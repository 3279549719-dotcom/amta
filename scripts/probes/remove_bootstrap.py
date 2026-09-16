"""删掉 state.py 的 bootstrap 子命令。"""
import io
import re

path = "scripts/state.py"
content = io.open(path, encoding="utf-8").read()

# 1. 删 docstring 里的 bootstrap 行
old_doc = """三个子命令，这就是全部（2026-09-12 收尾规程收敛：三套说法合成一套）：

  对话开始：uv run python scripts/state.py bootstrap
  改到一半：uv run python scripts/state.py check      # 秒级只读，任何时候都能跑
  对话结束：uv run python scripts/state.py finish "说明"   # 全量质检 + 提交，唯一收尾入口"""

new_doc = """两个子命令，这就是全部：

  改到一半：uv run python scripts/state.py check      # 秒级只读，任何时候都能跑
  对话结束：uv run python scripts/state.py finish "说明"   # 全量质检 + 提交，唯一收尾入口"""

assert old_doc in content, "docstring not found"
content = content.replace(old_doc, new_doc)

# 2. 删 bootstrap 的 argparse 定义
old_boot = """    # bootstrap
    p_boot = sub.add_parser("bootstrap", help="对话开始：读取 git + env 状态，输出统一格式的状态摘要")
    p_boot.add_argument("--no-env", action="store_true", help="跳过环境自检")
    p_boot.set_defaults(func=_cmd_bootstrap)

"""
assert old_boot in content, "argparse bootstrap not found"
content = content.replace(old_boot, "")

# 3. 删 _cmd_bootstrap 函数
m = re.search(r"def _cmd_bootstrap.*?(?=\ndef |\Z)", content, re.DOTALL)
assert m, "_cmd_bootstrap not found"
content = content.replace(m.group(0), "")

# 4. 删 import 里的 StateManager（只被 bootstrap 用）
content = content.replace(
    "from amta.common.state_manager import QualityGateFailed, StateManager, finish_verified",
    "from amta.common.state_manager import QualityGateFailed, finish_verified"
)

# 5. 删 docstring 里"为什么只有这三条"那段（提到了 bootstrap）
old_why = """**为什么只有这三条**：此前"收尾"有三种写法——CLAUDE.md 说 state.py finish、
cycle-close skill 说 npm run finish + 手工 git add、verify skill 又说第三套，
而这三份说法互相矛盾（其中一份还写着"本仓无 lint/无 typecheck"这样的假事实）。
规程一多，AI 每次收尾都得现场仲裁该信哪一份——那才是真正的不顺畅。"""
# 这段保留，因为它是历史背景，不是 bootstrap 相关

io.open(path, "w", encoding="utf-8", newline="\n").write(content)
print("Done. bootstrap removed.")
