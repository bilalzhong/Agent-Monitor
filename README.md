# Agent Monitor

A premium minimal desktop indicator that monitors **Claude Code** agent status in real time — locally or across SSH.

<br>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue" alt="Platform">
  <img src="https://img.shields.io/badge/python-3.9%2B-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
</p>

---

## Features

| | |
|---|---|
| 🟢🟡🔴 | **3-state traffic light** — Green (running), Yellow (awaiting approval), Red (idle) |
| 🔘 | **Stainless steel bezels** — premium anti-aliased rings around each indicator |
| 📊 | **Token tracking** — session tokens + all-time project totals |
| 🖥️ | **System tray** — close to tray, icon colour tracks state |
| 👆 | **Compact hover mode** — shows only 3 lights; hover to reveal full panel |
| 🌐 | **Remote SSH monitoring** — monitor Linux servers without installing anything |
| ⚡ | **Low latency** — multi-signal detection (session JSON + transcript stop_reason) |

## Quick Start

### Windows (standalone .exe)

```batch
# Build
pip install pyinstaller pillow pystray paramiko
pyinstaller --onefile --windowed --name "Agent-Monitor" --icon app.ico --add-data "monitor.py;." --add-data "remote.py;." --hidden-import PIL --hidden-import PIL.Image --hidden-import PIL.ImageTk --hidden-import PIL.ImageDraw --hidden-import pystray --hidden-import paramiko --collect-all paramiko main.py

# Install (Run as Administrator)
install.bat
```

### macOS / Linux

```bash
pip install pillow pystray paramiko
python main.py
```

## Remote Monitoring

Right-click → **Configure Remote…** → enter SSH credentials → toggle **Remote** on.

| Field | Description |
|-------|-------------|
| Host | Linux server IP / hostname |
| Port | SSH port (default 22) |
| Username | SSH user |
| Password | SSH password |

**No files are installed on the server.** The monitoring script is injected via SSH stdin.

Press **Test Connection** to verify before enabling.

## Right-Click Menu

| Option | Description |
|--------|-------------|
| Compact Mode | Show only 3 lights |
| Hover Expand | Auto-expand on mouse hover |
| Remote | Toggle SSH remote monitoring |
| Configure Remote… | Set up remote server |
| Always on Top | Keep window above others |
| Exit | Quit application |

## How It Works

```
Session JSON              Transcript JSONL
(~/.claude/sessions/)     (~/.claude/projects/)
       │                        │
       ▼                        ▼
  ┌────────────────────────────────────┐
  │       Multi-Signal Detection       │
  │  • session.status ("busy"/"idle")  │
  │  • stop_reason ("end_turn"/...)    │
  │  • permission-mode (auto-approve)  │
  │  • transcript staleness            │
  └────────────────────────────────────┘
                    │
                    ▼
         🟢 Green  │  🟡 Yellow  │  🔴 Red
```

The detection engine reads multiple signal sources to avoid false states:
- **RED** requires both `end_turn` and session `idle` (two signals must agree)
- **YELLOW** only when permission mode is NOT auto-approve
- **GREEN** is the default when Claude is actively working

## Project Structure

```
agent-monitor/
├── main.py         # Desktop UI (tkinter)
├── monitor.py      # Status detection engine
├── remote.py       # SSH remote transport
├── app.ico         # Application icon
├── install.bat     # Windows installer
├── update.bat      # Quick update script
├── .gitignore
└── README.md
```

## Requirements

- Python 3.9+
- `pillow` — anti-aliased graphics
- `pystray` — system tray (optional; Windows/macOS/Linux)
- `paramiko` — SSH remote monitoring (optional)

No environment dependencies at runtime on Windows (standalone .exe).

## License

MIT
