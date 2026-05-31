"""
Agent Monitor — Premium minimal desktop indicator.
Cross-platform: macOS / Windows / Linux.
Supports local + remote (SSH) monitoring.
"""

import tkinter as tk
from tkinter import font as tkfont, messagebox
import threading
import time
import os
import sys
import platform
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor import get_full_status, format_tokens
from remote import RemoteMonitor, load_config, save_config, create_from_config

# ── Platform ───────────────────────────────────────────────────────────────
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"
FONT_SANS = "SF Pro Display" if IS_MAC else "Segoe UI"
FONT_MONO = "SF Mono" if IS_MAC else "Cascadia Code"

# ── Design system ──────────────────────────────────────────────────────────
BG          = "#0d0d14"
TEXT        = "#e4e4ef"
TEXT_DIM    = "#6b6b80"
GREEN_ON    = "#00ff33"
GREEN_OFF   = "#002206"
YELLOW_ON   = "#ffee00"
YELLOW_OFF  = "#221800"
RED_ON      = "#ff0022"
RED_OFF     = "#220008"
ACCENT      = "#2a2a3a"

LIGHT_R     = 18
RING_W      = 6
GAP         = 1.5
PADDING     = 3.5
CELL_W      = int((LIGHT_R + GAP + RING_W + PADDING) * 2)  # 58
CELL_H      = CELL_W + 20

FULL_W    = 212
FULL_H    = 258          # +20 for remote indicator row
COMPACT_W = 196
COMPACT_H = 88

REMOTE_POLL = 3          # seconds — lighter on the server


# ═══════════════════════════════════════════════════════════════════════════
#  Image generation
# ═══════════════════════════════════════════════════════════════════════════

def _make_ringed(fill_hex, r=LIGHT_R, gap=GAP, rw=RING_W, pad=PADDING):
    from PIL import Image
    size = int((r + gap + rw + pad) * 2)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rr, gg, bb = int(fill_hex[1:3], 16), int(fill_hex[3:5], 16), int(fill_hex[5:7], 16)
    cx = cy = size // 2
    ri = r + gap
    ro = r + gap + rw
    for y in range(size):
        for x in range(size):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if ri - 0.5 <= dist <= ro + 0.5:
                if dist < ri:
                    a = int(255 * max(0, (dist - (ri - 1.2)) / 1.2))
                elif dist > ro:
                    a = int(255 * max(0, 1 - (dist - ro) / 1.2))
                else:
                    a = 255
                a = max(0, min(255, a))
                if a > 0:
                    angle = math.atan2(y - cy, x - cx)
                    base = 0.48 + 0.42 * (math.sin(angle + math.pi * 0.70) * 0.5 + 0.5)
                    base += 0.12 * max(0, math.cos(angle * 2 + 0.30))
                    base = min(1.0, max(0.0, base))
                    v = int(175 + 72 * base)
                    img.putpixel((x, y), (v, v, v, a))
                continue
            if r <= dist < ri:
                if dist < r + 0.5:
                    a = int(255 * max(0, (dist - r) / 0.5))
                elif dist < ri - 0.5:
                    a = 255
                else:
                    a = int(255 * max(0, 1 - (dist - (ri - 0.5)) / 0.5))
                a = max(0, min(255, a))
                if a > 0:
                    img.putpixel((x, y), (6, 6, 10, a))
                continue
            if dist < r:
                if dist < r - 1.5:
                    a = 255
                elif dist < r:
                    a = int(255 * max(0, 1 - (dist - (r - 1.5)) / 1.5))
                else:
                    a = 0
                if a > 0:
                    img.putpixel((x, y), (rr, gg, bb, a))
    return img


def _tray_dot(hex_color, sz=32):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 5
    d.ellipse([m, m, sz - m, sz - m], fill=hex_color, outline="#a0a0a0", width=1)
    return img


# ═══════════════════════════════════════════════════════════════════════════
#  Dot widget
# ═══════════════════════════════════════════════════════════════════════════

