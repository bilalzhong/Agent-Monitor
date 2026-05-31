"""
Remote Agent Monitor — SSH transport.
Connects to a Linux server via paramiko, runs monitor.py remotely,
and returns the same status dict as the local monitor.
"""

import json
import os
import sys
import threading
import time

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".agent-monitor.json")


def load_config():
    """Load remote server config from ~/.agent-monitor.json."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    """Save remote server config."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── Embedded monitor.py (inlined to avoid SFTP upload) ──────────────────────
# The remote agent script is self-contained — no file transfer needed.

_REMOTE_SCRIPT = r'''
import json, os, glob, time, platform
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")
TOOL_STALL = 1.5

def _find_session_file():
    if not os.path.isdir(SESSIONS_DIR): return None
    files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    if not files: return None
    return max(files, key=os.path.getmtime)

def _find_project_dir():
    if not os.path.isdir(PROJECTS_DIR): return None
    dirs = [os.path.join(PROJECTS_DIR, d) for d in os.listdir(PROJECTS_DIR) if os.path.isdir(os.path.join(PROJECTS_DIR, d))]
    if not dirs: return None
    return max(dirs, key=os.path.getmtime)

def _find_transcript(project_dir):
    if not project_dir: return None
    files = glob.glob(os.path.join(project_dir, "*.jsonl"))
    if not files: return None
    return max(files, key=os.path.getmtime)

def _read_session(session_path):
    if not session_path or not os.path.exists(session_path): return None, 999
    for attempt in range(3):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(session_path), tz=timezone.utc)
            age = (datetime.now(timezone.utc) - mtime).total_seconds()
            with open(session_path, "r", encoding="utf-8") as f:
                return json.load(f), age
        except:
            if attempt < 2: time.sleep(0.05)
    return None, 999

def _read_transcript(path, tail=200):
    events = []
    file_age = 999
    if not path or not os.path.exists(path): return events, file_age
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        file_age = (datetime.now(timezone.utc) - mtime).total_seconds()
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-tail:]:
            line = line.strip()
            if not line: continue
            try: events.append(json.loads(line))
            except: pass
    except: pass
    return events, file_age

def _has_pending_tool_use(events):
    pending = False
    last_tool_names = []
    for event in events:
        t = event.get("type", "")
        if t == "assistant":
            content = event.get("message", {}).get("content", [])
            tools = [b.get("name", "?") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if tools:
                pending = True
                last_tool_names = tools
        elif t == "user":
            content = event.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        pending = False
                        last_tool_names = []
    return pending, last_tool_names

def _last_stop_reason(events):
    for event in reversed(events):
        if event.get("type") == "assistant":
            return event.get("message", {}).get("stop_reason", "")
    return ""

def _is_auto_approve(events):
    for event in reversed(events):
        if event.get("type") == "permission-mode":
            return event.get("permissionMode") == "acceptEdits"
    return False

def detect_state(events, transcript_age, session_data, session_age):
    session_busy = (session_data or {}).get("status") == "busy"
    pending, tool_names = _has_pending_tool_use(events)
    stop = _last_stop_reason(events)
    auto_approve = _is_auto_approve(events)
    if stop == "end_turn" and not session_busy:
        return {"state": "red", "status_text": "Idle"}
    if not session_busy and stop != "tool_use":
        return {"state": "red", "status_text": "Idle"}
    if session_busy and pending and transcript_age > TOOL_STALL and not auto_approve:
        hint = tool_names[0] if tool_names else "?"
        return {"state": "yellow", "status_text": "Approval: " + hint}
    return {"state": "green", "status_text": "Running..."}

def calculate_tokens(events):
    si = so = 0
    for e in events:
        if e.get("type") != "assistant": continue
        u = e.get("message", {}).get("usage", {})
        si += u.get("input_tokens", 0)
        so += u.get("output_tokens", 0)
    return {"session_input": si, "session_output": so, "session_total": si + so}

def calculate_all_time_tokens(project_dir):
    ti = to = ts = 0
    if not project_dir: return {"total_input": 0, "total_output": 0, "total_tokens": 0, "total_sessions": 0}
    for path in glob.glob(os.path.join(project_dir, "*.jsonl")):
        try:
            events, _ = _read_transcript(path, tail=5000)
            for e in events:
                if e.get("type") != "assistant": continue
                u = e.get("message", {}).get("usage", {})
                ti += u.get("input_tokens", 0)
                to += u.get("output_tokens", 0)
            ts += 1
        except: continue
    return {"total_input": ti, "total_output": to, "total_tokens": ti + to, "total_sessions": ts}

def get_full_status():
    session_path = _find_session_file()
    project_dir = _find_project_dir()
    transcript_path = _find_transcript(project_dir)
    session_data, session_age = _read_session(session_path)
    events, transcript_age = _read_transcript(transcript_path)
    state = detect_state(events, transcript_age, session_data, session_age)
    tokens = calculate_tokens(events)
    all_time = calculate_all_time_tokens(project_dir)
    sid = (session_data or {}).get("sessionId", "-")
    r = {**state, **tokens, **all_time, "session_id": sid}
    return r

print(json.dumps(get_full_status(), ensure_ascii=False))
'''


class RemoteMonitor:
    """SSH-based remote Claude state monitor."""

    def __init__(self, host, port=22, username="root", password=None):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client = None
        self._lock = threading.Lock()

    @property
    def host(self):
        return self._host

    def connect(self):
        """Establish SSH connection.  Raises on failure."""
        import paramiko

        if self._client:
            return

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
        # Keep connection alive
        transport = client.get_transport()
        transport.set_keepalive(15)
        self._client = client

    def get_full_status(self):
        """Run the monitor script remotely and return parsed status dict."""
        with self._lock:
            try:
                if not self._client or not self._client.get_transport() or not self._client.get_transport().is_active():
                    self._client = None
                    self.connect()

                # Execute the self-contained script via stdin
                stdin, stdout, stderr = self._client.exec_command(
                    "python3", timeout=10
                )
                stdin.write(_REMOTE_SCRIPT)
                stdin.channel.shutdown_write()

                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()

                if err:
                    # If remote has no python3, try python
                    if "python3" in err.lower() or "not found" in err.lower():
                        stdin2, stdout2, stderr2 = self._client.exec_command(
                            "python", timeout=10
                        )
                        stdin2.write(_REMOTE_SCRIPT)
                        stdin2.channel.shutdown_write()
                        out = stdout2.read().decode("utf-8", errors="replace").strip()
                        err2 = stderr2.read().decode("utf-8", errors="replace").strip()
                        if err2:
                            return {"state": "red", "status_text": f"SSH error: {err2[:60]}"}

                if not out:
                    return {"state": "red", "status_text": "No response"}

                return json.loads(out)

            except Exception as exc:
                self._client = None
                msg = str(exc)[:60]
                return {"state": "red", "status_text": f"Disconnected: {msg}"}

    def close(self):
        """Close SSH connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def create_from_config():
    """Create a RemoteMonitor from saved config, or None if not configured."""
    cfg = load_config()
    remote = cfg.get("remote", {})
    host = remote.get("host", "").strip()
    if not host:
        return None
    return RemoteMonitor(
        host=host,
        port=remote.get("port", 22),
        username=remote.get("username", "root"),
        password=remote.get("password", ""),
    )
