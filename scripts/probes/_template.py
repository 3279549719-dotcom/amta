"""<一句话说明这个 probe 干什么>。

用法：uv run python scripts/probes/<this_file>.py [参数]

复制本文件改名后再写逻辑；下划线开头的文件不会被当作正式 probe。
"""
from __future__ import annotations

# ── 每个 probe 的固定头部，不要删 ───────────────────────────────
# 下面这行 import amta 会触发包级 UTF-8 stdout 收口
# （见 src/amta/common/encoding.py 的 force_utf8_stdio）。
# 没有它，print 中文在 Windows 管道里会变成乱码，
# 报错信息也只会说"输出中文但没到 UTF-8 收口点"。
import amta  # noqa: F401  (UTF-8 stdout choke point)

# ───────────────────────────────────────────────────────────────


def main() -> None:
    # TODO: 在这里写你的探测逻辑
    print("probe template: hello")


if __name__ == "__main__":
    main()
