#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
locate_session.py — 定位 Google Antigravity (AGY) 本地会话。

用法:
    python locate_session.py --workspace "ForAgent" --time "yesterday"
    python locate_session.py --workspace "社交媒体" --limit 5
    python locate_session.py --archived-only --limit 10
    python locate_session.py --keyword "视频号" --json

输出:
    默认人类可读表格；--json 时输出结构化 JSON。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_LIMIT = 10
MAX_WINDOW_DAYS = 30


@dataclass
class TimeWindow:
    start_utc: datetime
    end_utc: datetime
    parsed_from: str

    def width_days(self) -> float:
        return (self.end_utc - self.start_utc).total_seconds() / 86400


_CN_TOD = [
    ("凌晨", (0, 6)),
    ("上午", (6, 12)),
    ("中午", (11, 14)),
    ("下午", (12, 18)),
    ("傍晚", (17, 20)),
    ("晚上", (18, 24)),
    ("夜里", (20, 24)),
    ("深夜", (22, 24)),
]

_EN_TOD = [
    ("early morning", (0, 6)),
    ("late night", (22, 24)),
    ("morning", (6, 12)),
    ("noon", (11, 14)),
    ("afternoon", (12, 18)),
    ("evening", (17, 20)),
    ("night", (18, 24)),
]


def parse_time_hint(hint: str, now: Optional[datetime] = None) -> TimeWindow:
    if now is None:
        now = datetime.now().astimezone()

    hint_norm = hint.strip().lower()
    if not hint_norm:
        raise ValueError("时间提示为空")

    iso = _try_parse_iso(hint_norm, now)
    if iso:
        return iso

    day_anchor, consumed = _parse_day_anchor(hint_norm, now)
    if day_anchor is None:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_anchor, consumed = today, ""

    remainder = hint_norm.replace(consumed, "").strip()
    start_t, end_t = _match_time_of_day(remainder)

    hour_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", remainder)
    if hour_match:
        h = int(hour_match.group(1))
        m = int(hour_match.group(2) or 0)
        ampm = hour_match.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23:
            start_dt = day_anchor.replace(hour=h, minute=m, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=4)
            return TimeWindow(start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), hint)

    end_hour = 23 if end_t == 24 else end_t
    end_minute = 59 if end_t == 24 else 0
    end_second = 59 if end_t == 24 else 0
    start_dt = day_anchor.replace(hour=start_t, minute=0, second=0, microsecond=0)
    end_dt = day_anchor.replace(hour=end_hour, minute=end_minute, second=end_second, microsecond=0)
    return TimeWindow(start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), hint)


def _try_parse_iso(hint: str, now: datetime) -> Optional[TimeWindow]:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(hint, fmt).replace(tzinfo=now.tzinfo)
            return TimeWindow(
                (dt - timedelta(hours=2)).astimezone(timezone.utc),
                (dt + timedelta(hours=2)).astimezone(timezone.utc),
                hint,
            )
        except ValueError:
            pass
    try:
        d = datetime.strptime(hint, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
        return TimeWindow(
            d.astimezone(timezone.utc),
            (d + timedelta(days=1) - timedelta(seconds=1)).astimezone(timezone.utc),
            hint,
        )
    except ValueError:
        return None


def _parse_day_anchor(hint: str, now: datetime) -> Tuple[Optional[datetime], str]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\btoday\b|今天", hint):
        return today, "today" if "today" in hint else "今天"
    if re.search(r"\byesterday\b|昨天", hint):
        return today - timedelta(days=1), "yesterday" if "yesterday" in hint else "昨天"
    if re.search(r"day before yesterday|前天", hint):
        consumed = "day before yesterday" if "day before yesterday" in hint else "前天"
        return today - timedelta(days=2), consumed
    m = re.search(r"(\d+)\s*days?\s*ago|(\d+)\s*天前", hint)
    if m:
        n = int(m.group(1) or m.group(2))
        return today - timedelta(days=n), m.group(0)
    if re.search(r"\blast\s+week\b|上周", hint):
        consumed = "last week" if "last week" in hint else "上周"
        return today - timedelta(days=7), consumed
    m = re.search(r"\d{4}-\d{2}-\d{2}", hint)
    if m:
        try:
            d = datetime.strptime(m.group(0), "%Y-%m-%d")
            return d.replace(tzinfo=now.tzinfo), m.group(0)
        except ValueError:
            pass
    return None, ""


def _match_time_of_day(remainder: str) -> Tuple[int, int]:
    for kw, (s, e) in _CN_TOD:
        if kw in remainder:
            return s, e
    for kw, (s, e) in _EN_TOD:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, remainder):
            return s, e
    return 0, 24


