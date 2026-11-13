# -*- coding: utf-8 -*-
"""排查脚本：监控固定在底层的日历窗口 Z 序，分别启动其他 Python 程序观察是否被顶起。"""
import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
import calendar_app as ca

ca.DB_PATH = tmp / "calendar.db"
ca.SETTINGS_PATH = tmp / "settings.json"

app = ca.CalendarApp()
log = []
bad = []


def below_class(hwnd):
    """返回主窗口紧邻下层窗口的类名（Progman/WorkerW = 仍在壁纸层，其余 = 被顶起）"""
    buf = ctypes.create_unicode_buffer(64)
    below = ca._user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
    if below:
        ca._user32.GetClassNameW(below, buf, 64)
        return buf.value
    return "(none)"


def sample():
    hwnd = ca._toplevel_hwnd(app)
    cls = below_class(hwnd)
    log.append(cls)
    if cls not in ("Progman", "WorkerW"):
        bad.append(cls)
        print("  !! 被顶起，下方窗口类 =", cls)
    app.after(500, sample)


def spawn_console(_e=None):
    print(">> 启动控制台 Python 程序")
    subprocess.Popen([sys.executable, "-c",
                      "print('hello'); import time; time.sleep(4)"],
                     creationflags=subprocess.CREATE_NEW_CONSOLE)


def spawn_tk(_e=None):
    print(">> 启动 Tkinter GUI Python 程序")
    subprocess.Popen([sys.executable, "-c",
                      "import tkinter as tk; r = tk.Tk(); r.title('other-py'); "
                      "r.geometry('300x200+200+200'); r.after(4000, r.destroy); "
                      "r.mainloop()"])


def finish():
    tail = log[-4:]  # 结尾 2 秒（4 次采样）全部贴底才算修复
    good_tail = all(c in ("Progman", "WorkerW") for c in tail)
    print(">> 结束。采样", len(log), "次，异常", len(bad), "次（含保活周期内的瞬时波动）")
    print("RESULT:", "STAYED_BOTTOM" if good_tail else "FLOATING_STUCK")
    app.on_close()


app.after(3000, sample)
app.after(5000, spawn_console)
app.after(11000, spawn_tk)
app.after(17000, spawn_console)
app.after(24000, finish)
app.mainloop()
