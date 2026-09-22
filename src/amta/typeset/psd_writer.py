"""最小 PSD 写入器 — 零依赖，仅支持 RGB 像素图层。

设计目标：把干净底图 + 若干文字区域图层写成一个 .psd 文件，
让 Photoshop / Krita / Photopea 能打开并看到分层结构。

不支持的东西（刻意不做）：
- 可编辑文字层（TypeLayer）— 文字是渲染好的像素，图层名存文字内容
- 调整层、矢量层、智能对象
- 图层样式（描边/阴影作为像素预渲染，不是图层样式）
- 16位/32位色深

PSD 格式参考：Adobe Photoshop File Format Specification
所有多字节整数均为大端序（big-endian）。
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from PIL import Image


def _pascal_string(s: str, max_len: int = 255) -> bytes:
    """PSD 图层名用 Pascal 字符串：1 字节长度 + 内容，整体对齐到 4 字节。"""
    encoded = s.encode("utf-8")[:max_len]
    length_byte = bytes([len(encoded)])
    raw = length_byte + encoded
    # 对齐到 4 字节（包含 length byte）
    pad = (4 - (len(raw) % 4)) % 4
    return raw + b"\x00" * pad


def _channel_raw_data(channel_arr: np.ndarray) -> bytes:
    """单个通道的 raw（不压缩）像素数据，按行存储。"""
    return channel_arr.astype(np.uint8).tobytes()


def _build_layer_record(
    name: str,
    img: Image.Image,
    top: int,
    left: int,
    visible: bool = True,
) -> tuple[bytes, list[tuple[int, bytes]]]:
    """构建一个图层的记录头 + 各通道像素数据。

    返回 (layer_record_bytes, [(channel_id, channel_data_bytes), ...])。
    channel_id: 0=R, 1=G, 2=B, -1=transparency(A)
    """
    rgba = np.array(img.convert("RGBA"))
    h, w = rgba.shape[:2]
    bottom = top + h
    right = left + w

    # 通道数据：R, G, B, A
    channels = [
        (0, _channel_raw_data(rgba[:, :, 0])),
        (1, _channel_raw_data(rgba[:, :, 1])),
        (2, _channel_raw_data(rgba[:, :, 2])),
        (-1, _channel_raw_data(rgba[:, :, 3])),
    ]
    n_channels = len(channels)

    # ---- Layer record ----
    record = b""
    # 图层矩形：top, left, bottom, right（各 4 字节）
    record += struct.pack(">iiii", top, left, bottom, right)
    # 通道数
    record += struct.pack(">H", n_channels)
    # 每个通道的信息：channel_id (2字节, 有符号) + data_length (4字节)
    for cid, cdata in channels:
        # 压缩方式 2字节(raw=0) + 数据
        channel_total = 2 + len(cdata)
        record += struct.pack(">hI", cid, channel_total)

    # 混合模式：signature "8BIM" + key "norm"
    record += b"8BIM" + b"norm"
    # 不透明度 (1字节, 255=不透明)
    record += struct.pack(">B", 255)
    # clipping (1字节, 0=base)
    record += struct.pack(">B", 0)
    # flags (1字节): bit0=透明度存在, bit1=visible(0=可见, 1=隐藏)
    flags = 0x01  # 透明度存在
    if not visible:
        flags |= 0x02
    record += struct.pack(">B", flags)
    # filler (1字节)
    record += struct.pack(">B", 0)

    # Extra data length (4字节) — 包含 mask + blending ranges + layer name
    # 我们只写 layer name，mask 和 blending ranges 长度为 0
    layer_name_bytes = _pascal_string(name)
    # mask data length = 0, blending ranges length = 0
    extra_data = struct.pack(">I", 0) + struct.pack(">I", 0) + layer_name_bytes
    record += struct.pack(">I", len(extra_data))
    record += extra_data

    return record, channels


def write_psd(
    layers: list[tuple[str, Image.Image, int, int]],
    width: int,
    height: int,
    output_path: Path,
) -> None:
    """写入 PSD 文件。

    layers: [(name, image, top, left), ...] — 从底到顶的顺序。
            每个 image 是 PIL Image（会被转成 RGBA）。
    width, height: 画布尺寸（通常等于底图尺寸）。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 构建所有图层的记录和通道数据 ----
    layer_records: list[bytes] = []
    # 通道图像数据：按图层顺序，每个图层的通道按 R,G,B,A 排列
    channel_image_data: list[bytes] = []

    for name, img, top, left in layers:
        record, channels = _build_layer_record(name, img, top, left)
        layer_records.append(record)
        for cid, cdata in channels:
            # 每个通道：压缩方式 (2字节, 0=raw) + 数据
            channel_image_data.append(struct.pack(">H", 0) + cdata)

    # ---- Layer info section ----
    # 图层数：PSD 规范说如果为负数，绝对值是图层数，且第一个 alpha 通道是合并结果的透明度。
    # 我们用正数（图层数），但很多实现要求负数。实际上 Krita/Photoshop 都接受正数。
    # 为了最大兼容性，用负数：-n 表示 n 个图层，第一个 alpha 是透明度。
    layer_count = len(layers)
    layer_count_bytes = struct.pack(">h", -layer_count)

    layer_records_blob = b"".join(layer_records)
    channel_image_blob = b"".join(channel_image_data)

    # Layer info = layer_count + layer_records + channel_image_data
    layer_info = layer_count_bytes + layer_records_blob + channel_image_blob
    layer_info_length = len(layer_info)
    # 对齐到 2 字节
    if layer_info_length % 2 != 0:
        layer_info += b"\x00"
        layer_info_length += 1

    # ---- Layer and Mask Information section ----
    # 包含 Layer info + Global layer mask info (长度0)
    global_mask_info = struct.pack(">I", 0)  # length=0
    layer_and_mask = struct.pack(">I", layer_info_length + 4) + layer_info + global_mask_info

    # ---- 扁平化图像数据（Image Data section）----
    # PSD 要求最后有一个扁平化的合成图。我们把所有图层合成到一个 RGB 图上。
    composite = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for name, img, top, left in layers:
        composite.alpha_composite(img.convert("RGBA"), (left, top))
    composite_rgb = np.array(composite.convert("RGB"))
    # raw 压缩：2字节压缩标志 + R行 + G行 + B行
    image_data = struct.pack(">H", 0)  # raw
    for c in range(3):
        image_data += composite_rgb[:, :, c].astype(np.uint8).tobytes()

    # ---- File Header (26 bytes) ----
    header = b"8BPS"  # signature
    header += struct.pack(">H", 1)  # version
    header += b"\x00" * 6  # reserved
    header += struct.pack(">H", 3)  # channels (RGB, 不含alpha — 合成图是RGB)
    header += struct.pack(">I", height)
    header += struct.pack(">I", width)
    header += struct.pack(">H", 8)  # depth (8-bit)
    header += struct.pack(">H", 3)  # color mode (RGB=3)

    # ---- Color Mode Data (length=0 for RGB) ----
    color_mode = struct.pack(">I", 0)

    # ---- Image Resources (length=0) ----
    image_resources = struct.pack(">I", 0)

    # ---- 组装 ----
    psd_bytes = header + color_mode + image_resources + layer_and_mask + image_data

    with open(output_path, "wb") as f:
        f.write(psd_bytes)
