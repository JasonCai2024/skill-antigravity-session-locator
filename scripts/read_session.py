#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_session.py — 读取并解析 Antigravity 会话轨迹与产物。

用法:
    python read_session.py --session-id <uuid>
    python read_session.py --session-id <uuid> --summary
    python read_session.py --session-id <uuid> --turn 3
    python read_session.py --session-id <uuid> --artifacts
    python read_session.py --path "C:\\Users\\pc\\.gemini\\antigravity\\brain\\<uuid>\\.system_generated\\logs\\transcript.jsonl"
    python read_session.py --session-id <uuid> --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def resolve_antigravity_home(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ANTIGRAVITY_HOME")
    if env:
        return Path(env).expanduser()
    user_home = Path.home()
    base = user_home / ".gemini" / "antigravity"
    if base.exists():
        return base
    for env_var in ("LOCALAPPDATA", "APPDATA"):
        appdata = os.environ.get(env_var)
        if appdata:
            alt = Path(appdata) / "antigravity"
            if alt.exists():
                return alt
    return base


@dataclass
class StepTurn:
    step_index: int
    step_type: str
    source: str
    created_at: Optional[str]
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thinking: Optional[str] = None

    def preview(self, max_len: int = 100) -> str:
        s = self.content.replace("\n", " ").strip()
        if not s and self.tool_calls:
            names = [tc.get("name", "tool") for tc in self.tool_calls]
            s = f"[Tool Calls: {', '.join(names)}]"
        return s if len(s) <= max_len else s[: max_len - 3] + "..."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "type": self.step_type,
            "source": self.source,
            "created_at": self.created_at,
            "content_preview": self.preview(),
            "tool_call_count": len(self.tool_calls),
            "tool_calls": self.tool_calls,
        }


def read_antigravity_session(brain_path: Path, full_log: bool = False) -> Dict[str, Any]:
    if not brain_path.exists():
        raise FileNotFoundError(f"Brain 目录不存在: {brain_path}")

    log_file_name = "transcript_full.jsonl" if full_log else "transcript.jsonl"
    log_path = brain_path / ".system_generated" / "logs" / log_file_name
    if not log_path.exists() and full_log:
        log_path = brain_path / ".system_generated" / "logs" / "transcript.jsonl"

    if not log_path.exists():
        raise FileNotFoundError(f"未找到交互轨迹文件: {log_path}")

    turns: List[StepTurn] = []
    parse_errors: List[Dict[str, Any]] = []

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for lineno, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError as e:
                parse_errors.append({"line": lineno, "error": str(e), "raw": raw_line[:150]})
                continue

            step_idx = obj.get("step_index", len(turns))
            stype = obj.get("type", "UNKNOWN")
            source = obj.get("source", "UNKNOWN")
            created_at = obj.get("created_at")
            content = obj.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            tool_calls = obj.get("tool_calls") or []
            thinking = obj.get("thinking")

            turns.append(
                StepTurn(
                    step_index=step_idx,
                    step_type=stype,
                    source=source,
                    created_at=created_at,
                    content=content,
                    tool_calls=tool_calls if isinstance(tool_calls, list) else [tool_calls],
                    thinking=thinking,
                )
            )

    type_counts: Dict[str, int] = {}
    tool_call_count = 0
    for t in turns:
        type_counts[t.step_type] = type_counts.get(t.step_type, 0) + 1
        tool_call_count += len(t.tool_calls)

    artifacts: Dict[str, Any] = {}
    plan_file = brain_path / "implementation_plan.md"
    walkthrough_file = brain_path / "walkthrough.md"
    scratch_dir = brain_path / "scratch"

    if plan_file.exists():
        artifacts["implementation_plan"] = {
            "path": str(plan_file),
            "size_bytes": plan_file.stat().st_size,
            "preview": plan_file.read_text(encoding="utf-8", errors="ignore")[:300],
        }
    if walkthrough_file.exists():
        artifacts["walkthrough"] = {
            "path": str(walkthrough_file),
            "size_bytes": walkthrough_file.stat().st_size,
            "preview": walkthrough_file.read_text(encoding="utf-8", errors="ignore")[:300],
        }
    if scratch_dir.exists() and scratch_dir.is_dir():
        scratch_files = [str(p.relative_to(brain_path)) for p in scratch_dir.glob("**/*") if p.is_file()]
        artifacts["scratch_files"] = scratch_files

    return {
        "session_id": brain_path.name,
        "brain_path": str(brain_path),
        "log_path": str(log_path),
        "stats": {
            "total_steps": len(turns),
            "type_counts": type_counts,
            "tool_call_count": tool_call_count,
            "has_plan": plan_file.exists(),
            "has_walkthrough": walkthrough_file.exists(),
        },
        "artifacts": artifacts,
        "turns": turns,
        "parse_errors": parse_errors,
    }