class Dot(tk.Canvas):
    def __init__(self, parent, on_color, off_color, label, **kw):
        super().__init__(
            parent, width=CELL_W, height=CELL_H,
            bg=BG, highlightthickness=0, **kw,
        )
        self._lit = False
        from PIL import ImageTk
        self._img_on  = ImageTk.PhotoImage(_make_ringed(on_color))
        self._img_off = ImageTk.PhotoImage(_make_ringed(off_color))
        cx = CELL_W // 2
        self._img_id = self.create_image(cx, CELL_W // 2, image=self._img_off)
        self.create_text(cx, CELL_W + 11, text=label, fill=TEXT_DIM,
                         font=(FONT_SANS, 9))
    def set_on(self, on: bool):
        if on == self._lit: return
        self._lit = on
        self.itemconfig(self._img_id, image=self._img_on if on else self._img_off)


# ═══════════════════════════════════════════════════════════════════════════
#  Remote-config dialog
# ═══════════════════════════════════════════════════════════════════════════

def _dialog_remote(parent):
    """Toplevel to configure remote SSH server.  Returns True if saved."""
    dlg = tk.Toplevel(parent)
    dlg.title("Configure Remote Server")
    dlg.resizable(False, False)
    dlg.configure(bg=BG)
    dlg.transient(parent)
    dlg.grab_set()

    cfg = load_config()
    remote = cfg.get("remote", {})

    fields = [
        ("Host:",     "host",     remote.get("host", "")),
        ("Port:",     "port",     str(remote.get("port", 22))),
        ("Username:", "username", remote.get("username", "root")),
        ("Password:", "password", remote.get("password", "")),
    ]
    entries = {}

    for idx, (label, key, default) in enumerate(fields):
        tk.Label(dlg, text=label, fg=TEXT_DIM, bg=BG,
                 font=(FONT_SANS, 9), anchor="e",
        ).grid(row=idx, column=0, sticky="e", padx=(14, 6), pady=(10 if idx == 0 else 4))
        show = "" if key == "password" else None
        e = tk.Entry(dlg, font=(FONT_SANS, 10),
                     fg=TEXT, bg="#1a1a2e", insertbackground=TEXT,
                     relief="flat", borderwidth=0,
                     highlightthickness=1, highlightbackground=ACCENT,
                     highlightcolor=TEXT_DIM,
                     show=show)
        e.insert(0, default)
        e.grid(row=idx, column=1, padx=(0, 14), pady=(10 if idx == 0 else 4),
               ipadx=6, ipady=4, sticky="ew")
        entries[key] = e

    result = {"saved": False}

    def do_save():
        try:
            port = int(entries["port"].get())
        except ValueError:
            port = 22
        cfg["remote"] = {
            "host":     entries["host"].get().strip(),
            "port":     port,
            "username": entries["username"].get().strip(),
            "password": entries["password"].get(),
        }
        save_config(cfg)
        result["saved"] = True
        dlg.destroy()

    def do_test():
        """Test SSH connection."""
        host = entries["host"].get().strip()
        try:
            port = int(entries["port"].get())
        except ValueError:
            port = 22
        username = entries["username"].get().strip()
        password = entries["password"].get()
        if not host:
            messagebox.showwarning("Test", "Enter a host first.", parent=dlg)
            return

        btn_test.config(text="Testing…", state="disabled")
        dlg.update()

        def _test():
            try:
                rm = RemoteMonitor(host, port, username, password)
                rm.connect()
                st = rm.get_full_status()
                rm.close()
                dlg.after(0, lambda: [
                    btn_test.config(text="Test Connection", state="normal"),
                    messagebox.showinfo("Test",
                        f"Connected!  State: {st.get('state','?')}\n"
                        f"Session: {st.get('session_total',0):,} tokens",
                        parent=dlg)
                ])
            except Exception as exc:
                dlg.after(0, lambda: [
                    btn_test.config(text="Test Connection", state="normal"),
                    messagebox.showerror("Test Failed", str(exc), parent=dlg)
                ])
        threading.Thread(target=_test, daemon=True).start()

    btn_frame = tk.Frame(dlg, bg=BG)
    btn_frame.grid(row=len(fields), column=0, columnspan=2,
                   pady=(14, 12), padx=14, sticky="ew")

    btn_test = tk.Button(btn_frame, text="Test Connection",
                         command=do_test,
                         font=(FONT_SANS, 9),
                         fg=TEXT_DIM, bg=SURFACE, relief="flat",
                         activeforeground=TEXT, activebackground=ACCENT,
                         cursor="hand2")
    btn_test.pack(side=tk.LEFT, padx=(0, 6))

    tk.Button(btn_frame, text="Cancel", command=dlg.destroy,
              font=(FONT_SANS, 9),
              fg=TEXT_DIM, bg=SURFACE, relief="flat",
              activeforeground=TEXT, activebackground=ACCENT,
              cursor="hand2",
    ).pack(side=tk.RIGHT, padx=(6, 0))

    tk.Button(btn_frame, text="Save", command=do_save,
              font=(FONT_SANS, 9, "bold"),
              fg="#00ff33", bg=SURFACE, relief="flat",
              activeforeground="#00ff33", activebackground=ACCENT,
              cursor="hand2",
    ).pack(side=tk.RIGHT)

    dlg.wait_window()
    return result["saved"]


# ═══════════════════════════════════════════════════════════════════════════
#  Application
# ═══════════════════════════════════════════════════════════════════════════

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Agent Monitor")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # Monitoring state
        self._tray         = None
        self._tray_ico     = {}
        self._current      = "red"
        self._compact      = True
        self._hover_expand = False
        self._hover_job    = None
        self._expanded     = False

        # Remote state
        self._remote       = None        # RemoteMonitor instance, or None for local
        self._remote_cfg   = load_config().get("remote", {})

        # tkinter variables
        self._var_compact      = tk.BooleanVar(value=True)
        self._var_hover_expand = tk.BooleanVar(value=False)
        self._var_topmost      = tk.BooleanVar(value=True)
        self._var_remote       = tk.BooleanVar(value=False)

        self._build()
        self._init_tray()
        self._init_menus()

        self._apply_compact(True)

        self._running = True
        threading.Thread(target=self._poll, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ──────────────────────────────────────────────────

    def _build(self):
        # Extra top — title bar
        self._extra_top = tk.Frame(self.root, bg=BG)
        tk.Label(self._extra_top, text="Agent Monitor", fg=TEXT, bg=BG,
                 font=(FONT_SANS, 11, "bold")).pack(side=tk.LEFT)
        self._pin = tk.Label(
            self._extra_top, text="📌",
            fg="#00f277" if self.root.attributes("-topmost") else TEXT_DIM,
            bg=BG, font=("Segoe UI", 10), cursor="hand2")
        self._pin.pack(side=tk.RIGHT)
        self._pin.bind("<Button-1>", self._toggle_pin)

        # Lights — always visible
        self._lights = tk.Frame(self.root, bg=BG)
        self._green  = Dot(self._lights, GREEN_ON,  GREEN_OFF,  "Running")
        self._yellow = Dot(self._lights, YELLOW_ON, YELLOW_OFF, "Waiting")
        self._red    = Dot(self._lights, RED_ON,    RED_OFF,    "Idle")
        self._green.pack(side=tk.LEFT, padx=2)
        self._yellow.pack(side=tk.LEFT, padx=2)
        self._red.pack(side=tk.LEFT, padx=2)

        # Extra bottom — status, tokens, remote indicator
        self._extra_bot = tk.Frame(self.root, bg=BG)

        # Remote indicator (only visible when remote is active)
        self._remote_row = tk.Frame(self._extra_bot, bg=BG)
        self._remote_dot = tk.Canvas(self._remote_row, width=8, height=8,
                                     bg=BG, highlightthickness=0)
        self._remote_dot_id = self._remote_dot.create_oval(
            0, 0, 8, 8, fill="#00ff33", outline="")
        self._remote_dot.pack(side=tk.LEFT, padx=(0, 4))
        self._remote_label = tk.Label(
            self._remote_row, text="", fg=TEXT_DIM, bg=BG,
            font=(FONT_SANS, 8))
        self._remote_label.pack(side=tk.LEFT)

        self._status = tk.Label(
            self._extra_bot, text="…", fg=TEXT_DIM, bg=BG,
            font=(FONT_SANS, 9))
        self._status.pack(pady=(0, 4))

        tk.Frame(self._extra_bot, bg=ACCENT, height=1).pack(fill=tk.X)

        tok = tk.Frame(self._extra_bot, bg=BG)
        tok.pack(fill=tk.X, pady=(6, 0))
        self._tok_session = self._col(tok, "Session", tk.LEFT)
        self._tok_total   = self._col(tok, "Total",   tk.RIGHT)

        self._sid = tk.Label(
            self._extra_bot, text="", fg=TEXT_DIM, bg=BG,
            font=(FONT_MONO, 7))
        self._sid.pack(pady=(2, 2))

        tk.Label(
            self._extra_bot, text="Close → Tray", fg=TEXT_DIM, bg=BG,
            font=(FONT_SANS, 7),
        ).pack()

    def _col(self, parent, label, side):
        f = tk.Frame(parent, bg=BG)
        f.pack(side=side)
        v = tk.Label(f, text="—", fg=TEXT, bg=BG,
                     font=(FONT_SANS, 13, "bold"))
        v.pack(anchor="center")
        tk.Label(f, text=label, fg=TEXT_DIM, bg=BG,
                 font=(FONT_SANS, 8)).pack(anchor="center")
        return v

    # ── Layout switching ────────────────────────────────────────────────

    def _apply_compact(self, compact):
        if compact:
            self._extra_top.pack_forget()
            self._extra_bot.pack_forget()
            self._lights.pack(pady=(8, 8))
            self.root.geometry(f"{COMPACT_W}x{COMPACT_H}")
        else:
            self._extra_top.pack(
                fill=tk.X, padx=12, pady=(10, 0), before=self._lights)
            self._lights.pack(pady=(12, 0))
            self._extra_bot.pack(
                fill=tk.X, padx=12, pady=(2, 4), after=self._lights)
            self.root.geometry(f"{FULL_W}x{FULL_H}")

    # ── Hover detection ─────────────────────────────────────────────────

    def _on_enter(self, e=None):
        if self._hover_job:
            self.root.after_cancel(self._hover_job)
            self._hover_job = None
        if self._compact and self._hover_expand and not self._expanded:
            self._expanded = True
            self._apply_compact(False)
            self._hover_poll()

    def _hover_poll(self):
        if not self._compact or not self._expanded:
            self._hover_job = None; return
        x = self.root.winfo_pointerx()
        y = self.root.winfo_pointery()
        wx = self.root.winfo_rootx()
        wy = self.root.winfo_rooty()
        ww = self.root.winfo_width()
        wh = self.root.winfo_height()
        if wx <= x <= wx + ww and wy <= y <= wy + wh:
            self._hover_job = self.root.after(250, self._hover_poll)
        else:
            self._expanded = False
            self._apply_compact(True)
            self._hover_job = None

    # ── Menus ──────────────────────────────────────────────────────────

    def _init_menus(self):
        self._ctx = tk.Menu(self.root, tearoff=0)
        self._ctx.add_checkbutton(
            label="Compact Mode", variable=self._var_compact,
            command=self._toggle_compact)
        self._ctx.add_checkbutton(
            label="Hover Expand", variable=self._var_hover_expand,
            command=self._toggle_hover_expand)
        self._ctx.add_separator()
        self._ctx.add_checkbutton(
            label="Remote", variable=self._var_remote,
            command=self._toggle_remote)
        self._ctx.add_command(
            label="Configure Remote…", command=self._configure_remote)
        self._ctx.add_separator()
        self._ctx.add_checkbutton(
            label="Always on Top", variable=self._var_topmost,
            command=self._toggle_pin)
        self._ctx.add_separator()
        self._ctx.add_command(label="Exit", command=self._quit)

        self.root.bind("<Button-3>", self._on_right_click)
        self._lights.bind("<Button-3>", self._on_right_click)

        self.root.bind("<Enter>", self._on_enter)
        self._lights.bind("<Enter>", self._on_enter)
        for dot in (self._green, self._yellow, self._red):
            dot.bind("<Enter>", self._on_enter)

    def _on_right_click(self, e):
        self._ctx.post(e.x_root, e.y_root)

    # ── System tray ─────────────────────────────────────────────────────

    def _init_tray(self):
        try:
            import pystray
            self._tray_ico = {
                "green":  _tray_dot(GREEN_ON),
                "yellow": _tray_dot(YELLOW_ON),
                "red":    _tray_dot(RED_ON),
            }
            menu = pystray.Menu(
                pystray.MenuItem("Show", self._show, default=True),
                pystray.MenuItem("Exit", self._quit),
            )
            self._tray = pystray.Icon(
                "agent-monitor", self._tray_ico["red"],
                "Agent Monitor", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception:
            self._tray = None

    def _update_tray(self, state):
        if self._tray and state in self._tray_ico:
            try:
                self._tray.icon = self._tray_ico[state]
            except Exception:
                pass

    def _show(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _on_close(self):
        if self._tray:
            self.root.withdraw()
        else:
            self._quit()

    def _quit(self, icon=None, item=None):
        if self._remote:
            self._remote.close()
            self._remote = None
        if self._tray:
            self._tray.stop()
        self._running = False
        self.root.destroy()

    # ── Interactions ────────────────────────────────────────────────────

    def _toggle_pin(self, e=None):
        cur = self.root.attributes("-topmost")
        self.root.attributes("-topmost", not cur)
        self._var_topmost.set(not cur)
        self._pin.config(fg="#00f277" if not cur else TEXT_DIM)

    def _toggle_compact(self):
        self._compact = self._var_compact.get()
        self._expanded = False
        if self._hover_job:
            self.root.after_cancel(self._hover_job)
            self._hover_job = None
        self._apply_compact(self._compact)

    def _toggle_hover_expand(self):
        self._hover_expand = self._var_hover_expand.get()
        if not self._hover_expand and self._expanded:
            self._expanded = False
            if self._hover_job:
                self.root.after_cancel(self._hover_job)
                self._hover_job = None
            self._apply_compact(True)

    # ── Remote ─────────────────────────────────────────────────────────

    def _toggle_remote(self):
        """Enable / disable remote monitoring."""
        if self._var_remote.get():
            if not self._remote_cfg.get("host"):
                # No config — open dialog
                if not _dialog_remote(self.root):
                    self._var_remote.set(False)
                    return
                self._remote_cfg = load_config().get("remote", {})

            # Connect
            try:
                self._remote = RemoteMonitor(
                    host=self._remote_cfg["host"],
                    port=self._remote_cfg.get("port", 22),
                    username=self._remote_cfg.get("username", "root"),
                    password=self._remote_cfg.get("password", ""),
                )
                self._remote.connect()
                self._remote_dot.itemconfig(
                    self._remote_dot_id, fill="#00ff33")  # green = connected
            except Exception as exc:
                messagebox.showerror("Connection Failed", str(exc))
                self._remote = None
                self._var_remote.set(False)
        else:
            if self._remote:
                self._remote.close()
                self._remote = None
            self._remote_dot.itemconfig(self._remote_dot_id, fill=TEXT_DIM)

        self._update_remote_indicator()

    def _configure_remote(self):
        """Open the remote-config dialog."""
        if _dialog_remote(self.root):
            self._remote_cfg = load_config().get("remote", {})
            # If remote was on, reconnect
            if self._var_remote.get():
                if self._remote:
                    self._remote.close()
                    self._remote = None
                self._toggle_remote()

    def _update_remote_indicator(self):
        """Show / hide the remote server row."""
        if self._remote and self._var_remote.get():
            host = self._remote_cfg.get("host", "?")
            self._remote_label.config(text=f"● {host}")
            self._remote_row.pack(before=self._status, pady=(4, 0))
        else:
            self._remote_row.pack_forget()

    # ── State loop ──────────────────────────────────────────────────────

    def _apply(self, s):
        state = s.get("state", "red")
        self._current = state
        self._green.set_on(state == "green")
        self._yellow.set_on(state == "yellow")
        self._red.set_on(state == "red")
        self._status.config(text=s.get("status_text", ""))
        self._tok_session.config(
            text=format_tokens(s.get("session_total", 0)))
        self._tok_total.config(
            text=format_tokens(s.get("total_tokens", 0)))
        sid = s.get("session_id", "—")
        self._sid.config(text=f"session {sid[:8]}…")
        self._update_tray(state)

    def _poll(self):
        interval = 1
        while self._running:
            try:
                if self._remote and self._var_remote.get():
                    s = self._remote.get_full_status()
                    interval = REMOTE_POLL
                else:
                    s = get_full_status()
                    interval = 1

                self.root.after(0, self._apply, s)
                # Update remote indicator state
                if self._remote:
                    self.root.after(0, self._update_remote_indicator)
            except Exception:
                pass
            time.sleep(interval)

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
