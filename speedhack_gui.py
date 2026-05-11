#!/usr/bin/python3
"""
speedhack_gui.py — 游戏变速图形界面
依赖：Python 3 + tkinter（Linux 系统通常自带）
"""

import tkinter as tk
from tkinter import ttk, filedialog
import subprocess
import socket
import os
import glob
import shlex

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SO_PATH    = os.path.join(SCRIPT_DIR, "speedhack.so")

def _sock_dir() -> str:
    return os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("HOME") or "/tmp"

def _sock_path(pid: int) -> str:
    return os.path.join(_sock_dir(), f".speedhack_{pid}.sock")

def _all_scan_dirs() -> list[str]:
    """返回所有可能存放 socket 的目录（兼容 Snap + pressure-vessel 双重隔离）。"""
    uid = os.getuid()
    run_user = f"/run/user/{uid}"
    dirs = set([
        _sock_dir(),
        run_user,
        os.path.expanduser("~"),          # 宿主 HOME
    ])
    # /run/user/<uid>/ 的所有直接子目录（snap.steam 等）
    try:
        dirs.update(e.path for e in os.scandir(run_user) if e.is_dir())
    except OSError:
        pass
    return list(dirs)

def _find_sock(pid: int) -> str | None:
    """跨所有候选目录查找 socket。"""
    for d in _all_scan_dirs():
        p = os.path.join(d, f".speedhack_{pid}.sock")
        if os.path.exists(p):
            return p
    return None

# ── Catppuccin Mocha ─────────────────────────────────────────────
C = dict(
    bg      = "#1e1e2e",
    surface = "#313244",
    overlay = "#45475a",
    text    = "#cdd6f4",
    subtext = "#6c7086",
    blue    = "#89b4fa",
    green   = "#a6e3a1",
    red     = "#f38ba8",
    yellow  = "#f9e2af",
    mauve   = "#cba6f7",
    teal    = "#94e2d5",
)

PRESETS     = [("¼×", 0.25), ("½×", 0.5), ("1×", 1.0),
               ("2×", 2.0),  ("3×", 3.0), ("5×", 5.0), ("10×", 10.0)]
FONT_TITLE  = ("Sans Serif", 15, "bold")
FONT_BODY   = ("Sans Serif", 10)
FONT_SPEED  = ("Monospace", 20, "bold")
FONT_STATUS = ("Sans Serif", 9)
FONT_PRESET = ("Monospace", 10, "bold")