def render_summary(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"Antigravity 会话 ID: {result['session_id']}")
    lines.append(f"Brain 路径:         {result['brain_path']}")
    lines.append(f"轨迹日志文件:       {result['log_path']}")
    stats = result["stats"]
    lines.append("")
    lines.append("统计信息:")
    lines.append(f"  总步数 (Steps):   {stats['total_steps']}")
    lines.append(f"  步类型分布:       {stats['type_counts']}")
    lines.append(f"  工具调用总数:     {stats['tool_call_count']}")
    lines.append(f"  包含实施计划:     {'是' if stats['has_plan'] else '否'}")
    lines.append(f"  包含改动总结:     {'是' if stats['has_walkthrough'] else '否'}")

    arts = result.get("artifacts", {})
    if arts:
        lines.append("")
        lines.append("产物 (Artifacts):")
        for k, v in arts.items():
            if isinstance(v, dict):
                lines.append(f"  - {k}: {v.get('path')} ({v.get('size_bytes')} 字节)")
            elif isinstance(v, list):
                lines.append(f"  - {k} ({len(v)} 个文件): {', '.join(v[:5])}")

    turns = result["turns"]
    lines.append("")
    lines.append(f"Step 轨迹列表 (共 {len(turns)} 步):")
    lines.append(f"{'#':<4} {'类型':<18} {'来源':<16} {'时间':<24} {'内容预览'}")
    lines.append("-" * 115)
    for t in turns:
        ts = (t.created_at or "")[:23]
        lines.append(f"{t.step_index:<4} {t.step_type:<18} {t.source:<16} {ts:<24} {t.preview(50)}")

    return "\n".join(lines)


def render_turn_detail(turn: StepTurn) -> str:
    lines = []
    lines.append(f"Step #{turn.step_index} [{turn.step_type}] (Source: {turn.source}, Time: {turn.created_at or '未知'})")
    lines.append("=" * 80)
    if turn.thinking:
        lines.append("【Thinking 思考过程】")
        lines.append(turn.thinking)
        lines.append("-" * 80)
    if turn.content:
        lines.append("【Content 文本正文】")
        lines.append(turn.content)
    if turn.tool_calls:
        lines.append("-" * 80)
        lines.append(f"【Tool Calls 工具调用 ({len(turn.tool_calls)} 个)】")
        for i, tc in enumerate(turn.tool_calls, 1):
            name = tc.get("name") or tc.get("toolAction") or "unknown_tool"
            args = tc.get("args") or tc.get("parameters") or tc
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
            lines.append(f"  {i}. {name}:\n{args_str}")
    lines.append("=" * 80)
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="read_session.py",
        description="读取并解析 Antigravity 会话轨迹与产物",
    )
    p.add_argument("--session-id", "-s", help="会话 UUID")
    p.add_argument("--path", "-p", help="transcript.jsonl 文件绝对路径或 brain 目录路径")
    p.add_argument("--antigravity-home", help="自定义 Antigravity 主目录")
    p.add_argument("--turn", "-t", type=int, help="输出指定 step_index 的完整内容")
    p.add_argument("--summary", action="store_true", help="输出结构化会话摘要（默认）")
    p.add_argument("--artifacts", action="store_true", help="仅查看会话实施计划与验证报告产物")
    p.add_argument("--full", action="store_true", help="优先读取未截断的 transcript_full.jsonl")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.session_id and not args.path:
        print("错误: 必须指定 --session-id 或 --path", file=sys.stderr)
        return 2

    brain_path = None
    if args.path:
        p = Path(args.path)
        if p.is_file():
            # 可能是 brain/<id>/.system_generated/logs/transcript.jsonl
            if p.parent.name == "logs" and p.parent.parent.name == ".system_generated":
                brain_path = p.parent.parent.parent
            else:
                brain_path = p.parent
        else:
            brain_path = p
    else:
        base_dir = resolve_antigravity_home(args.antigravity_home)
        brain_path = base_dir / "brain" / args.session_id

    try:
        data = read_antigravity_session(brain_path, full_log=args.full)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    if args.artifacts:
        arts = data.get("artifacts", {})
        if args.json:
            print(json.dumps(arts, ensure_ascii=False, indent=2))
        else:
            print(f"Antigravity 会话 {data['session_id']} 核心产物清单:")
            print("=" * 80)
            if not arts:
                print("该会话未生成 implementation_plan.md 或 walkthrough.md。")
            for k, v in arts.items():
                if isinstance(v, dict):
                    print(f"\n--- {k} ({v.get('path')}) ---")
                    print(v.get("preview", ""))
                elif isinstance(v, list):
                    print(f"\n--- {k} ---")
                    for sf in v:
                        print(f"  {sf}")
        return 0

    if args.turn is not None:
        turns = data["turns"]
        target = next((t for t in turns if t.step_index == args.turn), None)
        if not target:
            # 尝试按 1-based index 查找
            if 1 <= args.turn <= len(turns):
                target = turns[args.turn - 1]
            else:
                print(f"错误: 未找到 step_index={args.turn} 的步（共 {len(turns)} 步）", file=sys.stderr)
                return 2
        if args.json:
            print(json.dumps(target.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_turn_detail(target))
        return 0

    if args.json:
        out = {
            "session_id": data["session_id"],
            "brain_path": data["brain_path"],
            "log_path": data["log_path"],
            "stats": data["stats"],
            "artifacts": data["artifacts"],
            "turns": [t.to_dict() for t in data["turns"]],
            "parse_errors": data["parse_errors"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
