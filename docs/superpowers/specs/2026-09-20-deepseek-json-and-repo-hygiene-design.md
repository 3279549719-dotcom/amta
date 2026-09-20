# DeepSeek JSON 输出与仓库卫生设计

## 目标

在不改变漫画翻译业务流程、不重构排字模块、不启动长文本 VLM OCR 的前提下，完成三项技术收口：

1. 普通对白翻译固定使用 DeepSeek Flash 非思考模式，并启用官方 JSON object 输出格式。
2. 修复 Windows 下项目位于 E 盘、uv 默认缓存位于 C 盘时的跨盘持久化错误。
3. 清除误提交的 pytest 临时文件，并防止其再次进入 Git。

## 已确认决策

- `21fc2f4` 未合并到 `main`，不在本次恢复或重做 text-ink mask。
- `src/amta/typeset/` 已经通过单一工位入口对外，当前不做排字重构。
- 普通漫画对白翻译使用 `thinking: {"type": "disabled"}`，不启用自动分流。
- 保留 Chat Completions。DeepSeek 的该接口已经支持文字、图片和 JSON object；本次不迁移 Responses API。
- p55、p60、p63、p67 的 VLM OCR 属于后续独立任务，本次只保留未来可复用的消息内容块能力。
- 最后一次提交带入的 25 个 probe 暂不删除；它们的保留、归档或删除属于独立的 Selection。

## 深模块设计

### DeepSeek 网络模块

`src/amta/backends/chat_client.py` 继续作为唯一网络接缝。它隐藏 URL 拼接、Bearer 鉴权、HTTP 错误和 `choices[0].message` 解析；调用方不直接使用 `requests`。

现有 `chat()` / `chat_text()` 接口不扩张为 provider 类层级，也不增加 Responses adapter。请求体的 DeepSeek 可选字段继续通过已有 `**extra` 进入实现，因此没有第二个真实 adapter 时不制造假接缝。

### 翻译领域模块

`src/amta/translation/translate.py` 拥有翻译输出契约。LLM 输出由裸数组：

```json
["译文一", "译文二"]
```

改为 JSON object：

```json
{"translations": ["译文一", "译文二"]}
```

翻译模块负责验证：

- 顶层必须是 object；
- `translations` 必须是数组；
- 数组长度必须等于输入 region 数；
- 每个值最终规范化为字符串；
- 失败时保持当前行为：该批次返回空译文，不静默错绑 region。

翻译请求显式传入：

```python
response_format={"type": "json_object"}
thinking={"type": "disabled"}
```

Prompt 同时明确要求顶层 object 和 `translations` 键。DeepSeek 官方说明 JSON mode 仍需要在提示词中要求生成 JSON，否则可能持续输出空白，因此请求参数和 prompt 缺一不可。

### VLM 延展点

未来长文本 OCR 继续通过 `chat_client.chat()` 发送 `user.content` 内容块数组，其中可包含 `text` 与 `image_url`。这已经被当前 `messages: list[dict]` 接口容纳，本次不新增 VLM 专用公共接口。

## uv 缓存修复

项目在 `pyproject.toml` 的现有 `[tool.uv]` 中增加仓库本地、同盘缓存目录配置，并把缓存目录加入 `.gitignore`。配置不能另建会覆盖现有 index 设置的 `uv.toml`。验收标准是：清除当前 shell 的 `UV_CACHE_DIR` 覆盖后，在 E 盘仓库中直接运行 `uv run python -c "print('ok')"` 成功，不再要求 `--no-cache`。

缓存属于可再生运行数据，不进入 Git。方案必须使用相对项目路径，不能写死当前用户目录或盘符。

## 仓库卫生

- 从 Git 删除全部已跟踪的 `.pytest_tmp/**`。
- `.gitignore` 增加根级 `/.pytest_tmp/`。
- pytest 的 `basetemp` 固定为项目同盘的 `.pytest_tmp`，避开 Windows 全局临时目录中无权限的陈旧链接；该目录始终被忽略。
- 不删除 `scripts/probes/`，避免在没有用户选择的情况下丢弃可能仍有研究价值的实验脚本。

## 错误处理

- HTTP 非 2xx 继续由 `raise_for_status()` 抛出，不吞掉服务端错误。
- DeepSeek 返回畸形消息时，网络模块继续返回空 content；翻译模块把不合约的 JSON 转成整批空译文。
- `finish_reason="length"` 造成的截断会表现为 JSON 解析失败，仍按不合约处理；本次不增加重试或自动拆批。

## 测试策略

按照 TDD 顺序实施：

1. 为网络接缝增加失败测试，断言翻译调用发送 `response_format` 和关闭 thinking。
2. 为翻译解析增加失败测试，覆盖合法 object、裸数组拒绝、缺键、错误长度和非数组值。
3. 写最小实现使测试通过。
4. 运行相关测试，再运行完整 pytest、Ruff、Pyright 和仓库 full gate。
5. 验证 Git 中不存在 `.pytest_tmp` 路径，并验证默认 uv 命令可在 E 盘运行。

## 非目标

- 不补齐 p55、p60、p63、p67。
- 不实现 VLM OCR 或 OCR 置信度自动路由。
- 不恢复 `21fc2f4`。
- 不重构排字模块。
- 不切换 Responses API。
- 不删除或归档 probe。