def resolve_antigravity_home(explicit: Optional[str]) -> Path:
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


def parse_workspace_from_db(db_path: Path) -> Optional[str]:
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT data FROM trajectory_metadata_blob WHERE id='main';")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            m = re.search(rb"file:///([^\x00-\x1f\x7f-\xff]+)", row[0])
            if m:
                raw_path = m.group(1).decode("utf-8", errors="ignore")
                decoded_path = urllib.parse.unquote(raw_path)
                if re.match(r"^[a-zA-Z]:", decoded_path):
                    return decoded_path.replace("/", "\\")
                elif decoded_path.startswith("/") and len(decoded_path) > 2 and decoded_path[2] == ":":
                    return decoded_path[1:].replace("/", "\\")
                return decoded_path
    except Exception:
        pass
    return None


def parse_annotation(pbtxt_path: Path) -> Tuple[Optional[str], Optional[str], bool, Optional[str], Optional[int]]:
    title = None
    last_view = None
    is_archived = False
    archived_at = None
    archived_ts = None
    if pbtxt_path.exists():
        try:
            content = pbtxt_path.read_text(encoding="utf-8", errors="ignore")
            is_archived = "archived:true" in content or "archived: true" in content
            m_title = re.search(r'title:\s*"([^"]+)"', content)
            if m_title:
                title = m_title.group(1)
            m_time = re.search(r"last_user_view_time:\s*\{\s*seconds:\s*(\d+)", content)
            if m_time:
                last_view = datetime.fromtimestamp(int(m_time.group(1)), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            m_arch = re.search(r"archival_status_timestamp:\s*\{\s*seconds:\s*(\d+)", content)
            if m_arch:
                archived_ts = int(m_arch.group(1))
                archived_at = datetime.fromtimestamp(archived_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return title, last_view, is_archived, archived_at, archived_ts


def parse_transcript_summary(brain_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    t_file = brain_path / ".system_generated" / "logs" / "transcript.jsonl"
    first_prompt = None
    created_at = None
    full_text_parts = []
    if t_file.exists():
        try:
            with open(t_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    full_text_parts.append(line)
                    if first_prompt is None:
                        try:
                            data = json.loads(line)
                            if data.get("type") == "USER_INPUT":
                                content = data.get("content", "")
                                clean = re.sub(r"<[^>]+>", "", content).strip()
                                first_prompt = clean[:80].replace("\n", " ")
                                created_at = data.get("created_at")
                        except Exception:
                            pass
        except Exception:
            pass
    return first_prompt, created_at, str(t_file) if t_file.exists() else None, "".join(full_text_parts)


@dataclass
class SessionRecord:
    session_id: str
    title: str
    workspace: str
    is_archived: bool
    archived_at: Optional[str]
    updated_at: str
    updated_at_dt: datetime
    created_at: str
    last_view_at: str
    has_plan: bool
    has_walkthrough: bool
    brain_path: str
    transcript_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "workspace": self.workspace,
            "is_archived": self.is_archived,
            "archived_at": self.archived_at,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
            "last_view_at": self.last_view_at,
            "has_plan": self.has_plan,
            "has_walkthrough": self.has_walkthrough,
            "brain_path": self.brain_path,
            "transcript_path": self.transcript_path,
        }


def locate_antigravity_sessions(
    base_dir: Path,
    workspace_kw: Optional[str] = None,
    time_window: Optional[TimeWindow] = None,
    title_kw: Optional[str] = None,
    keyword_kw: Optional[str] = None,
    archived_mode: str = "all",
    limit: int = DEFAULT_LIMIT,
) -> Tuple[List[SessionRecord], List[Tuple[str, int]]]:
    conv_dir = base_dir / "conversations"
    brain_dir = base_dir / "brain"
    annot_dir = base_dir / "annotations"

    if not conv_dir.exists():
        raise FileNotFoundError(f"Antigravity 会话目录不存在: {conv_dir}")

    db_files = sorted(conv_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    all_workspaces: Dict[str, int] = {}
    matched_records: List[SessionRecord] = []

    for db_path in db_files:
        sid = db_path.stem
        mtime_ts = db_path.stat().st_mtime
        mtime_dt = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
        mtime_str = mtime_dt.strftime("%Y-%m-%d %H:%M:%S")

        ws = parse_workspace_from_db(db_path) or "(未关联工作区)"
        all_workspaces[ws] = all_workspaces.get(ws, 0) + 1

        title, last_view, is_archived, archived_at, _ = parse_annotation(annot_dir / f"{sid}.pbtxt")

        # 归档模式过滤
        if archived_mode == "archived_only" and not is_archived:
            continue
        elif archived_mode == "active_only" and is_archived:
            continue

        # 时间窗过滤
        if time_window:
            if not (time_window.start_utc <= mtime_dt <= time_window.end_utc):
                continue

        # 工作区过滤
        if workspace_kw:
            if workspace_kw.lower() not in ws.lower():
                continue

        cur_brain = brain_dir / sid
        first_prompt, created_at, transcript_path, full_text = parse_transcript_summary(cur_brain)
        final_title = title or first_prompt or "(无标题)"

        # 标题过滤
        if title_kw:
            if title_kw.lower() not in final_title.lower():
                continue

        # 关键词全文过滤
        if keyword_kw:
            if keyword_kw.lower() not in full_text.lower():
                continue

        has_plan = (cur_brain / "implementation_plan.md").exists()
        has_walkthrough = (cur_brain / "walkthrough.md").exists()

        record = SessionRecord(
            session_id=sid,
            title=final_title,
            workspace=ws,
            is_archived=is_archived,
            archived_at=archived_at,
            updated_at=mtime_str,
            updated_at_dt=mtime_dt,
            created_at=created_at or "(未知)",
            last_view_at=last_view or "(未知)",
            has_plan=has_plan,
            has_walkthrough=has_walkthrough,
            brain_path=str(cur_brain),
            transcript_path=transcript_path,
        )
        matched_records.append(record)
        if len(matched_records) >= limit:
            break

    sorted_workspaces = sorted(all_workspaces.items(), key=lambda x: x[1], reverse=True)[:20]
    return matched_records, sorted_workspaces


def render_table(records: List[SessionRecord]) -> str:
    if not records:
        return "(无匹配记录)"
    lines = []
    lines.append(f"{'#':<3} {'Session ID':<38} {'状态':<6} {'产物':<6} {'更新时间(UTC)':<19} {'标题 / 工作区'}")
    lines.append("-" * 130)
    for i, r in enumerate(records, 1):
        status = "[已归档]" if r.is_archived else "[活跃]"
        artifacts = []
        if r.has_plan:
            artifacts.append("Plan")
        if r.has_walkthrough:
            artifacts.append("Walk")
        art_str = "+".join(artifacts) if artifacts else "-"
        t = (r.title[:24] + "...") if len(r.title) > 24 else r.title
        ws = (r.workspace[:26] + "...") if len(r.workspace) > 26 else r.workspace
        lines.append(f"{i:<3} {r.session_id:<38} {status:<6} {art_str:<6} {r.updated_at:<19} {t} ({ws})")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="locate_session.py",
        description="按工作区、时间窗、归档状态及关键词定位 Antigravity 会话",
    )
    p.add_argument("--workspace", "-w", help="项目工作区路径或关键词（大小写不敏感模糊匹配）")
    p.add_argument("--time", "-t", help="自然语言时间提示，如 'yesterday', '上周', 'today', '2026-08-22'")
    p.add_argument("--after", help="时间窗起点 (ISO 格式)，如 2026-08-01")
    p.add_argument("--before", help="时间窗终点 (ISO 格式)，如 2026-08-31")
    p.add_argument("--title", help="按会话标题过滤（模糊匹配）")
    p.add_argument("--keyword", "-k", help="按对话全文关键词过滤")
    p.add_argument("--archived-only", action="store_true", help="仅检索已归档会话")
    p.add_argument("--active-only", action="store_true", help="仅检索活跃会话")
    p.add_argument("--antigravity-home", help="自定义 Antigravity 主目录路径")
    p.add_argument("--limit", "-n", type=int, default=DEFAULT_LIMIT, help=f"返回上限，默认 {DEFAULT_LIMIT}")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON 格式")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    window = None
    try:
        if args.time:
            window = parse_time_hint(args.time)
        elif args.after or args.before:
            now = datetime.now().astimezone()
            after = (
                datetime.fromisoformat(args.after).replace(tzinfo=now.tzinfo)
                if args.after
                else now - timedelta(days=MAX_WINDOW_DAYS)
            )
            before = (
                datetime.fromisoformat(args.before).replace(tzinfo=now.tzinfo)
                if args.before
                else now
            )
            window = TimeWindow(
                after.astimezone(timezone.utc),
                before.astimezone(timezone.utc),
                f"{args.after or ''} ~ {args.before or ''}",
            )
    except ValueError as e:
        print(f"错误: 时间解析失败: {e}", file=sys.stderr)
        return 2

    if window and window.width_days() > MAX_WINDOW_DAYS:
        print(
            f"错误: 时间窗跨度 {window.width_days():.1f} 天超过 {MAX_WINDOW_DAYS} 天上限，请缩窄窗口",
            file=sys.stderr,
        )
        return 2

    arch_mode = "all"
    if args.archived_only:
        arch_mode = "archived_only"
    elif args.active_only:
        arch_mode = "active_only"

    try:
        base_dir = resolve_antigravity_home(args.antigravity_home)
        matches, distinct_ws = locate_antigravity_sessions(
            base_dir=base_dir,
            workspace_kw=args.workspace,
            time_window=window,
            title_kw=args.title,
            keyword_kw=args.keyword,
            archived_mode=arch_mode,
            limit=args.limit,
        )
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    if args.json:
        result = {
            "antigravity_home": str(base_dir),
            "query": {
                "workspace_keyword": args.workspace,
                "time_window": {
                    "start_utc": window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if window else None,
                    "end_utc": window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if window else None,
                    "parsed_from": window.parsed_from if window else None,
                },
                "archived_mode": arch_mode,
                "title_keyword": args.title,
                "keyword": args.keyword,
            },
            "matches": [m.to_dict() for m in matches],
            "match_count": len(matches),
        }
        if not matches and distinct_ws:
            result["hint_distinct_workspaces"] = [{"workspace": w, "count": c} for w, c in distinct_ws]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ANTIGRAVITY_HOME: {base_dir}")
        if window:
            print(f"时间窗口(UTC):   {window.start_utc} ~ {window.end_utc} (来源: {window.parsed_from})")
        if args.workspace:
            print(f"工作区关键词:     {args.workspace}")
        print(f"归档过滤模式:     {arch_mode}")
        print()
        print(f"找到 {len(matches)} 个匹配会话:")
        print(render_table(matches))
        if not matches:
            print()
            print("本地数据库中已发现的工作区候选（前 20）:")
            for w, c in distinct_ws:
                print(f"  {c:>4} 次会话  {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
