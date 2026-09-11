"""一键上传本地文件到飞书云空间并生成公网链接。

用法：
    uv run python scripts/share_file.py --file output/report.html
    uv run python scripts/share_file.py --file output/report.html --name "自定义名称.html"

输出：公网链接（互联网任何人可阅读，无需登录）

本质：封装 lark-cli 的 3 步操作为 1 条命令：
  1. drive +upload 上传文件
  2. 解析返回的 file_token
  3. permission.public patch 设置 external_access=true + link_share_entity=anyone_readable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run_lark(args: list[str]) -> dict:
    """运行 lark-cli 命令，返回解析后的 JSON。"""
    # 清除代理环境变量（127.0.0.1:7890 不可达会导致连接失败）
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(key, None)

    result = subprocess.run(
        ["lark-cli"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    # lark-cli 可能把响应存到 download.txt（二进制响应）
    download_path = Path("download.txt")
    if download_path.exists():
        raw = download_path.read_text(encoding="utf-8")
        download_path.unlink(missing_ok=True)
        return json.loads(raw)

    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f"lark-cli 失败: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # 可能是多行输出，尝试提取 JSON
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise RuntimeError(f"无法解析 lark-cli 输出: {result.stdout[:200]}")


def share_file(file_path: str, name: str | None = None) -> str:
    """上传文件并设置公开权限，返回公网链接。"""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    upload_name = name or path.name

    # 第 1 步：上传
    print(f"[1/3] 上传 {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)...")
    upload_args = ["drive", "+upload", "--file", str(path), "--name", upload_name]
    upload_result = _run_lark(upload_args)

    if not upload_result.get("ok"):
        raise RuntimeError(f"上传失败: {upload_result.get('error', upload_result)}")

    file_token = upload_result["data"]["file_token"]
    print(f"      file_token: {file_token}")

    # 第 2 步：设置公开权限
    print("[2/3] 设置公开权限（互联网任何人可阅读）...")
    params = json.dumps({"token": file_token, "type": "file"})
    data = json.dumps({"external_access": True, "link_share_entity": "anyone_readable"})
    perm_args = [
        "drive", "permission.public", "patch",
        "--params", params,
        "--data", data,
        "--yes",
    ]
    perm_result = _run_lark(perm_args)

    if (
        perm_result.get("code") != 0
        and not perm_result.get("ok")
        and "permission_public" not in str(perm_result)
    ):
        raise RuntimeError(f"权限设置失败: {perm_result}")

    # 第 3 步：返回链接
    url = f"https://my.feishu.cn/file/{file_token}"
    print(f"[3/3] 完成！公网链接: {url}")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="一键上传文件到飞书云空间并生成公网链接")
    parser.add_argument("--file", required=True, help="本地文件路径")
    parser.add_argument("--name", default=None, help="上传后的文件名（默认用本地文件名）")
    args = parser.parse_args()

    try:
        url = share_file(args.file, args.name)
        print(f"\n✅ 公网链接（手机直接点开）: {url}")
    except Exception as e:
        print(f"\n❌ 失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
