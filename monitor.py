"""
Agent Monitor — Status detection engine.
Cross-platform (macOS / Windows / Linux). Uses multiple signal sources
for low-latency state detection.
"""

import json
import os
import glob
import time
import platform
from datetime import datetime, timezone

# ── Cross-platform path resolution ─────────────────────────────────────────
HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")

# Minimal time thresholds (seconds)
TOOL_STALL = 0.8  # transcript not updated for this long → likely approval wait


def _find_session_file():
    """Find the current Claude session JSON file."""
    if not os.path.isdir(SESSIONS_DIR):
        return None
    files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    if not files:
        return None
    # Return the most recently modified (current session)
    return max(files, key=os.path.getmtime)


def _find_project_dir():
    """Find the most recently active project directory."""
    if not os.path.isdir(PROJECTS_DIR):
        return None
    dirs = [
        os.path.join(PROJECTS_DIR, d)
        for d in os.listdir(PROJECTS_DIR)
        if os.path.isdir(os.path.join(PROJECTS_DIR, d))
    ]
    if not dirs:
        return None
    return max(dirs, key=os.path.getmtime)


def _find_transcript(project_dir):
    """Find the most recent transcript in a project directory."""
    if not project_dir:
        return None
    files = glob.glob(os.path.join(project_dir, "*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _read_session(session_path):
    """Read session JSON, return (data, mtime_age_seconds).  Retries on failure."""
    if not session_path or not os.path.exists(session_path):
        return None, 999
    for attempt in range(3):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(session_path), tz=timezone.utc)
            age = (datetime.now(timezone.utc) - mtime).total_seconds()
            with open(session_path, "r", encoding="utf-8") as f:
                return json.load(f), age
        except Exception:
            if attempt < 2:
                time.sleep(0.05)  # brief pause before retry
    return None, 999


def _read_transcript(path, tail=200):
    """Read last N lines of a JSONL transcript. Returns (events, file_age)."""
    events = []
    file_age = 999
    if not path or not os.path.exists(path):
        return events, file_age
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        file_age = (datetime.now(timezone.utc) - mtime).total_seconds()
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-tail:]:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return events, file_age


def _has_pending_tool_use(events):
    """Check if the last assistant has tool_use without a matching tool_result."""
    pending = False
    last_tool_names = []

    for event in events:
        t = event.get("type", "")
        if t == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", [])
            tools = [
                b.get("name", "?")
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            if tools:
                pending = True
                last_tool_names = tools
        elif t == "user":
            msg = event.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        pending = False
                        last_tool_names = []

    return pending, last_tool_names


def _last_stop_reason(events):
    """Get stop_reason of the most recent assistant event."""
    for event in reversed(events):
        if event.get("type") == "assistant":
            return event.get("message", {}).get("stop_reason", "")
    return ""


def _is_auto_approve(events):
    """
    Check whether the current permission mode auto-approves ALL tool use.
    Even 'acceptEdits' still prompts yes/no for dangerous tools (bash, write…),
    so we treat it as NOT auto-approve.  Only truly bypassing modes (like
    'bypassPermissions') skip approval entirely.
    """
    for event in reversed(events):
        if event.get("type") == "permission-mode":
            mode = event.get("permissionMode", "")
            if mode == "bypassPermissions":
                return True
            # acceptEdits / default / anything else — approval may be needed
            return False
    return False  # no permission-mode event — assume approval may be needed


def detect_state(events, transcript_age, session_data, session_age):
    """
    Multi-signal state detection — robust against race conditions.

    🟢 Green  — Claude is actively executing
    🟡 Yellow — Claude needs user approval (yes/no)
    🔴 Red    — Idle (turn confirmed complete)

    Key design choices to avoid false RED / false YELLOW:
      • RED requires BOTH end_turn AND session not busy (two signals agree)
      • YELLOW only fires when NOT in acceptEdits mode (auto-approve → GREEN)
      • If session read fails, transcript stop_reason serves as fallback
    """
    session_busy = (session_data or {}).get("status") == "busy"
    pending, tool_names = _has_pending_tool_use(events)
    stop = _last_stop_reason(events)
    auto_approve = _is_auto_approve(events)

    # ── RED: both signals agree the turn is over ───────────────────────
    if stop == "end_turn" and not session_busy:
        return {"state": "red", "status_text": "Idle"}

    # ── RED: session explicitly idle, transcript agrees (no tool_use) ─
    if not session_busy and stop != "tool_use":
        return {"state": "red", "status_text": "Idle"}

    # ── YELLOW: tool pending + stalled transcript + NOT auto-approve ─
    # Two independent signals — either is sufficient:
    #   1. _has_pending_tool_use  — unresolved tool_use in transcript events
    #   2. stop == "tool_use"     — stop_reason is an even more reliable indicator
    stalled = transcript_age > TOOL_STALL
    if stalled and not auto_approve:
        if pending:
            hint = tool_names[0] if tool_names else "?"
            return {"state": "yellow", "status_text": f"Approval: {hint}"}
        if stop == "tool_use":
            return {"state": "yellow", "status_text": "Approval needed"}

    # ── GREEN: everything else (actively working) ──────────────────────
    return {"state": "green", "status_text": "Running…"}


def calculate_tokens(events):
    si = so = 0
    for e in events:
        if e.get("type") != "assistant":
            continue
        u = e.get("message", {}).get("usage", {})
        si += u.get("input_tokens", 0)
        so += u.get("output_tokens", 0)
    return {"session_input": si, "session_output": so, "session_total": si + so}


def calculate_all_time_tokens(project_dir):
    ti = to = ts = 0
    if not project_dir:
        return {"total_input": 0, "total_output": 0, "total_tokens": 0, "total_sessions": 0}
    for path in glob.glob(os.path.join(project_dir, "*.jsonl")):
        try:
            events, _ = _read_transcript(path, tail=5000)
            for e in events:
                if e.get("type") != "assistant":
                    continue
                u = e.get("message", {}).get("usage", {})
                ti += u.get("input_tokens", 0)
                to += u.get("output_tokens", 0)
            ts += 1
        except Exception:
            continue
    return {"total_input": ti, "total_output": to, "total_tokens": ti + to, "total_sessions": ts}


def format_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def get_full_status():
    session_path = _find_session_file()
    project_dir = _find_project_dir()
    transcript_path = _find_transcript(project_dir)

    session_data, session_age = _read_session(session_path)
    events, transcript_age = _read_transcript(transcript_path)

    state = detect_state(events, transcript_age, session_data, session_age)
    tokens = calculate_tokens(events)
    all_time = calculate_all_time_tokens(project_dir)

    sid = (session_data or {}).get("sessionId", "—")
    return {**state, **tokens, **all_time, "session_id": sid}


# ═══════════════════════════════════════════════════════════════════════════
#  CLI — supports remote execution via SSH
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--json" in sys.argv:
        # One-shot JSON output — used by remote SSH polling
        print(json.dumps(get_full_status(), ensure_ascii=False))
    elif "--stream" in sys.argv:
        # Continuous JSON lines — used by persistent SSH session
        interval = 3
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = float(arg.split("=")[1])
        while True:
            try:
                print(json.dumps(get_full_status(), ensure_ascii=False), flush=True)
            except Exception:
                print(json.dumps({"state": "red", "status_text": "Error"}, ensure_ascii=False), flush=True)
            time.sleep(interval)
    else:
        # Interactive / debug
        import pprint
        pprint.pprint(get_full_status())