# ─────────────────────────────────────────────────────────────────
class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("SpeedHack")
        self.configure(bg=C["bg"])
        self.resizable(False, False)

        self._proc            = None   # subprocess.Popen（GUI 启动的进程）
        self._pid             = None   # 当前连接的 PID
        self._connected_sock  = None   # 实际 socket 路径（snap 子目录兼容）
        self._sock_ready      = False
        self._cur_speed       = 1.0
        self._slider_busy     = False  # 防止滑块 ↔ 显示循环触发
        self._combo_pid_map   = {}     # 下拉项文字 → (pid, sock_path)

        self._build()
        self._apply_combo_style()
        self._tick()                   # 启动 2s 轮询

    # ── ttk Combobox 深色样式 ─────────────────────────────────────
    def _apply_combo_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Dark.TCombobox",
                     fieldbackground=C["surface"],
                     background=C["overlay"],
                     foreground=C["text"],
                     arrowcolor=C["text"],
                     selectbackground=C["overlay"],
                     selectforeground=C["text"],
                     bordercolor=C["overlay"],
                     lightcolor=C["overlay"],
                     darkcolor=C["overlay"])
        st.map("Dark.TCombobox",
               fieldbackground=[("readonly", C["surface"])],
               foreground=[("readonly", C["text"])])
        self.option_add("*TCombobox*Listbox.background",  C["surface"])
        self.option_add("*TCombobox*Listbox.foreground",  C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["overlay"])
        self.option_add("*TCombobox*Listbox.selectForeground", C["text"])

    # ── 界面构建 ──────────────────────────────────────────────────
    def _build(self):
        # 标题
        tk.Label(self, text="⚡  SpeedHack",
                 font=FONT_TITLE, bg=C["bg"], fg=C["mauve"]
                 ).pack(pady=(18, 2))
        tk.Label(self, text="Linux 游戏变速器",
                 font=FONT_STATUS, bg=C["bg"], fg=C["subtext"]
                 ).pack(pady=(0, 12))
        self._sep()

        # ── 启动区 ────────────────────────────────────────────────
        sec = self._section("启动游戏")

        frm = tk.Frame(sec, bg=C["bg"])
        frm.pack(fill="x", pady=3)
        tk.Label(frm, text="命令", width=8, anchor="w",
                 bg=C["bg"], fg=C["subtext"], font=FONT_BODY).pack(side="left")
        self._cmd_var = tk.StringVar()
        e = tk.Entry(frm, textvariable=self._cmd_var,
                     bg=C["surface"], fg=C["text"],
                     insertbackground=C["text"],
                     relief="flat", font=FONT_BODY, width=34)
        e.pack(side="left", padx=(4, 4))
        e.bind("<Return>", lambda _: self._start_game())
        self._btn(frm, "浏览", self._browse, C["overlay"]).pack(side="left")

        frm2 = tk.Frame(sec, bg=C["bg"])
        frm2.pack(fill="x", pady=3)
        tk.Label(frm2, text="初始速度", width=8, anchor="w",
                 bg=C["bg"], fg=C["subtext"], font=FONT_BODY).pack(side="left")
        self._init_speed_var = tk.DoubleVar(value=1.0)
        tk.Spinbox(frm2, from_=0.01, to=100.0, increment=0.25, width=6,
                   textvariable=self._init_speed_var, format="%.2f",
                   bg=C["surface"], fg=C["text"],
                   buttonbackground=C["overlay"], relief="flat", font=FONT_BODY,
                   ).pack(side="left", padx=(4, 2))
        tk.Label(frm2, text="×", bg=C["bg"],
                 fg=C["subtext"], font=FONT_BODY).pack(side="left", padx=(0, 14))
        self._btn_start = self._btn(frm2, "▶  启动", self._start_game, C["green"], C["bg"])
        self._btn_start.pack(side="left", padx=4)
        self._btn_stop = self._btn(frm2, "■  停止", self._stop_game, C["red"], C["bg"])
        self._btn_stop.pack(side="left", padx=4)
        self._btn_stop.config(state="disabled")
        self._sep()

        # ── 检测到的进程 ──────────────────────────────────────────
        self._section("检测到的进程（自动扫描）")

        frm3 = tk.Frame(self, bg=C["bg"])
        frm3.pack(fill="x", padx=16, pady=(4, 4))

        self._proc_combo = ttk.Combobox(frm3, state="readonly",
                                        style="Dark.TCombobox", width=34)
        self._proc_combo.pack(side="left")
        self._proc_combo.set("扫描中…")

        self._btn(frm3, "连接", self._connect_selected, C["blue"], C["bg"]
                  ).pack(side="left", padx=(8, 4))

        # 连接状态指示点
        self._dot = tk.Label(frm3, text="●", font=("Monospace", 14),
                             bg=C["bg"], fg=C["subtext"])
        self._dot.pack(side="left", padx=(4, 0))
        self._dot_lbl = tk.Label(frm3, text="未连接",
                                 bg=C["bg"], fg=C["subtext"], font=FONT_STATUS)
        self._dot_lbl.pack(side="left", padx=(2, 0))
        self._sep()

        # ── 速度控制区 ────────────────────────────────────────────
        self._section("速度控制")

        frm_pre = tk.Frame(self, bg=C["bg"])
        frm_pre.pack(pady=(6, 4))
        for label, val in PRESETS:
            color = C["green"] if val == 1.0 else C["blue"]
            b = self._btn(frm_pre, label, lambda v=val: self._set_speed(v),
                          C["surface"], color)
            b.configure(width=4, font=FONT_PRESET)
            b.pack(side="left", padx=3)

        self._speed_lbl = tk.Label(self, text="1.00 ×",
                                   font=FONT_SPEED, bg=C["bg"], fg=C["green"])
        self._speed_lbl.pack(pady=(4, 2))

        # 睡眠缩短开关
        frm_opt = tk.Frame(self, bg=C["bg"])
        frm_opt.pack(pady=(0, 2))
        self._sleep_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frm_opt, text="缩短 sleep（旧游戏/固定帧率游戏需要，现代游戏开了会卡）",
                       variable=self._sleep_var, command=self._on_sleep_toggle,
                       bg=C["bg"], fg=C["subtext"], selectcolor=C["surface"],
                       activebackground=C["bg"], activeforeground=C["text"],
                       font=FONT_STATUS, cursor="hand2",
                       relief="flat", bd=0).pack()

        frm_sl = tk.Frame(self, bg=C["bg"])
        frm_sl.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(frm_sl, text="0.1×", bg=C["bg"],
                 fg=C["subtext"], font=FONT_STATUS, width=4).pack(side="left")
        self._slider = tk.Scale(frm_sl, from_=0.1, to=10.0, resolution=0.05,
                                orient="horizontal", length=330, showvalue=False,
                                command=self._on_slider_move,
                                bg=C["bg"], fg=C["text"],
                                troughcolor=C["surface"],
                                activebackground=C["blue"],
                                highlightthickness=0, bd=0, cursor="hand2")
        self._slider.set(1.0)
        self._slider.pack(side="left", padx=6)
        self._slider.bind("<ButtonRelease-1>", self._on_slider_release)
        tk.Label(frm_sl, text="10×", bg=C["bg"],
                 fg=C["subtext"], font=FONT_STATUS, width=3).pack(side="left")
        self._sep()

        # 状态栏
        self._status_var = tk.StringVar(value="就绪")
        self._status_lbl = tk.Label(self, textvariable=self._status_var,
                                    bg=C["bg"], fg=C["subtext"],
                                    font=FONT_STATUS, anchor="w")
        self._status_lbl.pack(fill="x", padx=16, pady=(4, 10))

    # ── 辅助 ─────────────────────────────────────────────────────

    def _sep(self):
        tk.Frame(self, bg=C["overlay"], height=1).pack(fill="x", padx=16, pady=6)

    def _section(self, title):
        tk.Label(self, text=title, font=("Sans Serif", 10, "bold"),
                 bg=C["bg"], fg=C["text"], anchor="w"
                 ).pack(fill="x", padx=16, pady=(4, 0))
        frm = tk.Frame(self, bg=C["bg"])
        frm.pack(fill="x", padx=16, pady=(2, 0))
        return frm

    def _btn(self, parent, text, cmd, bg, fg=None):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg, fg=fg or C["text"], relief="flat",
                         activebackground=C["overlay"],
                         activeforeground=C["text"],
                         font=FONT_BODY, cursor="hand2", padx=8, pady=3)

    # ── 扫描进程 ──────────────────────────────────────────────────

    def _scan_procs(self) -> list:
        """返回 [(pid, name, sock_path), ...] 所有存活的 speedhack socket。
        扫描 /run/user/<uid>/ 及所有直接子目录（兼容 Steam snap 隔离）。"""
        scan_dirs = set(_all_scan_dirs())

        seen_pids = set()
        found = []
        for d in sorted(scan_dirs):
            for sock in sorted(glob.glob(os.path.join(d, ".speedhack_*.sock"))):
                base = os.path.basename(sock)
                try:
                    pid = int(base[len(".speedhack_"):-len(".sock")])
                except ValueError:
                    continue
                if pid in seen_pids:
                    continue
                if not os.path.exists(f"/proc/{pid}"):
                    continue
                try:
                    name = open(f"/proc/{pid}/comm").read().strip()
                except OSError:
                    name = "?"
                seen_pids.add(pid)
                found.append((pid, name, sock))
        return found

    def _refresh_combo(self, procs: list):
        old_sel = self._proc_combo.get()
        self._combo_pid_map = {
            f"PID {pid}  —  {name}": (pid, sock)
            for pid, name, sock in procs
        }
        entries = list(self._combo_pid_map.keys())
        self._proc_combo["values"] = entries

        if not entries:
            self._proc_combo.set("未找到注入进程")
            return

        # 保持之前选中的项；否则选第一项
        if old_sel in entries:
            self._proc_combo.set(old_sel)
        else:
            self._proc_combo.current(0)

    # ── 连接动作 ──────────────────────────────────────────────────

    def _connect_selected(self):
        sel = self._proc_combo.get()
        val = self._combo_pid_map.get(sel)
        if val is None:
            self._status("请先在下拉框中选择进程", "warn")
            return
        pid, sock = val
        self._do_connect(pid, sock)

    def _do_connect(self, pid: int, sock: str | None = None):
        if sock is None:
            sock = _find_sock(pid)
        if not sock or not os.path.exists(sock):
            self._status("Socket 不存在，游戏须以 speedhack.so 启动", "err")
            return
        self._pid            = pid
        self._connected_sock = sock
        self._sock_ready     = True
        self._btn_stop.config(state="normal")
        self._update_dot(True)
        reply = self._send("?")
        if reply:
            # 格式: "speed=X.XXX sleep=N"
            for part in reply.split():
                if part.startswith("speed="):
                    try: self._set_speed_display(float(part[6:]))
                    except Exception: pass
                elif part.startswith("sleep="):
                    self._sleep_var.set(part[6:] == "1")
        self._status(f"已连接  PID={pid}", "ok")

    # ── 启动 / 停止 ───────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(title="选择游戏可执行文件")
        if path:
            self._cmd_var.set(path)

    def _start_game(self):
        raw = self._cmd_var.get().strip()
        if not raw:
            self._status("请输入命令或浏览选择可执行文件", "warn")
            return
        if not os.path.isfile(SO_PATH):
            self._status(f"找不到 {SO_PATH}，请先执行 make", "err")
            return
        try:
            cmd = shlex.split(raw)
        except ValueError as e:
            self._status(f"命令解析失败: {e}", "err")
            return

        init_speed = self._init_speed_var.get()
        env = os.environ.copy()
        prev = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"]       = f"{SO_PATH}:{prev}" if prev else SO_PATH
        env["SPEEDHACK_FACTOR"] = f"{init_speed:.3f}"

        try:
            self._proc = subprocess.Popen(cmd, env=env)
        except FileNotFoundError:
            self._status(f"找不到可执行文件：{cmd[0]}", "err")
            return
        except Exception as e:
            self._status(f"启动失败: {e}", "err")
            return

        self._pid        = self._proc.pid
        self._sock_ready = False
        self._set_speed_display(init_speed)
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._status(f"已启动  PID={self._pid}  等待连接…", "ok")

    def _stop_game(self):
        if self._proc:
            try: self._proc.terminate()
            except Exception: pass
        self._reset_state()
        self._status("已停止")

    # ── 速度控制 ──────────────────────────────────────────────────

    def _set_speed(self, speed: float):
        self._set_speed_display(speed)
        self._apply_speed(speed)

    def _on_sleep_toggle(self):
        val = 1 if self._sleep_var.get() else 0
        reply = self._send(f"sleep={val}")
        if reply and "OK" in reply:
            state = "已启用（旧游戏模式）" if val else "已关闭（默认）"
            self._status(f"缩短 sleep {state}", "ok")
        elif not self._sock_ready:
            pass  # 未连接时静默，连接后状态会同步

    def _on_slider_move(self, val):
        if not self._slider_busy:
            self._update_speed_label(round(float(val), 2))

    def _on_slider_release(self, _event):
        speed = round(self._slider.get(), 2)
        self._cur_speed = speed
        self._apply_speed(speed)

    def _apply_speed(self, speed: float):
        if not self._sock_ready or not self._pid:
            self._status("游戏未连接，请先启动或选择进程后点连接", "warn")
            return
        reply = self._send(f"{speed:.3f}")
        if reply and "OK" in reply:
            self._status(f"速度  {speed:.2f}×   PID={self._pid}", "ok")
        elif reply:
            self._status(reply, "warn")
        else:
            self._status("发送失败，游戏可能已退出", "err")
            self._update_dot(False)

    def _send(self, cmd: str):
        if not self._pid or not self._connected_sock:
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(self._connected_sock)
                s.sendall((cmd + "\n").encode())
                return s.recv(128).decode().strip()
        except Exception:
            return None

    # ── 显示 ─────────────────────────────────────────────────────

    def _set_speed_display(self, speed: float):
        self._cur_speed = speed
        self._update_speed_label(speed)
        self._slider_busy = True
        self._slider.set(min(max(speed, 0.1), 10.0))
        self._slider_busy = False

    def _update_speed_label(self, speed: float):
        self._speed_lbl.config(text=f"{speed:.2f} ×")
        if speed < 0.99:   self._speed_lbl.config(fg=C["teal"])
        elif speed < 1.01: self._speed_lbl.config(fg=C["green"])
        elif speed <= 3.0: self._speed_lbl.config(fg=C["yellow"])
        else:              self._speed_lbl.config(fg=C["red"])

    def _update_dot(self, connected: bool):
        if connected:
            self._dot.config(fg=C["green"])
            self._dot_lbl.config(text=f"已连接 PID={self._pid}", fg=C["green"])
        else:
            self._dot.config(fg=C["subtext"])
            self._dot_lbl.config(text="未连接", fg=C["subtext"])

    def _status(self, msg: str, level: str = "info"):
        colors = {"ok": C["green"], "warn": C["yellow"], "err": C["red"], "info": C["subtext"]}
        self._status_var.set(msg)
        self._status_lbl.config(fg=colors.get(level, C["subtext"]))

    def _reset_state(self):
        self._proc       = None
        self._pid        = None
        self._sock_ready = False
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._update_dot(False)

    # ── 轮询（每 2 秒）───────────────────────────────────────────

    def _tick(self):
        # 1. 检测 GUI 启动的进程是否退出
        if self._proc and self._proc.poll() is not None:
            self._reset_state()
            self._status("游戏已退出")

        # 2. 扫描所有存活 socket
        procs = self._scan_procs()
        self._refresh_combo(procs)

        # 3. 自动连接：GUI 启动了游戏，socket 刚出现
        if self._proc and not self._sock_ready and self._pid:
            pid_list = {p: sock for p, _, sock in procs}
            if self._pid in pid_list:
                self._do_connect(self._pid, pid_list[self._pid])

        # 4. 检测已连接进程是否还活着
        if self._sock_ready and self._pid:
            pid_list = [p for p, _, _ in procs]
            if self._pid not in pid_list:
                self._sock_ready = False
                self._update_dot(False)
                self._status("连接已断开（游戏退出？）", "warn")

        self.after(2000, self._tick)


# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not os.path.isfile(SO_PATH):
        print(f"[警告] 找不到 {SO_PATH}，请先在 speedhack/ 目录下执行 make")
    App().mainloop()
