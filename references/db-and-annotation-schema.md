# Antigravity 数据库与元数据 Schema 参考

本文档记录 Antigravity 会话的 SQLite 内部表结构与 Protobuf Text (`.pbtxt`) 字段说明。

## 1. `conversations/<id>.db` 表结构

每个会话拥有独立的 SQLite 数据库，WAL 模式运行。

### 1.1 表清单
- `trajectory_metadata_blob`: 核心元数据（工作区 URI、框架状态）
- `steps`: 交互执行步骤（`step_index`、`created_at`、执行结果）
- `session_metadata`: 会话属性与执行器配置

### 1.2 `trajectory_metadata_blob`
- `id`: TEXT PRIMARY KEY（主记录通常为 `'main'`）
- `data`: BLOB 二进制序列化数据

**工作区解析逻辑**：
通过正则匹配二进制数据中的 `rb"file:///([^\x00-\x1f\x7f-\xff]+)"`，获取绝对 URI 路径，再通过 URL 解码转换为本地标准路径格式。

---

## 2. `annotations/<id>.pbtxt` 字段说明

文本 Protobuf 格式，无需依赖 Protobuf 编译即可纯正则/字符串解析。

### 关键字段
```protobuf
title: "会话侧边栏显示的标题"
last_user_view_time: {
  seconds: 1787239447
  nanos: 123456789
}
archived: true
archival_status_timestamp: {
  seconds: 1787240697
  nanos: 483657700
}
```

- `title`: 用户修改后的自定义标题或大模型自动总结的标题。
- `archived`: 布尔值。存在且为 `true` 时表示会话已归档。
- `archival_status_timestamp`: 归档发生的 Unix 秒数。
- `last_user_view_time`: 用户最后在 Antigravity 界面打开该会话的时间戳。

---

## 3. `transcript.jsonl` 行结构

每一行均为标准 JSON 对象：
```json
{
  "step_index": 0,
  "source": "USER_EXPLICIT",
  "type": "USER_INPUT",
  "status": "DONE",
  "created_at": "2026-09-05T14:51:30Z",
  "content": "<USER_REQUEST>用户的初始输入...</USER_REQUEST>",
  "thinking": "模型思考过程...",
  "tool_calls": [
    {
      "name": "view_file",
      "args": {"AbsolutePath": "..."}
    }
  ]
}
```

### 关键字段说明
- `type`: `USER_INPUT` (用户)、`PLANNER_RESPONSE` (模型回复或工具调用)、`GENERIC` (系统输出/工具结果)、`CHECKPOINT` (检查点)。
- `content`: 用户提问文本或助手回复文本。
- `tool_calls`: 该 step 触发的工具调用列表及参数。
- `thinking`: 模型的内部思考推理过程。
