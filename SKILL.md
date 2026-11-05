---
name: skill-antigravity-session-locator
description: 定位 Google Antigravity (AGY) 本地会话。支持按工作区目录(CWD/Workspace)、更新或创建时间窗、归档状态(Archived/Active)、会话标题与对话关键词过滤，并按需提取会话轨迹 transcript 与实施方案 artifacts。当用户通过项目路径或时间找 Antigravity 会话时使用。触发话术包括 找Antigravity会话, 定位AGY历史, resume Antigravity by workspace.
disable-model-invocation: true
user-invocable: true
argument-hint: [workspace-path, time-hint]
---

# Skill Antigravity Session Locator

## Goal

根据用户提供的工作区路径（Workspace / CWD）、大致更新时间、归档状态或对话关键词，快速定位 Antigravity 本地会话索引记录，并按需解析其轨迹（`transcript.jsonl`）与产物（`implementation_plan.md` / `walkthrough.md`），供跨智能体接力、历史复盘或继续开发使用。

## Required Inputs

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `workspace` | 路径字符串 | 否* | 会话绑定的工作区目录或子目录关键词；大小写不敏感模糊匹配，自动解码 URL 编码（如中文） |
| `time_hint` | 时间字符串 | 否* | 会话更新时间提示，支持自然语言（"昨天" / "yesterday" / "上周" / "3pm"）或 ISO 格式（"2026-08-22"） |
| `title` | 字符串 | 否 | 会话侧边栏标题或初始提问关键词过滤 |
| `keyword` | 字符串 | 否 | 对话全文交互关键词过滤 |
| `archived_mode` | 枚举 | 否 | `all`（默认，全部）、`archived_only`（仅已归档）、`active_only`（仅活跃会话） |
| `antigravity_home`| 路径 | 否 | Antigravity 数据主目录，覆盖 `ANTIGRAVITY_HOME` 环境变量；默认 `~/.gemini/antigravity/` |
| `limit` | 整数 | 否 | 候选返回上限，默认 `10` |

> \*注：`workspace`、`time_hint`、`keyword`、`title` 中至少应提供一个过滤条件；若全不提供，默认返回按最新更新时间排序的前 10 个会话。

## Workflow

### Step 1：解析 ANTIGRAVITY_HOME 根目录
1. 读取 `--antigravity-home` 参数；若未提供则读取环境变量 `ANTIGRAVITY_HOME`。
2. 若未设置则使用 `Path.home() / ".gemini" / "antigravity"`（Windows 备用路径 `%LOCALAPPDATA%\antigravity`）。
3. 验证 `conversations/` 目录存在性，不存在则中止并返回路径错误。

### Step 2：时间提示解析为窗口
1. 若用户提供了自然语言时间提示，调用 `scripts/locate_session.py --time "<hint>"` 解析为 `(start_utc, end_utc)`。
2. 时间窗跨度超过 30 天时报错，引导用户缩窄范围。

### Step 3：多维度扫描会话候选
1. 遍历 `conversations/*.db`，按文件修改时间（`mtime`）倒序排序。
2. 连接数据库读取 `trajectory_metadata_blob` 中 `id='main'` 记录，正则提取工作区 URI，并调用 `urllib.parse.unquote` 解码为本地标准路径。
3. 读取对应 `annotations/<id>.pbtxt`，秒级提取 `title`、`is_archived` 与 `archived_at`。
4. 若指定了 `--keyword`，在 `brain/<id>/.system_generated/logs/transcript.jsonl` 中全文检索。
5. 检查 `brain/<id>/` 下是否存在 `implementation_plan.md` 与 `walkthrough.md`。

### Step 4：候选判定与用户决策
1. **1 个候选**：直接进入 Step 5 读取详情。
2. **多个候选**：展示会话列表（包含 Session ID、状态、产物标记、更新时间、标题及工作区），由用户确认。
3. **0 个候选**：返回 0 匹配；输出本地已发现的工作区候选列表供用户纠偏。

