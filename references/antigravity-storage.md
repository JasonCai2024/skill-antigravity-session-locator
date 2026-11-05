# Antigravity 会话存储结构参考

本文档汇总 Google Antigravity (AGY) 本地会话的存储介质、目录层级与资产组织规则，作为 `skill-antigravity-session-locator` 的底层技术参考。

## 1. 存储总览与根路径优先级

Antigravity 的全部会话数据保存在本地应用目录中。主目录解析优先级如下：

1. 命令行 `--antigravity-home` 参数
2. 环境变量 `ANTIGRAVITY_HOME`
3. 默认路径：
   - **Windows**：`C:\Users\<用户名>\.gemini\antigravity\`（或 `%LOCALAPPDATA%\antigravity\`）
   - **macOS / Linux**：`~/.gemini/antigravity/`

每一个会话由全局唯一的 UUID（例如 `6f38c3da-bf5b-48be-aaa6-198951df88d4`）作为 Conversation ID。

---

## 2. 核心存储介质及职责划分

| 存储路径 | 存储格式 | 核心内容 | 定位与读取价值 |
| :--- | :--- | :--- | :--- |
| `annotations/<id>.pbtxt` | Protobuf Text | 会话侧边栏标题、归档标志（`archived: true`）、归档时间戳、最后查看时间 | **最高**：秒级判断活跃/归档状态与标题，无数据库锁定风险 |
| `conversations/<id>.db` | SQLite 3 (WAL) | 状态机步骤（`steps`）、绑定的项目工作区（`trajectory_metadata_blob`） | **最高**：最权威获取工作区物理路径来源 |
| `brain/<id>/.system_generated/logs/transcript.jsonl` | JSONL | 结构化交互轨迹（按 step 逐行记录 User 提问、Agent 回复、工具调用） | **极高**：全文检索关键词、提取首轮需求与最新结论 |
| `brain/<id>/.system_generated/logs/transcript_full.jsonl` | JSONL | 包含未截断工具输出、完整思维链 (Thinking) 与代码的完整交互轨迹 | **高**：排障复盘与细节追溯 |
| `brain/<id>/implementation_plan.md` | Markdown | Agent 生成的技术实施方案（Artifact） | **高**：快速了解会话既定方案 |
| `brain/<id>/walkthrough.md` | Markdown | Agent 生成的最终改动总结与验证记录（Artifact） | **高**：快速获取会话已完成的工作与验证结果 |
| `brain/<id>/scratch/` | 目录 | Agent 在会话过程中编写的临时探针、脚本与中间数据 | **中**：复用已有排查工具与临时数据 |
| `brain/<id>/.system_generated/tasks/` | 文本日志 | 后台长任务与命令的 stdout/stderr（`task-<id>.log`） | **中**：检查后台构建、测试或服务日志 |

---

## 3. 归档会话（Archived Sessions）特性

Antigravity 对归档会话采用 **“就地元数据标记（In-Place State Flagging）”** 机制：

1. **文件绝对不搬迁**：
   - 会话数据库依然位于 `conversations/<id>.db`；
   - 资产与日志依然位于 `brain/<id>/`。
   - 保证了跨会话 `@mention`（例如 `@conversation://<id>`）和直接脚本定位永不失效。
2. **状态标记存放在 `annotations/<id>.pbtxt`**：
   - 归档会话包含 `archived: true` 与 `archival_status_timestamp`。
   - 活跃会话该字段缺失或为 `false`。

---

## 4. 工作区 URI 编码处理机制

在 `conversations/<id>.db` 的 `trajectory_metadata_blob` 中，工作区路径以 `file:///` URI 保存，当路径中包含中文或特殊字符时，采用标准 URL 编码（例如中文目录 `社交媒体` 会被保存为 `%E7%A4%BE%E4%BA%A4%E5%AA%92%E4%BD%93`）。

因此，定位脚本必须使用 `urllib.parse.unquote` 解码后再做大小写不敏感匹配，保证中文工作区精准召回。