### Step 5：提取会话轨迹与产物
1. 调用 `scripts/read_session.py --session-id <id> --summary` 输出关键统计与 Turn 列表。
2. 若用户需要查验实施计划，调用 `scripts/read_session.py --session-id <id> --artifacts`。
3. 若用户需要复现具体对话，调用 `scripts/read_session.py --session-id <id> --turn <N>`。

## Decision Rules

1. **中文路径匹配规则**：SQLite 中存储的 URI 为 URL 编码形态（例如 `%E7%A4%BE%E4%BA%A4%E5%AA%92%E4%BD%93`），定位器必须在解码后再与用户输入进行匹配。
2. **归档状态判断规则**：以 `annotations/<id>.pbtxt` 中的 `archived: true` 为准。归档会话在本地不搬移路径，保持原位。
3. **首轮提问回退**：若会话无用户命名标题，自动读取 `transcript.jsonl` 中首轮 `USER_INPUT` 的前 80 字符作为标题展示。
4. **多候选歧义处理**：存在多条匹配时，不得擅自替用户做选择，必须以结构化表格呈现场景供用户确认。

## Output Requirements

### 定位命令输出 (`scripts/locate_session.py --json`)
```json
{
  "antigravity_home": "C:\\Users\\pc\\.gemini\\antigravity",
  "query": {
    "workspace_keyword": "ForAgent",
    "time_window": {
      "start_utc": "2026-09-04T00:00:00Z",
      "end_utc": "2026-09-05T23:59:59Z"
    },
    "archived_mode": "all"
  },
  "matches": [
    {
      "session_id": "967076da-4fa3-475b-9755-819873840fb1",
      "title": "构建会话定位技能",
      "workspace": "E:\\BaiduSyncdisk\\WorkSpace\\ForAgent",
      "is_archived": false,
      "archived_at": null,
      "updated_at": "2026-09-05 14:54:45",
      "has_plan": true,
      "has_walkthrough": false,
      "brain_path": "C:\\Users\\pc\\.gemini\\antigravity\\brain\\967076da-...",
      "transcript_path": "C:\\Users\\pc\\.gemini\\antigravity\\brain\\967076da-...\\transcript.jsonl"
    }
  ],
  "match_count": 1
}
```

### 读取命令输出 (`scripts/read_session.py --summary`)
输出会话 ID、工作区、统计信息（步数分布、工具调用量、产物状态）及前/后轮次预览。

## Validation

1. **路径有效性**：验证 `ANTIGRAVITY_HOME/conversations` 目录存在。
2. **工作区解码**：中文路径必须正确还原为非乱码形态。
3. **时间窗约束**：时间窗跨度不能超过 30 天。
4. **日志完整性**：读取 JSONL 时校验每行 JSON 合法性，统计跳过错误行。

## Fallback

| 异常情况 | 降级处理策略 |
| :--- | :--- |
| 未找到符合条件的会话 | 输出本地出现频率最高的 20 个工作区路径供用户核对 |
| 会话未生成 `transcript.jsonl` | 提示日志未生成，仅输出 SQLite 与 annotations 元数据 |
| 无法解析自然语言时间 | 回退到最近 7 天窗口并在控制台告警提示 |
| `annotations/*.pbtxt` 缺失 | 标题回退为 `(无标题)`，归档状态默认视为活跃 |

## Examples

### 触发示例
- `帮我找昨天在 E:\BaiduSyncdisk\WorkSpace\ForAgent 跑的 Antigravity 会话`
- `查看上周做过 implementation_plan 的 Antigravity 会话`
- `查找包含“视频号”关键词的已归档 Antigravity 会话`
- `定位最近一次关于 openclaw 的 Antigravity 记录`

### 执行命令示例
```powershell
# 1. 查找指定工作区在昨天的会话
python scripts/locate_session.py --workspace "ForAgent" --time "yesterday"

# 2. 仅查找已归档的会话并输出 JSON
python scripts/locate_session.py --archived-only --limit 5 --json

# 3. 查看会话摘要与产物
python scripts/read_session.py --session-id <uuid> --summary
python scripts/read_session.py --session-id <uuid> --artifacts
```

## Reference

- 存储架构细节：`references/antigravity-storage.md`
- 数据库与元数据结构：`references/db-and-annotation-schema.md`
