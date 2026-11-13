#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面日历清单（Windows）

月历视图 + 每日任务面板 + 全部清单三合一，用于个人任务跟进。
数据保存在同目录 data/calendar.db（SQLite），可随文件夹整体备份/迁移。

用法：
  python calendar_app.py            # 调试运行（带控制台报错）
  pythonw calendar_app.py           # 正常运行（无控制台窗口）
  run.bat                           # 双击启动
"""

import calendar
import csv
import json
import os
import queue
import re
import shutil
import sqlite3
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import ttk, font as tkfont, messagebox, filedialog, colorchooser

try:
    import winreg
except ImportError:  # 非 Windows 环境兜底
    winreg = None

# ---------------------------------------------------------------------------
# Win32 窗口控制：任务栏按钮显隐 / 贴桌面底层 / 主屏工作区
# ---------------------------------------------------------------------------
try:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _shell32 = ctypes.windll.shell32   # 托盘 API（Shell_NotifyIconW / ExtractIconW）
except (ImportError, AttributeError, OSError):  # 非 Windows 环境兜底
    ctypes = None
    wintypes = None
    _user32 = None
    _kernel32 = None
    _shell32 = None

# 窗口扩展样式索引：GetWindowLongW/SetWindowLongW 用 GWL_EXSTYLE 读写扩展样式
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080   # 不进任务栏与 Alt-Tab
_WS_EX_APPWINDOW = 0x00040000    # 强制显示任务栏按钮
_WS_EX_TOPMOST = 0x00000008      # 置顶样式位；贴桌面底层前必须清掉，否则压不下去
_WS_EX_NOACTIVATE = 0x08000000   # 永不参与激活/前台切换：禁止系统把本窗口抬到最上层
_WS_EX_LAYERED = 0x00080000      # 分层窗口（Tk 设了 -alpha<1 就会带上）；会破坏中文输入法
# SetWindowPos 的 hWndInsertAfter 特殊取值
_HWND_BOTTOM = 1                 # 绝对底层
_HWND_NOTOPMOST = -2             # 仅用于「取消置顶」，会顺带把窗口抬到非置顶层最前，慎用
# SetWindowPos 的 flags：不动尺寸 / 不动位置 / 不改 Z 序 / 不激活 / 重绘边框
_SWP_NOSIZE, _SWP_NOMOVE = 0x0001, 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE, _SWP_FRAMECHANGED = 0x0010, 0x0020
_SPI_GETWORKAREA = 0x0030        # SystemParametersInfo：取主屏工作区（不含任务栏）

if _user32 is not None:
    # 逐一声明 Win32 API 的返回值/参数类型。不声明的话 ctypes 默认按 int 处理，
    # 在 64 位系统上 HWND（指针）会被截断成 32 位，导致句柄错误、调用静默失败
    _user32.GetParent.restype = wintypes.HWND          # 返回值：父窗口句柄
    _user32.GetParent.argtypes = [wintypes.HWND]       # 参数：子窗口句柄
    _user32.FindWindowW.restype = wintypes.HWND        # 按类名+标题找顶层窗口
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND      # 在父窗口下找子窗口
    _user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                      wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.GetWindow.restype = wintypes.HWND          # 取 Z 序上的相邻窗口
    _user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    _user32.SetWindowPos.restype = wintypes.BOOL       # 移动/改 Z 序的核心 API
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                     ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.GetWindowLongW.restype = ctypes.c_long     # 读窗口样式位
    _user32.SetWindowLongW.restype = ctypes.c_long     # 写窗口样式位
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SendMessageTimeoutW.restype = wintypes.LPARAM   # 发消息并可限时等待
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    _user32.SystemParametersInfoW.restype = wintypes.BOOL   # 查系统参数（工作区等）
    _user32.SystemParametersInfoW.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    _user32.GetClassNameW.restype = ctypes.c_int       # 取窗口类名，用于判断桌面层
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.SetForegroundWindow.restype = wintypes.BOOL  # 把窗口切到前台（激活）
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.GetForegroundWindow.restype = wintypes.HWND  # 取当前前台窗口
    _user32.GetForegroundWindow.argtypes = []
    _user32.keybd_event.restype = None                  # 合成一次按键（ALT 技巧用）
    _user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE,
                                    wintypes.DWORD, ctypes.c_size_t]
    _user32.AttachThreadInput.restype = wintypes.BOOL   # 线程挂接强抢前台的兜底
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                          wintypes.BOOL]
    _user32.SetFocus.restype = wintypes.HWND            # 直接设置键盘焦点窗口
    _user32.SetFocus.argtypes = [wintypes.HWND]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD  # 本 GUI 线程 id


def _toplevel_hwnd(widget):
    """Tk 顶层窗口的真实 HWND（winfo_id 拿到的是内层子窗口，需向上一层）"""
    # widget.winfo_id() 只是 Tk 内部子窗口的句柄，向上一层才是我们能操作的顶层窗口；
    # 非 Windows（_user32 为 None）时返回 0，调用方据此跳过所有原生操作
    return _user32.GetParent(widget.winfo_id()) if _user32 else 0


def _set_taskbar_button(widget, show: bool):
    """控制窗口是否出现在任务栏/Alt-Tab：show=False 隐藏（固定），True 恢复（移动）"""
    hwnd = _toplevel_hwnd(widget)          # 取顶层窗口句柄
    if not hwnd:                            # 拿不到句柄（非 Windows）直接放弃
        return
    ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)   # 读出当前扩展样式位
    if show:
        # 恢复任务栏按钮：加 APPWINDOW、去掉 TOOLWINDOW
        ex = (ex | _WS_EX_APPWINDOW) & ~_WS_EX_TOOLWINDOW
    else:
        # 隐藏任务栏按钮：去掉 APPWINDOW、加 TOOLWINDOW（工具窗口不进任务栏/Alt-Tab）
        ex = (ex & ~_WS_EX_APPWINDOW) | _WS_EX_TOOLWINDOW
    _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)    # 写回新样式
    # 样式改完必须通知系统重绘边框才会生效；NOSIZE/NOMOVE/NOZORDER 保证只刷样式、不动窗口
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER
                         | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)


def _window_class(hwnd):
    """返回窗口句柄的类名；取不到返回空串"""
    if not (_user32 and hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(64)  # 类名缓冲区
    _user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def _below_class(hwnd):
    """返回 hwnd 紧邻下层窗口的类名。结果是 Progman/WorkerW 说明窗口仍贴在
    桌面层（壁纸之上、一切之下）；是别的窗口就说明被顶起来了。"""
    if not _user32:
        return ""
    return _window_class(_user32.GetWindow(hwnd, 2))  # GW_HWNDNEXT=2：下一层


def _find_desktop_layers():
    """枚举所有顶层窗口探测桌面层级结构，返回 (图标层宿主, 其下方的壁纸 WorkerW)。
    图标层宿主 = 含有 SHELLDLL_DefView（桌面图标）子窗口的那个顶层窗口；
    系统未分离壁纸层时第二个返回 0。"""
    if not _user32:
        return 0, 0
    found = [0, 0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # 枚举回调
    def _cb(item, _lp):
        if _user32.FindWindowExW(item, None, "SHELLDLL_DefView", None):
            found[0] = item                                       # 图标层宿主
            found[1] = _user32.FindWindowExW(None, item, "WorkerW", None) or 0
            return False                                          # 找到即停止枚举
        return True

    _user32.EnumWindows(_cb, 0)
    return found[0], found[1]


def _pin_above_wallpaper(hwnd, ask_split=False):
    """把窗口钉到「壁纸之上、图标和一切应用之下」，返回是否到位。

    历史教训（浮到最上层的根因）：旧实现把探测到的某个参照窗口缓存为「锚点」，
    之后周期性执行“插到锚点下面”——锚点窗口被系统抬升（如启动其他程序）时，
    日历会跟着被抬到最上层。因此本函数不缓存任何窗口句柄，每次都实时枚举
    桌面结构，且只移动自己、从不移动外壳窗口（Progman 不可被第三方移动）：

    - 壁纸在独立 WorkerW 上（0x052C 分离后）：插到图标层宿主正下方，
      其下正是壁纸 WorkerW —— 图标之下、壁纸之上；
    - 壁纸直接画在图标层宿主（Progman）上：插到宿主「正上邻窗口」的下方，
      即紧贴宿主上方 —— 壁纸之上；
    - 探测不到外壳（资源管理器未运行等）：HWND_BOTTOM 兜底。
    ask_split=True 时先向 Progman 发 0x052C 请系统分离壁纸层（幂等，
    每次固定会话只尝试一次）。

    本次修复补了两处硬伤：
    1) 参照窗口可能取到本窗口自身（日历正好贴在图标层上方时，
       GetWindow(icons, GW_HWNDPREV) 返回的正是日历），此时 SetWindowPos(自身, 自身)
       是无效操作、位置得不到纠正 —— 现在先排除自身并做有效性校验；
    2) 定位后立刻校验，不到位就用 HWND_BOTTOM 兜底再压一次，
       避免“压不下去却没人管”导致日历一直停在被顶起的位置。"""
    if not (_user32 and hwnd):
        return True
    progman = _user32.FindWindowW("Progman", None) or 0
    if ask_split and progman:  # 请求分离壁纸层（部分系统由此产生 WorkerW 结构）
        _user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0x0002, 500, None)
    icons, wallpaper = _find_desktop_layers()
    if icons and wallpaper:
        target = icons                                   # 图标层宿主之下（壁纸 WorkerW 之上）
    elif icons:
        # GW_HWNDPREV=3：图标层宿主正上方的那个窗口；把它作为插入参照，
        # 日历就会被塞到它下面、紧贴图标层上方（即壁纸之上）
        prev = _user32.GetWindow(icons, 3)
        # 参照窗口无效、或是本窗口自己时，直接退到绝对底层，避免无效移动
        target = prev if (prev and prev != hwnd) else _HWND_BOTTOM
    else:
        target = _HWND_BOTTOM                            # 兜底：绝对底层
    _user32.SetWindowPos(hwnd, target, 0, 0, 0, 0,
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE)
    # 到位校验：紧邻下层必须是桌面层（Progman 或壁纸 WorkerW）
    if _below_class(hwnd) in ("Progman", "WorkerW"):
        return True
    # 结构探测/插入失效：退到绝对底层再压一次，并重新校验
    _user32.SetWindowPos(hwnd, _HWND_BOTTOM, 0, 0, 0, 0,
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE)
    return _below_class(hwnd) in ("Progman", "WorkerW")


def _clear_topmost_style(hwnd):
    """清掉 WS_EX_TOPMOST（置顶样式位），且绝不做任何 Z 序抬升。

    关键：不能用 Tk 的 attributes("-topmost", False)。它等价于
    SetWindowPos(hwnd, HWND_NOTOPMOST)，而 HWND_NOTOPMOST 的语义是
    「放到所有非置顶窗口的最前面」—— 也就是关闭置顶这个动作本身会把窗口
    顶到最上层。这正是启动其他程序、触发层级重算时日历突然浮出的元凶之一。
    这里改为只摘样式位（SetWindowLong + SWP_NOZORDER），位置交给
    _pin_above_wallpaper 单独处理。"""
    if not (_user32 and hwnd):
        return
    ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if not (ex & _WS_EX_TOPMOST):
        return  # 本来就没置顶，无需处理
    _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_TOPMOST)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,          # 仅刷新样式，不动 Z 序
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER
                         | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)


def _set_no_activate(hwnd, on: bool):
    """加/去 WS_EX_NOACTIVATE：窗口永不参与激活与前台切换。

    桌面挂件的标准做法。加上之后 Windows 的前台切换逻辑不会再把这个窗口
    卷进来（例如新程序启动抢前台时，系统可能顺带抬升某些窗口），
    从源头减少被顶到最上层的机会；副作用是窗口无法被点击激活、收不到
    键盘输入——打字期间由 _on_focus_in 临时摘掉本样式并抢前台（见
    「输入保护」一节），输完在 _ime_guard_restore 里还原。"""
    if not (_user32 and hwnd):
        return
    ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    ex = (ex | _WS_EX_NOACTIVATE) if on else (ex & ~_WS_EX_NOACTIVATE)
    _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,          # 让样式生效，不动 Z 序
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER
                         | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)


def _set_layered(hwnd, on: bool):
    """加/去 WS_EX_LAYERED（分层窗口样式位）。

    为什么必须自己动手：Tk 只要调用过 attributes("-alpha", x) 且 x < 1，
    就会给窗口加上 WS_EX_LAYERED；而设回 1.0 时 Tk **只把不透明度改成 255，
    并不会摘掉这个样式位**（已实测确认）。残留的分层样式会让中文输入法失效——
    表现为点进输入框后打不出中文（英文正常），要来回切几次输入法才好。
    所以打字期间必须真正摘掉它，让窗口回到普通窗口状态。"""
    if not (_user32 and hwnd):
        return
    ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    ex = (ex | _WS_EX_LAYERED) if on else (ex & ~_WS_EX_LAYERED)
    _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,          # 让样式生效，不动 Z 序
                         _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER
                         | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)


def _force_foreground(hwnd, child_hwnd: int = 0) -> bool:
    """把 hwnd 切到前台（激活它）。child_hwnd 是当前输入框的 Win32 句柄。

    贴桌面模式常驻 WS_EX_NOACTIVATE，点击不会激活窗口，系统把键盘输入
    全部发给当前前台应用——点进输入框也打不出任何字。所以打字前必须
    显式抢一次前台（配合先摘掉 NOACTIVATE，见 CalendarApp._on_focus_in）。

    SetForegroundWindow 受前台锁定限制：只有「最近收到输入的进程」才能
    成功。本函数只在用户刚点击了本窗口的输入框之后调用，通常直接成功；
    万一被系统拒绝，按强度依次降级重试：
    ① 合成一次 ALT 按下/抬起——系统据此认为本进程正在接收输入，放开锁定；
    ② 把本 GUI 线程挂到前台窗口所属线程的输入队列上，强设前台与焦点后
       立刻解除挂接（经典桌面挂件做法）。

    ② 里的 SetFocus 必须落在【输入框本身】（child_hwnd）——历史上写成顶层
    窗口句柄，把 Win32 键盘焦点从输入框抢到顶层：光标看着在框里（Tk 层
    焦点没丢）但任何按键都进不来，还会触发一次假 FocusOut 把打字模式
    60ms 后关掉——「点进输入框打不出字、切一次固定/移动才恢复」的元凶。
    返回 True 表示前台已确认是本窗口。"""
    if not (_user32 and hwnd):
        return True
    if _user32.SetForegroundWindow(hwnd) and \
            _user32.GetForegroundWindow() == hwnd:
        return True
    _user32.keybd_event(0x12, 0, 0, 0)    # VK_MENU(0x12) 按下
    _user32.keybd_event(0x12, 0, 2, 0)    # 抬起；KEYEVENTF_KEYUP = 2
    if _user32.SetForegroundWindow(hwnd) and \
            _user32.GetForegroundWindow() == hwnd:
        return True
    this_tid = _kernel32.GetCurrentThreadId()
    fg = _user32.GetForegroundWindow()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    if fg_tid and fg_tid != this_tid:
        _user32.AttachThreadInput(this_tid, fg_tid, True)
        _user32.SetForegroundWindow(hwnd)
        _user32.SetFocus(child_hwnd or hwnd)   # 焦点必须落回输入框本身
        _user32.AttachThreadInput(this_tid, fg_tid, False)
    return _user32.GetForegroundWindow() == hwnd


def _primary_work_area():
    """主屏工作区 (右边界, 下边界)，不含任务栏；取不到时返回 None"""
    if _user32 is None:
        return None
    rc = wintypes.RECT()
    if _user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rc), 0):
        return rc.right, rc.bottom
    return None


# ---------------------------------------------------------------------------
# 屏幕外窗口救援 + 单实例保护（v1.7.1）
# 背景：settings.json 里保存的 geometry 是「当时显示器布局」下的坐标；拔掉副屏/
# 断开扩展屏后再启动，窗口会被还原到不存在的屏幕上——进程活着但看不见，
# 用户以为「双击没反应」。启动时做一次可见性校验，屏幕外就拉回主屏。
# ---------------------------------------------------------------------------
_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
_WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
                ("szDevice", ctypes.c_wchar * 32)]


def _screen_rects():
    """枚举所有显示器：[(物理矩形, 工作区矩形), ...]，主屏排最前"""
    if _user32 is None:
        return []
    out = []

    def _cb(hmon, _hdc, _rect, _lparam):
        mi = _MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            m, r = mi.rcMonitor, mi.rcWork
            out.append((bool(mi.dwFlags & 1),        # MONITORINFOF_PRIMARY
                        (m.left, m.top, m.right, m.bottom),
                        (r.left, r.top, r.right, r.bottom)))
        return True

    proc = _MONITORENUMPROC(_cb)   # 局部引用防 GC，调用结束自然释放
    _user32.EnumDisplayMonitors(None, None, proc, 0)
    out.sort(key=lambda it: not it[0])
    return [(mon, work) for _is_primary, mon, work in out]


def _window_rect(widget):
    """窗口外框的屏幕坐标 (x, y, w, h)；取不到时回退 Tk 近似值。
    必须用 GetWindowRect 拿外框：winfo_rootx/y 是客户区原点，不含标题栏，
    窗口顶部被截在桌面上方时，客户区还看得见、外框其实已经出屏（v1.7.3）"""
    try:
        hwnd = _user32.GetAncestor(wintypes.HWND(widget.winfo_id()), 2)  # GA_ROOT
        rc = wintypes.RECT()
        if hwnd and _user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
    except Exception:  # noqa: BLE001
        pass
    try:
        return (widget.winfo_rootx(), widget.winfo_rooty(),
                widget.winfo_width(), widget.winfo_height())
    except Exception:  # noqa: BLE001
        return None


def _clamp_xy(x, y, w, h):
    """把窗口位置钳制回可见桌面，返回修正后的 (x, y)。
    与某屏相交 → 收进相交面积最大的那块屏（多屏改布局/改分辨率后窗口
    半截在桌面外、尤其是顶部被截的主因）；完全在屏外 → 拉回主屏工作区
    居中偏上。钳制基准用显示器物理矩形而非工作区：贴任务栏/压住任务栏的
    摆放是用户有意的，不该被拽走。"""
    rects = _screen_rects()
    if not rects or w < 50 or h < 50:   # 显示器信息拿不到 / 尺寸未就绪
        return x, y
    best, best_area = None, 0
    for mon, _work in rects:
        l, t, r, b = mon
        ix = min(x + w, r) - max(x, l)
        iy = min(y + h, b) - max(y, t)
        if ix > 0 and iy > 0 and ix * iy > best_area:
            best, best_area = mon, ix * iy
    if best is None:                    # 全出屏：主屏工作区居中偏上
        l, t, r, b = rects[0][1]
        return (l + max(0, (r - l - w) // 2),
                t + max(0, (b - t - h) // 3))
    l, t, r, b = best                   # 部分出屏：整体收进该屏
    return (min(max(x, l), max(l, r - w)),
            min(max(y, t), max(t, b - h)))


def _clamp_into_screen(widget):
    """启动时把窗口钳制回可见桌面（v1.7.1 救完全出屏；v1.7.3 起连部分
    出屏一起救——历史 geometry 在多屏改布局后常把顶部甩到桌面上方）"""
    rect = _window_rect(widget)
    if not rect:
        return
    x, y, w, h = rect
    nx, ny = _clamp_xy(x, y, w, h)
    if (nx, ny) != (x, y):
        widget.geometry(f"+{nx}+{ny}")


def _persist_geometry(widget):
    """保存前先钳制位置：坏坐标不落盘，下次启动不会先闪到屏外再被拉回。
    注意 Tk 负偏移用「-」作分隔符（360x600-200-100 = 在屏幕左上外），
    正则必须两种分隔符都认——负坐标恰恰是最需要钳制的输入"""
    g = widget.geometry()
    m = re.fullmatch(r"(\d+)x(\d+)([+-])-?(\d+)([+-])-?(\d+)", g or "")
    if not m:
        return g
    w, h, sx, xs, sy, ys = m.groups()
    w, h = int(w), int(h)
    x, y = int(xs) * (-1 if sx == "-" else 1), int(ys) * (-1 if sy == "-" else 1)
    nx, ny = _clamp_xy(x, y, w, h)
    return f"{w}x{h}+{nx}+{ny}"


def _raise_existing_instance():
    """单实例保护：把已运行实例带到前台。窗口可见时直接 SetForegroundWindow；
    缩在托盘里时（IsWindowVisible 为假），向托盘消息窗口发恢复消息让旧实例
    自己 deiconify——v1.8.2 前这里只找可见窗口，托盘里的实例双击 exe 毫无反应，
    用户以为程序退出了（实际只是旧实例藏起来 + 新实例按单实例规则退出）"""
    if _user32 is None:
        return

    tray_hwnd = _user32.FindWindowW("DC_TrayMsgWnd", None)
    if tray_hwnd:                       # 有托盘消息窗口 = 旧实例在跑
        _user32.PostMessageW(tray_hwnd, _WM_APP_RESTORE, 0, 0)

    def _cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetWindowTextW(hwnd, buf, 64)
        t = buf.value.lower()
        if ("日历" in t) or ("calendar" in t):
            _user32.SetForegroundWindow(hwnd)
            return False                 # 找到即停
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)


if getattr(sys, "frozen", False):
    # PyInstaller 打包成 exe 后，数据/设置跟着 exe 所在目录走
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "calendar.db"
SETTINGS_PATH = BASE_DIR / "settings.json"

# 程序版本 + 修订日志文件：每次改动请改版本号，并在 CHANGELOG.md 顶部补一条说明
# （界面「设置 → 📜 修订日志」直接读这个文件，方便随时回看改了什么）
APP_VERSION = "1.8.5"
CHANGELOG_FILE = "CHANGELOG.md"

# ---------------------------------------------------------------------------
# 系统托盘（纯 ctypes 实现，零第三方依赖；「最小化缩到托盘」用）
# 原理：注册一个自己的隐藏消息窗口接收托盘回调消息。Tcl/Tk 主循环本身就在泵
# 消息，线程内所有窗口的消息（含托盘回调）都会被派发到各自的窗口过程，
# 因此无需额外线程/消息循环，托盘事件天然落在 Tk 主线程上。
# ---------------------------------------------------------------------------
_NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP = 0x01, 0x02, 0x04
_WM_APP_TRAY = 0x8000 + 0x11      # 托盘回调消息（WM_APP 区段，避开 Tk 内部消息）
_WM_APP_RESTORE = 0x8000 + 0x12   # 第二实例请求恢复：缩在托盘里的窗口也拉回前台
_WM_DISPLAYCHANGE = 0x007E        # 显示器热插拔/改分辨率广播（v1.8.4 据此救窗口）
_WM_LBUTTONDBLCLK, _WM_LBUTTONUP, _WM_RBUTTONUP = 0x0203, 0x0202, 0x0205
_IMAGE_ICON, _LR_LOADFROMFILE = 1, 0x10
_MF_STRING, _MF_SEPARATOR, _MF_GRAYED = 0x0000, 0x0800, 0x00000001
_TPM_RETURNCMD, _TPM_NONOTIFY, _TPM_BOTTOMALIGN = 0x0100, 0x0080, 0x0020
_SM_CXSMICON, _SM_CYSMICON = 49, 50
_WM_NULL = 0x0000

if _user32 is not None:
    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
        wintypes.WPARAM, wintypes.LPARAM)

    class _WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT),
                    ("lpfnWndProc", _WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HANDLE),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR)]

    class _NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HICON),
                    ("szTip", ctypes.c_wchar * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", ctypes.c_wchar * 256),
                    ("uVersion", wintypes.UINT),
                    ("szInfoTitle", ctypes.c_wchar * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_ubyte * 16)]

    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    _shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                   wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT]
    _shell32.ExtractIconW.restype = wintypes.HICON
    _shell32.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                      wintypes.UINT]
    _user32.DestroyIcon.restype = wintypes.BOOL
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                        wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int,
                                        wintypes.HWND, wintypes.HMENU,
                                        wintypes.HINSTANCE, wintypes.LPVOID]
    _user32.DestroyWindow.restype = wintypes.BOOL
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.CreatePopupMenu.argtypes = []
    _user32.AppendMenuW.restype = wintypes.BOOL
    _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                    ctypes.c_size_t, wintypes.LPCWSTR]
    _user32.TrackPopupMenu.restype = wintypes.BOOL   # TPM_RETURNCMD 时返回所选项 id
    _user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND,
                                       ctypes.c_void_p]
    _user32.DestroyMenu.restype = wintypes.BOOL
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class TrayIcon:
    """系统托盘图标（Windows 专属，非 Windows 上相关方法自动失效）。

    用法（见 CalendarApp）：
      tray = TrayIcon(widget, icon_path, get_menu, on_activate, on_menu)
      tray.show("悬浮提示")   # 图标出现在通知区
      tray.hide()             # 图标消失
      tray.set_tip("新提示")  # 未显示时是空操作
      tray.destroy()          # 程序退出前清理
    get_menu 返回 [(key, 文本, 是否可用), ...]，key 为 None 表示分隔线；
    点击菜单项后回调 on_menu(key)。

    线程模型（v1.8.2 重写，修「托盘双击进程直接退出」）：
      托盘消息窗口和 GetMessage 泵跑在**独立守护线程**里，WndProc 回调在该
      线程只做「把回调塞进队列」；Tk 主线程用 after 轮询取出来执行。
      旧实现让 Tcl 主循环泵消息——Tcl 阻塞等待期间派发 ctypes WndProc 回调
      会踩 GIL 重入坑（PyEval_RestoreThread: thread state NULL），进程当场
      被 Windows 撕掉，连 crash.log 都来不及写。所有对 Tk 的访问都经队列
      回主线程，托盘线程不碰任何 Tk 对象。"""

    _CLASS_NAME = "DC_TrayMsgWnd"
    _ICON_ID = 1

    def __init__(self, widget, icon_path, get_menu, on_activate, on_menu,
                 on_display_change=None):
        self._widget = widget            # Tk 控件：用它的 after 轮询回主循环
        self._icon_path = str(icon_path or "")
        self._get_menu = get_menu        # () -> [(key, label, enabled)]
        self._on_activate = on_activate  # 左键单击：恢复窗口
        self._on_menu = on_menu          # (key) 菜单项被选中
        self._on_display_change = on_display_change  # 显示器布局变化广播
        self._nid = None                 # NOTIFYICONDATAW，None=托盘未显示
        self._hicon = None
        self._menu_hwnd = None
        self._proc_ref = None            # 窗口过程引用，防止被 GC 后崩溃
        self._cmd_map = {}
        self._created = False
        self._alive = True
        self._tid = None                 # 消息线程 id，退出时用它投 WM_QUIT
        self._q = queue.Queue()          # 托盘线程 → Tk 线程 的回调队列
        self._created_evt = threading.Event()
        if _user32 is not None:
            self._widget.after(60, self._drain)
            threading.Thread(target=self._msg_loop, daemon=True,
                             name="DC_Tray").start()

    # ---- 内部：消息线程（窗口创建 + 消息泵都在这条线程） ----
    def _msg_loop(self):
        self._proc_ref = _WNDPROC(self._proc)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._proc_ref
        wc.lpszClassName = self._CLASS_NAME
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        _user32.RegisterClassW(ctypes.byref(wc))   # 重复注册失败无妨
        hwnd = _user32.CreateWindowExW(
            0, self._CLASS_NAME, "", 0, 0, 0, 0, 0,
            None, None, wc.hInstance, None)
        self._menu_hwnd = hwnd
        self._tid = _kernel32.GetCurrentThreadId()
        self._created = bool(hwnd)
        self._created_evt.set()          # 主线程的 show() 在等这个
        if not hwnd:
            return
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _proc(self, hwnd, msg, wp, lp):
        if msg == _WM_APP_TRAY:
            if lp in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                self._emit(self._on_activate)
            elif lp == _WM_RBUTTONUP:
                self._popup_menu(hwnd)
            return 0
        if msg == _WM_APP_RESTORE:      # 第二实例双击 exe：恢复主窗口
            self._emit(self._on_activate)
            return 0
        if msg == _WM_DISPLAYCHANGE:    # 显示器热插拔/改分辨率：救回主窗口
            self._emit(self._on_display_change)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _emit(self, fn, *args):
        """托盘线程 → Tk 线程：回调只入队，由 Tk 线程的 _drain 执行"""
        if self._alive:
            self._q.put((fn, args))

    def _drain(self):
        """Tk 主线程轮询：执行托盘线程投来的回调（最多 20 条/轮防卡顿）"""
        if not self._alive:
            return
        for _ in range(20):
            try:
                fn, args = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:  # noqa: BLE001  托盘回调出错不能拖垮主循环
                pass
        self._widget.after(60, self._drain)

    # ---- 内部：图标加载 ----
    def _load_icon(self):
        """优先加载程序目录的 app.ico；源码运行没有 exe 图标可退，
        打包成 exe 后退而从 exe 自身提取内嵌图标"""
        if _user32 is None:
            return None
        cx = _user32.GetSystemMetrics(_SM_CXSMICON)
        cy = _user32.GetSystemMetrics(_SM_CYSMICON)
        if self._icon_path and Path(self._icon_path).exists():
            h = _user32.LoadImageW(None, self._icon_path, _IMAGE_ICON,
                                   cx, cy, _LR_LOADFROMFILE)
            if h:
                return h
        return _shell32.ExtractIconW(None, sys.executable, 0)

    # ---- 内部：右键原生菜单 ----
    def _popup_menu(self, hwnd):
        if not self._nid:
            return
        menu = _user32.CreatePopupMenu()
        self._cmd_map = {}
        for i, entry in enumerate(self._get_menu() or [], start=1):
            key, label, enabled = entry
            if key is None:
                _user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
            else:
                flags = _MF_STRING | (0 if enabled else _MF_GRAYED)
                if _user32.AppendMenuW(menu, flags, i, label):
                    self._cmd_map[i] = key
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        # TrackPopupMenu 的标准三件套：先抢前台（否则点外部菜单不收起），
        # 弹出后补发 WM_NULL 让前台归属恢复正常
        _user32.SetForegroundWindow(hwnd)
        chosen = _user32.TrackPopupMenu(
            menu, _TPM_RETURNCMD | _TPM_NONOTIFY | _TPM_BOTTOMALIGN,
            pt.x, pt.y, 0, hwnd, None)
        _user32.PostMessageW(hwnd, _WM_NULL, 0, 0)
        _user32.DestroyMenu(menu)
        key = self._cmd_map.get(chosen)
        if key:
            self._emit(self._on_menu, key)

    # ---- 对外接口 ----
    def show(self, tip: str = "") -> bool:
        """把图标加进通知区；已显示时等价于 set_tip。返回是否成功"""
        if _user32 is None:
            return False
        if not self._created_evt.wait(2.0) or not self._menu_hwnd:
            return False          # 消息窗口最多等 2 秒（正常毫秒级就绪）
        if self._nid is not None:
            self.set_tip(tip)
            return True
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._menu_hwnd
        nid.uID = self._ICON_ID
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _WM_APP_TRAY
        nid.hIcon = self._load_icon()
        if not nid.hIcon:
            return False
        nid.szTip = (tip or "")[:127]
        ok = _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))
        if not ok:   # 任务栏偶发重启后第一次会失败，立即重试一次
            ok = _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))
        if not ok:
            _user32.DestroyIcon(nid.hIcon)
            return False
        self._nid = nid
        self._hicon = nid.hIcon
        return True

    def set_tip(self, tip: str):
        """更新悬浮提示（如「今日待办 N 条」）；未显示时是空操作"""
        if self._nid is None or _user32 is None:
            return
        self._nid.szTip = (tip or "")[:127]
        _shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._nid))

    def hide(self):
        """从通知区移除图标"""
        if self._nid is not None and _user32 is not None:
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None

    def destroy(self):
        """退出前清理：移除图标、停掉消息线程（DestroyWindow 只能在创建线程
        调，这里给消息线程投 WM_QUIT 让它自己收尾）"""
        self._alive = False
        self.hide()
        if self._tid and _user32 is not None:
            _user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT
        if self._hicon and _user32 is not None:
            _user32.DestroyIcon(self._hicon)
            self._hicon = None


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "DesktopCalendar"

WEEK_HEADER = ["一", "二", "三", "四", "五", "六", "日"]  # 周一为首
WEEKDAY_NAMES = ["周" + h for h in WEEK_HEADER]  # 周一~周日，索引与 date.weekday() 对齐

COLOR = {
    "cell": "#ffffff",
    "cell_other": "#f3f4f6",
    "cell_today": "#fef9c3",
    "cell_selected": "#dbeafe",
    "text": "#1f2937",
    "text_sub": "#6b7280",
    "text_other": "#9ca3af",
    "accent": "#2563eb",
    "danger": "#dc2626",
    "done": "#9ca3af",
    "ok": "#16a34a",
}


# ---------------------------------------------------------------------------
# 数据层
# ---------------------------------------------------------------------------
# 任务类型键 -> 标签底色（标签文字随界面语言取 T("tag_day") 等）
TYPE_COLORS = {
    "day": "#dbeafe",
    "week": "#dcfce7",
    "month": "#fef3c7",
    "workday": "#ede9fe",
}
TYPE_ORDER = ["day", "week", "month", "workday"]
# 参与「周期系列」生成各期的任务类型（周/月/工作日）
SERIES_KINDS = ("week", "month", "workday")


# ---------------------------------------------------------------------------
# 双语界面文案（zh=中文 / en=English），T() 按当前语言取词
# ---------------------------------------------------------------------------
STR = {
    "zh": {
        "app_title": "桌面日历清单",
        "title_pending": "桌面日历清单 — 今日待办 {n} 项",
        "month_label": "{y} 年 {m} 月",
        "signature": "— 王的出品 —",
        "tab_cal": " 日历 ",
        "tab_list": " 全部清单 ",
        "tab_calc": " 日期计算 ",
        "btn_today": "今天",
        "btn_settings": "⚙ 设置",
        "btn_move": "移动",
        "btn_pin": "固定",
        "tag_day": "日", "tag_week": "周", "tag_month": "月",
        "type_day": "日任务", "type_week": "周任务", "type_month": "月任务",
        "lbl_remind": "提醒",
        "btn_add": "添加",
        "empty_hint": ("当天暂无任务\n输入内容、选类型后添加，默认不提醒\n"
                       "（周任务选星期 / 月任务选几号；勾选「提醒」选时间）\n"
                       "周任务 / 月任务会自动生成后续各期"),
        "day_stat": "待办 {p} / 共 {n}",
        "day_header": "{m}月{d}日 {week}{mark}",
        "today_mark": "（今天）",
        "week_head": "周",
        "mark_work": "班",
        "mark_rest": "休",
        "more_tasks": "…共{n}项",
        "menu_edit": "✏️ 编辑任务",
        "menu_remind": "⏰ 设置/修改提醒时间",
        "menu_clear_remind": "清除提醒",
        "menu_imp": "⭐ 标为重要",
        "menu_unimp": "☆ 取消重要",
        "menu_pin": "📌 置顶",
        "menu_unpin": "📌 取消置顶",
        "edit_title": "编辑任务",
        "edit_task": "任务内容",
        "edit_date": "日期",
        "edit_type": "类型",
        "edit_remind": "提醒时间",
        "enable_remind": "开启提醒",
        "min_step": "分钟按 5 分钟步进",
        "btn_ok": "确定",
        "btn_save": "保存",
        "btn_cancel": "取消",
        "btn_close": "关闭",
        "btn_edit": "✏️ 编辑选中",
        "btn_changelog": "📜 修订日志",
        "changelog_title": "修订日志",
        "changelog_missing": ("未找到 CHANGELOG.md。\n\n请把该文件放在程序（exe）"
                              "所在目录下，再点「修订日志」即可查看。"),
        "menu_del": "🗑 删除本条",
        "menu_del_series": "🗑 删除整个系列（{n} 期）",
        "apply_series": "应用到整个系列（后续各期同步）",
        "series_count": "周期任务：已自动生成 {n} 期（最近一期 {d}）",
        "del_series_ask": ("「{t}」是周期任务，共 {n} 期。\n\n"
                           "「是」= 删除整个系列\n「否」= 只删这一条"),
        "series_tip": "✔ 已生成 {n} 期（到 {d}）",
        "no_selection": "请先在列表里选中一条任务",
        "remind_win_title": "设置提醒",
        "time_label": "时间",
        "toast_title": "⏰ 任务提醒",
        "toast_all_done": "全部完成",
        "toast_got": "知道了",
        "list_hint": "全部任务（按日期排序，双击切换完成状态）",
        "btn_toggle": "标记完成/取消",
        "btn_del_sel": "删除选中",
        "btn_clear": "清理已完成",
        "btn_export": "导出",
        "btn_import": "导入",
        "col_date": "日期", "col_status": "状态", "col_type": "类型",
        "col_remind": "提醒", "col_task": "任务",
        "st_done": "已完成", "st_overdue": "逾期", "st_today": "今天",
        "st_future": "未来",
        # 日期计算器
        "calc_countdown": "节日倒计时",
        "calc_pick": "距 离",
        "calc_days_until": "{d} 还有 {n} 天（约 {w} 周零 {r} 天）",
        "calc_days_since": "{d} 已过 {n} 天",
        "calc_target_today": "{d} 就是今天！",
        "calc_between": "两日期相差",
        "calc_date1": "起始日期", "calc_date2": "结束日期",
        "calc_diff": "相差 {n} 天（约 {w} 周零 {r} 天）",
        "calc_same": "两个是同一天",
        "calc_offset": "今天 ± N 天",
        "calc_days": "天数（可为负）",
        "calc_offset_result": "{n} 天后是 {d} {w}",
        "calc_offset_before": "{a} 天前是 {d} {w}",
        "calc_btn": "计算",
        "calc_bad_date": "日期格式应为 YYYY-MM-DD，例如 2026-10-03",
        "calc_bad_days": "天数应为整数（可为负），例如 30 或 -7",
        "no_empty_title": "任务内容不能为空",
        "weekday_names": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        "weekday_short": ["一", "二", "三", "四", "五", "六", "日"],
        "h_newyear": "元旦", "h_spring": "春节", "h_qingming": "清明",
        "h_labour": "劳动节", "h_dragon": "端午", "h_midaut": "中秋",
        "h_national": "国庆",
        # 设置对话框
        "settings": "设置",
        "opacity": "窗口透明度",
        "opacity_hint": "拖动滑杆即时生效",
        "cal_font": "框架文字（星期表头与日期数字）",
        "task_font": "内容文字（任务预览、日清单与全部清单）",
        "size_unit": "号",
        "disp_label": "日历显示：",
        "disp_weekno": "周数", "disp_lunar": "农历", "disp_terms": "节气",
        "disp_rest": "休息日",
        "week_start": "每周开始于",
        "monday": "周一", "sunday": "周日",
        "topmost": "窗口置顶（固定显示在桌面最前，不被其他窗口挡住）",
        "bottom_layer": ("贴桌面底层（固定状态生效，仅位于壁纸之上，"
                         "在图标和所有应用之下）"),
        "autostart": "开机自动启动（写入当前用户注册表 Run 项）",
        "autostart_na": "（当前系统不支持开机自启设置）",
        "show_holiday": "日历显示法定节假日与调休补班（如「中秋」「班」）",
        "cal_fg": "框架文字颜色（表头与日期）：",
        "task_fg": "内容文字颜色（任务文字）：",
        "win_size": "窗口尺寸（宽 × 高，可直接输入）：",
        "win_w": "宽",
        "win_h": "高",
        "btn_apply_size": "应用尺寸",
        "win_size_hint": "（拖动窗口边缘也可调整）",
        "size_invalid": "宽高需为数字（宽 640–4000，高 420–3000）",
        "accent_color": "主题色（角标与选中格）：",
        "bg_color": "背景颜色：",
        "bg_default": "默认", "bg_blue": "浅蓝", "bg_green": "浅绿",
        "bg_pink": "浅粉", "bg_beige": "米黄", "bg_gray": "深灰",
        "custom": "自定义…",
        "bg_image": "背景图片：",
        "pick_image": "选择图片…",
        "clear_image": "清除图片",
        "bg_image_hint": "铺满窗口底层，内容浮于其上",
        "no_pillow": "缺少 Pillow 库，无法显示图片背景\n\n安装：pip install Pillow",
        "ft_json": "JSON 备份（完整）", "ft_csv": "CSV 表格（Excel）",
        "ft_taskfile": "任务文件 JSON / CSV",
        "ft_json_plain": "JSON", "ft_csv_plain": "CSV", "ft_all": "全部文件",
        "pillow_read_fail": "图片读取失败：{e}",
        "language": "界面语言 / Language：",
        "lang_restart": "界面语言将在下次启动程序后生效",
        "wecom_hook": "企业微信 Webhook：",
        "btn_test": "测试",
        "wecom_hook_hint": "获取：企业微信群聊 → 设置 → 群机器人 → 添加 → 复制 Webhook 地址",
        "wecom_also_push": "任务提醒同时推送到企业微信",
        "btn_push_today": "推送今日待办",
        "wecom_app": "或用自建应用推送（发到个人企业微信）：",
        "btn_test_app": "测试应用",
        "wecom_app_hint": "  应用推送需在管理后台给该应用配置「企业可信IP」",
        "btn_done": "完成",
        # 消息提示
        "warn_title": "桌面日历清单",
        "time_format": "提醒时间格式应为 HH:MM（24小时制），例如 09:30",
        "save_settings_failed": "保存设置失败：{e}",
        "autostart_failed": "修改开机自启失败：{e}",
        "no_wecom_cfg": "请先在设置里配置 Webhook 或应用参数",
        "no_wecom_cfg2": "请先在设置里填写 Webhook 或应用参数",
        "no_tasks_today": "今天还没有任务，先添加再推送吧",
        "tray_show": "显示主窗口",
        "tray_add": "新增任务…",
        "qadd_title": "快速新增任务",
        "qadd_date": "日期",
        "qadd_today": "今天",
        "qadd_tomorrow": "明天",
        "qadd_dayafter": "后天",
        "qadd_time": "提醒(HH:MM)",
        "qadd_imp": "重要",
        "qadd_btn": "添加",
        "qadd_added": "已添加：{t}",
        "qadd_dup": "该日期已有同名任务，未重复添加",
        "qadd_time_bad": "提醒时间需为 HH:MM（如 09:30）",
        "tray_push": "推送今日待办（未完成）",
        "tray_push_none": "今天没有待办任务",
        "tray_push_sent": "已推送 {n} 条待办到企业微信",
        "tray_push_fail": "推送失败：{e}",
        "tray_clean": "清理已完成任务",
        "tray_clean_done": "已清理 {n} 条已完成任务",
        "tray_clean_none": "没有已完成的任务",
        "tray_settings": "设置…",
        "tray_exit": "退出",
        "tray_tip": "桌面日历 · 今日待办 {n} 条",
        "dup_series_ask": "同名「{t}」任务已有 {n} 期落在相同日期（如 {d}）。\n继续添加会出现同一天多条同名任务。\n\n仍要添加吗？",
        "edit_clash": "该系列在 {d} 已有一期，同系列两期不能落在同一天。\n请换个日期，或直接编辑那一天的任务。",
        "push_pick": "勾选要推送到企业微信的任务（{m}月{d}日）：",
        "select_all": "全选", "select_none": "全不选",
        "push": "推送",
        "push_need_one": "请至少勾选一条任务",
        "push_lines": "**📋 桌面日历清单 · {m}月{d}日 待办（{n} 条）**",
        "wecom_result_ok": "已推送到：{names}",
        "wecom_result_sent": "已发送",
        "wecom_fail": "企业微信推送",
        "wecom_test_sent": "测试消息已发送，请到企业微信群里查看",
        "wecom_bad_hook": ("Webhook 地址无效（错误码 93000）。\n\n"
                           "请到企业微信群聊 → 设置 → 群机器人 → 查看机器人，"
                           "复制完整 Webhook 地址。\n"
                           "注意：key 由系统生成，只包含数字和 a-f 的字母，"
                           "地址里不应有 xxx 或其他手动改动。"),
        "wecom_send_fail": "发送失败：{e}",
        "wecom_test_ok": "测试消息已发送，请到你的企业微信查看",
        "wecom_ip_hint": ("发送失败：{e}\n\n若是 IP 白名单问题：管理后台 → 应用 → "
                          "该应用 → 企业可信IP → 配置，加上本机出口 IP"),
        "wecom_test_msg": "**桌面日历清单** 企业微信推送测试成功 ✅",
        "wecom_app_test_msg": "**桌面日历清单** 企业微信应用推送测试成功 ✅",
        "wecom_fill": "CorpID / AgentID / Secret 需填写完整",
        "wecom_remind_head": "**⏰ 桌面日历清单 · 任务提醒**",
        "export_title": "导出任务",
        "export_fail": "导出失败",
        "export_fail_msg": "写入文件失败：{e}",
        "export_done": "导出完成",
        "export_done_msg": "已导出 {n} 条任务到：\n{path}",
        "import_title": "导入任务",
        "import_fail": "导入失败",
        "import_read_fail": "读取文件失败：{e}",
        "import_none": "文件里没有可识别的有效任务。",
        "import_ask": ("识别到 {n} 条任务。\n\n"
                       "「是」= 清空现有任务后导入（适合备份恢复）\n"
                       "「否」= 合并导入（自动跳过重复任务）"),
        "import_done": "导入完成",
        "import_done_msg": "成功导入 {a} 条，跳过 {s} 条重复。",
        # 当前国家与乌兹别克斯坦节假日（月历格子用短名）
        "country_label": "当前国家：",
        "country_cn": "中国", "country_uz": "乌兹别克斯坦",
        "h_uz_iftar": "开斋节", "h_uz_adha": "宰牲节",
        "h_uz_navruz": "诺鲁孜节", "h_uz_women": "妇女节",
        "h_uz_memory": "纪念日", "h_uz_independence": "独立日",
        "h_uz_teachers": "教师节", "h_uz_constitution": "宪法日",
        # 工作日任务 / 每N周
        "type_workday": "工作日任务", "tag_workday": "工",
        "iv_weeks": ["每周", "每2周", "每3周", "每4周", "每6周"],
        # 提前提醒 / 自动备份
        "remind_early": "提前提醒：",
        "early_vals": ["不提前", "5分钟", "10分钟", "30分钟", "1小时", "1天"],
        "span_min": "{n} 分钟", "span_hour": "{n} 小时", "span_day": "{n} 天",
        "early_in": "{n}后开始",
        "toast_early": "⏰ 即将开始",
        "auto_backup": "每日自动备份数据（data\\backup\\，保留最近10份）",
        # 倒数日 / 纪念日
        "event_head": "倒数日 / 纪念日",
        "event_add": "＋ 添加",
        "event_none": "还没有倒数日或纪念日",
        "event_name": "名称",
        "event_date": "日期",
        "event_kind": "类型",
        "event_annual": "每年纪念日",
        "event_countdown": "单次倒数",
        "event_lunar": "按农历",
        "event_left": "还有 {n} 天",
        "event_today": "就是今天！",
        "event_past": "已过 {n} 天",
        "event_desc_annual": "每年 {m}/{d}",
        "event_desc_lunar": "每年农历 {m}/{d}",
        "event_win_title": "添加倒数日 / 纪念日",
        "event_empty_name": "名称不能为空",
        "toast_event": "🎉 今日纪念",
        # ICS 日历订阅
        "ics_head": "日历订阅（ICS）：",
        "ics_sync": "立即同步",
        "ics_hint": ("粘贴 .ics 订阅网址，事件按日期自动建为任务"
                     "（如 https://www.officeholidays.com/ics/uzbekistan）"),
        "ics_ok": "已导入 {n} 条（跳过 {s} 条重复）",
        "ics_fail": "订阅同步失败：{e}",
        "ics_no_url": "请先填写 ICS 订阅网址",
    },
    "en": {
        "app_title": "Desktop Calendar",
        "title_pending": "Desktop Calendar — {n} due today",
        "month_label": "{y} / {m}",
        "signature": "— King's Product —",
        "tab_cal": " Calendar ",
        "tab_list": " All Tasks ",
        "tab_calc": " Date Calc ",
        "btn_today": "Today",
        "btn_settings": "⚙ Settings",
        "btn_move": "Move",
        "btn_pin": "Pin",
        "tag_day": "D", "tag_week": "W", "tag_month": "M",
        "type_day": "Day task", "type_week": "Week task", "type_month": "Month task",
        "lbl_remind": "Remind",
        "btn_add": "Add",
        "empty_hint": ("No tasks for this day yet.\nType, pick a type, then Add "
                       "(no reminder by default).\n(Week tasks pick a weekday / "
                       "month tasks a day; tick Remind for time)\n"
                       "Week / month tasks generate the later occurrences "
                       "automatically"),
        "day_stat": "{p} pending / {n} total",
        "day_header": "{week} {m}/{d}{mark}",
        "today_mark": " (Today)",
        "week_head": "Wk",
        "mark_work": "W",
        "mark_rest": "R",
        "more_tasks": "…{n} in total",
        "menu_edit": "✏️ Edit task",
        "menu_remind": "⏰ Set / change reminder",
        "menu_clear_remind": "Clear reminder",
        "menu_imp": "⭐ Mark important",
        "menu_unimp": "☆ Unmark important",
        "menu_pin": "📌 Pin",
        "menu_unpin": "📌 Unpin",
        "edit_title": "Edit Task",
        "edit_task": "Task",
        "edit_date": "Date",
        "edit_type": "Type",
        "edit_remind": "Reminder",
        "enable_remind": "Enable reminder",
        "min_step": "minutes in 5-min steps",
        "btn_ok": "OK",
        "btn_save": "Save",
        "btn_cancel": "Cancel",
        "btn_close": "Close",
        "btn_edit": "✏️ Edit selected",
        "btn_changelog": "📜 Changelog",
        "changelog_title": "Changelog",
        "changelog_missing": ("CHANGELOG.md not found.\n\nPut that file next to the "
                              "program (exe), then open Changelog again."),
        "menu_del": "🗑 Delete this one",
        "menu_del_series": "🗑 Delete whole series ({n})",
        "apply_series": "Apply to whole series (all later occurrences)",
        "series_count": "Recurring: {n} occurrences generated (latest {d})",
        "del_series_ask": ("\"{t}\" is a recurring task with {n} occurrences.\n\n"
                           "\"Yes\" = delete the whole series\n"
                           "\"No\" = delete only this one"),
        "series_tip": "✔ {n} occurrences created (until {d})",
        "no_selection": "Select a task in the list first",
        "remind_win_title": "Set Reminder",
        "time_label": "Time",
        "toast_title": "⏰ Task Reminder",
        "toast_all_done": "Complete All",
        "toast_got": "Got it",
        "list_hint": "All tasks (by date; double-click to toggle done)",
        "btn_toggle": "Toggle Done",
        "btn_del_sel": "Delete Selected",
        "btn_clear": "Clear Completed",
        "btn_export": "Export",
        "btn_import": "Import",
        "col_date": "Date", "col_status": "Status", "col_type": "Type",
        "col_remind": "Remind", "col_task": "Task",
        "st_done": "Done", "st_overdue": "Overdue", "st_today": "Today",
        "st_future": "Upcoming",
        "calc_countdown": "Holiday countdown",
        "calc_pick": "Days until",
        "calc_days_until": "{n} days until {d} (about {w} wk {r} d)",
        "calc_days_since": "{n} days since {d}",
        "calc_target_today": "{d} is today!",
        "calc_between": "Days between two dates",
        "calc_date1": "Start date", "calc_date2": "End date",
        "calc_diff": "{n} days apart (about {w} wk {r} d)",
        "calc_same": "The two dates are the same day",
        "calc_offset": "Today ± N days",
        "calc_days": "Days (may be negative)",
        "calc_offset_result": "{n} days from today: {d} {w}",
        "calc_offset_before": "{a} days ago was {d} {w}",
        "calc_btn": "Calculate",
        "calc_bad_date": "Date format should be YYYY-MM-DD, e.g. 2026-10-03",
        "calc_bad_days": "Days should be an integer (can be negative), e.g. 30 or -7",
        "no_empty_title": "Task title cannot be empty",
        "weekday_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "weekday_short": ["M", "T", "W", "T", "F", "S", "S"],
        "h_newyear": "New Year", "h_spring": "Spring Festival",
        "h_qingming": "Qingming", "h_labour": "Labour Day",
        "h_dragon": "Dragon Boat", "h_midaut": "Mid-Autumn",
        "h_national": "National Day",
        "settings": "Settings",
        "opacity": "Window opacity",
        "opacity_hint": "Applies while you drag",
        "cal_font": "Frame text (weekday header & dates)",
        "task_font": "Content text (previews, day panel & list)",
        "size_unit": "pt",
        "disp_label": "Calendar shows:",
        "disp_weekno": "Week No.", "disp_lunar": "Lunar", "disp_terms": "Terms",
        "disp_rest": "Rest days",
        "week_start": "Week starts on",
        "monday": "Monday", "sunday": "Sunday",
        "topmost": "Always on top (stays in front of all windows)",
        "bottom_layer": ("Desktop bottom layer (when pinned: above wallpaper "
                         "only, below icons and all apps)"),
        "autostart": "Start with Windows (writes HKCU Run key)",
        "autostart_na": "(Autostart is not supported on this system)",
        "show_holiday": "Show public holidays & makeup workdays (e.g. \"National\", \"W\")",
        "cal_fg": "Frame text color:",
        "task_fg": "Content text color:",
        "win_size": "Window size (W x H, type directly):",
        "win_w": "W",
        "win_h": "H",
        "btn_apply_size": "Apply size",
        "win_size_hint": "(or drag window edges)",
        "size_invalid": "Width/height must be numbers (W 640-4000, H 420-3000)",
        "accent_color": "Accent color (badges & selection):",
        "bg_color": "Background color:",
        "bg_default": "Default", "bg_blue": "Blue", "bg_green": "Green",
        "bg_pink": "Pink", "bg_beige": "Beige", "bg_gray": "Gray",
        "custom": "Custom…",
        "bg_image": "Background image:",
        "pick_image": "Choose image…",
        "clear_image": "Clear image",
        "bg_image_hint": "Stretched under all content",
        "no_pillow": ("Pillow is required to show an image background\n\n"
                      "Install: pip install Pillow"),
        "ft_json": "JSON backup (full)", "ft_csv": "CSV (Excel)",
        "ft_taskfile": "Task files JSON / CSV",
        "ft_json_plain": "JSON", "ft_csv_plain": "CSV", "ft_all": "All files",
        "pillow_read_fail": "Failed to read image: {e}",
        "language": "界面语言 / Language:",
        "lang_restart": "The interface language takes effect after restart",
        "wecom_hook": "WeCom Webhook:",
        "btn_test": "Test",
        "wecom_hook_hint": "Get it: WeCom group → Settings → Group Bot → Add → copy Webhook URL",
        "wecom_also_push": "Also push reminders to WeCom",
        "btn_push_today": "Push today's tasks",
        "wecom_app": "Or use a WeCom app (send to yourself):",
        "btn_test_app": "Test app",
        "wecom_app_hint": "  Configure a trusted IP for the app in the admin console",
        "btn_done": "Done",
        "warn_title": "Desktop Calendar",
        "time_format": "Reminder time should be HH:MM (24-hour), e.g. 09:30",
        "save_settings_failed": "Failed to save settings: {e}",
        "autostart_failed": "Failed to change autostart: {e}",
        "no_wecom_cfg": "Please configure a Webhook or app parameters in Settings first",
        "no_wecom_cfg2": "Please fill in the Webhook or app parameters in Settings first",
        "no_tasks_today": "No tasks for today yet — add some first",
        "tray_show": "Show main window",
        "tray_add": "Add task…",
        "qadd_title": "Quick add task",
        "qadd_date": "Date",
        "qadd_today": "Today",
        "qadd_tomorrow": "Tomorrow",
        "qadd_dayafter": "Day after",
        "qadd_time": "Remind (HH:MM)",
        "qadd_imp": "Important",
        "qadd_btn": "Add",
        "qadd_added": "Added: {t}",
        "qadd_dup": "A task with this title already exists on that date",
        "qadd_time_bad": "Time must be HH:MM (e.g. 09:30)",
        "tray_push": "Push today's pending tasks",
        "tray_push_none": "Nothing pending today",
        "tray_push_sent": "Pushed {n} tasks to WeCom",
        "tray_push_fail": "Push failed: {e}",
        "tray_clean": "Clear completed tasks",
        "tray_clean_done": "Cleared {n} completed tasks",
        "tray_clean_none": "No completed tasks",
        "tray_settings": "Settings…",
        "tray_exit": "Exit",
        "tray_tip": "Desktop Calendar · {n} pending today",
        "dup_series_ask": "A \"{t}\" series already covers {n} of these dates (e.g. {d}).\nAdding again will show duplicate rows on the same day.\n\nAdd anyway?",
        "edit_clash": "This series already has an occurrence on {d}.\nTwo occurrences of one series can't share a day — pick another date or edit that one.",
        "push_pick": "Pick tasks to push to WeCom ({m}/{d}):",
        "select_all": "All", "select_none": "None",
        "push": "Push",
        "push_need_one": "Please tick at least one task",
        "push_lines": "**📋 Desktop Calendar · {m}/{d} tasks ({n})**",
        "wecom_result_ok": "Pushed to: {names}",
        "wecom_result_sent": "Sent",
        "wecom_fail": "WeCom Push",
        "wecom_test_sent": "Test message sent — check your WeCom group",
        "wecom_bad_hook": ("Invalid Webhook URL (error 93000).\n\nOpen the WeCom "
                           "group → Settings → Group Bot → View Bot and copy the "
                           "full Webhook URL.\nNote: the key is system-generated, "
                           "digits and a-f letters only — no xxx or manual edits."),
        "wecom_send_fail": "Send failed: {e}",
        "wecom_test_ok": "Test message sent — check your WeCom",
        "wecom_ip_hint": ("Send failed: {e}\n\nIf it is an IP whitelist issue: "
                          "Admin console → App → your app → Trusted IP → add "
                          "this machine's outbound IP"),
        "wecom_test_msg": "**Desktop Calendar** WeCom push test OK ✅",
        "wecom_app_test_msg": "**Desktop Calendar** WeCom app push test OK ✅",
        "wecom_fill": "CorpID / AgentID / Secret are all required",
        "wecom_remind_head": "**⏰ Desktop Calendar · Task Reminder**",
        "export_title": "Export Tasks",
        "export_fail": "Export failed",
        "export_fail_msg": "Failed to write file: {e}",
        "export_done": "Export complete",
        "export_done_msg": "Exported {n} tasks to:\n{path}",
        "import_title": "Import Tasks",
        "import_fail": "Import failed",
        "import_read_fail": "Failed to read file: {e}",
        "import_none": "No valid tasks found in the file.",
        "import_ask": ("Found {n} tasks.\n\n"
                       "\"Yes\" = clear existing tasks, then import (restore)\n"
                       "\"No\" = merge import (duplicates skipped)"),
        "import_done": "Import complete",
        "import_done_msg": "Imported {a}, skipped {s} duplicates.",
        "country_label": "Country:",
        "country_cn": "China", "country_uz": "Uzbekistan",
        "h_uz_iftar": "Eid al-Fitr", "h_uz_adha": "Eid al-Adha",
        "h_uz_navruz": "Navruz", "h_uz_women": "Women's Day",
        "h_uz_memory": "Memory Day", "h_uz_independence": "Independence",
        "h_uz_teachers": "Teachers Day", "h_uz_constitution": "Constitution",
        "type_workday": "Workday task", "tag_workday": "W",
        "iv_weeks": ["Every week", "Every 2 wk", "Every 3 wk", "Every 4 wk",
                     "Every 6 wk"],
        "remind_early": "Remind early:",
        "early_vals": ["Off", "5 min", "10 min", "30 min", "1 hr", "1 day"],
        "span_min": "{n} min", "span_hour": "{n} hr", "span_day": "{n} d",
        "early_in": "starts in {n}",
        "toast_early": "⏰ Starting soon",
        "auto_backup": "Daily auto backup (data\\backup\\, keep latest 10)",
        "event_head": "Countdown / Anniversaries",
        "event_add": "＋ Add",
        "event_none": "No countdown or anniversary yet",
        "event_name": "Name",
        "event_date": "Date",
        "event_kind": "Type",
        "event_annual": "Yearly anniversary",
        "event_countdown": "One-time countdown",
        "event_lunar": "Lunar date",
        "event_left": "{n} days left",
        "event_today": "Today!",
        "event_past": "{n} days ago",
        "event_desc_annual": "Yearly {m}/{d}",
        "event_desc_lunar": "Yearly lunar {m}/{d}",
        "event_win_title": "Add Countdown / Anniversary",
        "event_empty_name": "Name cannot be empty",
        "toast_event": "🎉 Today's Event",
        "ics_head": "Calendar subscription (ICS):",
        "ics_sync": "Sync now",
        "ics_hint": ("Paste an .ics URL; events become tasks on their dates "
                     "(e.g. https://www.officeholidays.com/ics/uzbekistan)"),
        "ics_ok": "Imported {n} ({s} duplicates skipped)",
        "ics_fail": "Subscription sync failed: {e}",
        "ics_no_url": "Please enter the ICS URL first",
    },
}

# 当前界面语言（由 CalendarApp 启动时按设置赋值；T() 据此取词）
LANG = "zh"
# 当前国家（cn=中国 / uz=乌兹别克斯坦）：决定月历的工作日/休息日规则
COUNTRY = "cn"


def T(key, **kw):
    """取当前语言的界面文案；缺失键回退中文，支持 {n} 占位符填充"""
    text = STR.get(LANG, {}).get(key) or STR["zh"][key]
    return text.format(**kw) if kw else text


def weekday_names():
    """当前语言的星期全名列表（索引与 date.weekday() 对齐：0=周一）"""
    return STR[LANG]["weekday_names"]


def grid_weekday(i):
    """月历表头显示名：中文「周一~周日」，英文 Mon~Sun"""
    if LANG == "en":
        return STR["en"]["weekday_names"][i]
    return "周" + STR["zh"]["weekday_short"][i]

# 法定节假日英文名 -> 中文短名（chinese_calendar 库返回英文名）
# 注意：清明的库内英文名是 "Tomb-sweeping Day"，不是 "Qingming Festival"，
# 早期只写了后者，导致中文界面清明格显示成英文原名。两个写法都保留。
HOLIDAY_CN = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Qingming Festival": "清明",
    "Tomb-sweeping Day": "清明",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午",
    "Mid-autumn Festival": "中秋",
    "National Day": "国庆",
}

# 法定节假日英文名 -> 英文短名（英文界面月历格子用，需短小不挤破格子）
HOLIDAY_EN_SHORT = {
    "New Year's Day": "New Year",
    "Spring Festival": "Spring F.",
    "Qingming Festival": "Qingming",
    "Tomb-sweeping Day": "Qingming",
    "Labour Day": "Labour",
    "Dragon Boat Festival": "Dragon Boat",
    "Mid-autumn Festival": "Mid-Autumn",
    "National Day": "National",
}


def holiday_disp(name):
    """节日名转当前语言的短显示名：chinese_calendar 返回英文名（中文界面映射
    回中文短名）；乌兹别克节日直接是 STR 文案键；未知名称原样返回"""
    if name in HOLIDAY_CN or name in HOLIDAY_EN_SHORT:
        return HOLIDAY_EN_SHORT.get(name, name) if LANG == "en" \
            else HOLIDAY_CN.get(name, name)
    if name in STR.get(LANG, STR["zh"]):
        return T(name)
    return name


# 英文界面下**不显示**的中国传统节日：春节 / 清明 / 端午 / 中秋。
# 这几个按农历或节气推算，英文用户没有对应概念（与「英文界面不显示农历、节气」
# 同一口径）；元旦、劳动节、国庆属国际通行节日，英文界面照常显示。
# 隐藏只作用于节日名：该日的「休 / 班」标记与红底仍按中国法定假日规则保留。
# 英文用户若想连中国工作日一起不看，把设置里的「国家」切到 Uzbekistan 更彻底。
CN_TRAD_KEYS = {"h_spring", "h_qingming", "h_dragon", "h_midaut"}
# 匹配 chinese_calendar 的英文原名（含「国庆中秋连休」这类组合名）
_CN_TRAD_PAT = ("spring festival", "tomb-sweeping", "qingming",
                "dragon boat", "mid-autumn")


def hide_holiday(name):
    """该节日是否在英文界面下隐藏。name 可为 chinese_calendar 的英文原名，
    也可为 STR 文案键（如 h_midaut）"""
    if LANG != "en" or not name:
        return False
    if name in CN_TRAD_KEYS:
        return True
    low = name.lower()
    return any(p in low for p in _CN_TRAD_PAT)


# ---------------------------------------------------------------------------
# 乌兹别克斯坦法定节假日（country = "uz" 时使用）
# 数据取自 python-holidays 的乌兹别克斯坦官方数据（含总统令调休）。
# 开斋节/宰牲节是伊斯兰历节日，2027 年起为天文预估日期，官方公告后应核对
# ---------------------------------------------------------------------------
# 固定公历节日：(月, 日) -> 文案键（均为法定非工作日）
UZ_FIXED_HOLIDAYS = {
    (1, 1): "h_newyear",           # 新年
    (3, 8): "h_uz_women",          # 国际妇女节
    (3, 21): "h_uz_navruz",        # 诺鲁孜节
    (5, 9): "h_uz_memory",         # 记忆与荣誉日
    (9, 1): "h_uz_independence",   # 独立日
    (10, 1): "h_uz_teachers",      # 教师节
    (12, 8): "h_uz_constitution",  # 宪法日
}
# 开斋节/宰牲节：伊斯兰历每年约提前 11 天，按官方公告逐年内置
UZ_ISLAMIC_HOLIDAYS = {
    2024: {"h_uz_iftar": (4, 10), "h_uz_adha": (6, 16)},
    2025: {"h_uz_iftar": (3, 30), "h_uz_adha": (6, 6)},
    2026: {"h_uz_iftar": (3, 20), "h_uz_adha": (5, 27)},
    2027: {"h_uz_iftar": (3, 9), "h_uz_adha": (5, 16)},
}
# 政府调休：{年份: {"rest": {"月日": 节日键或None(纯补休)},
#                   "work": {"月日"...}   补班的周六日}}
UZ_TRANSFERS = {
    2024: {
        "rest": {"01-02": None, "03-22": None, "04-11": None, "04-12": None,
                 "06-17": "h_uz_adha", "06-18": None,
                 "09-02": "h_uz_independence", "09-03": None,
                 "12-09": "h_uz_constitution", "12-30": None, "12-31": None},
        "work": {"01-06", "04-13", "12-14"},
    },
    2025: {
        "rest": {"01-02": None, "03-10": "h_uz_women",
                 "03-31": "h_uz_iftar", "12-31": None},
        "work": {"01-04"},
    },
    2026: {
        "rest": {"01-02": None, "03-09": "h_uz_women", "03-23": "h_uz_navruz",
                 "05-11": "h_uz_memory", "05-28": None, "05-29": None,
                 "08-31": None, "12-31": None},
        "work": {"12-12"},
    },
    2027: {
        "rest": {"03-22": "h_uz_navruz", "05-10": "h_uz_memory",
                 "05-17": "h_uz_adha"},
        "work": set(),
    },
}


def _day_marks_uz(d: date):
    """乌兹别克斯坦规则：周六日双休 + 上表法定节日 + 政府调休；
    未覆盖调休数据的年份按普通周末处理"""
    key = d.strftime("%m-%d")
    tr = UZ_TRANSFERS.get(d.year, {})
    hol = UZ_FIXED_HOLIDAYS.get((d.month, d.day))
    if hol is None:
        for name, (m, dd) in UZ_ISLAMIC_HOLIDAYS.get(d.year, {}).items():
            if (m, dd) == (d.month, d.day):
                hol = name
                break
    rest_transfer = key in tr.get("rest", {})
    if rest_transfer:
        # 顺延补休日带节日名（如独立日顺延到周一），纯补休为 None
        hol = hol or tr["rest"][key]
    if hol or rest_transfer:
        return hol, True, False
    if key in tr.get("work", ()):
        return None, False, True
    return None, d.weekday() >= 5, False


def _day_marks_cn(d: date):
    """中国规则：chinese_calendar 的法定节假日与调休补班；
    未安装或数据未覆盖时按普通周末判断"""
    try:
        from chinese_calendar import get_holiday_detail, is_workday
        is_hol, name = get_holiday_detail(d)
        work = is_workday(d)
        # 返回英文原名，显示前由 holiday_disp() 按当前语言转换。
        # 早期版本在这里就转成中文，导致 holiday_disp 拿到中文后查 HOLIDAY_EN_SHORT
        # 查不到、原样返回，英文界面因此显示「中秋」这类中文节日名。
        hol = name if (is_hol and name) else None
        makeup = (not is_hol) and work and d.weekday() >= 5
        # 休息日 = 法定节假日 或 没被调成上班的周末。不能直接拿 is_hol 当
        # is_rest：装了 chinese_calendar 后普通周六日 is_hol=False，月历上
        # 周末就全都不显示「休」了，与未装库时的兜底行为不一致。
        is_rest = is_hol or (d.weekday() >= 5 and not work)
        return hol, is_rest, makeup
    except Exception:  # noqa: BLE001
        return None, d.weekday() >= 5, False


def day_marks(d: date):
    """按设置的国家返回 (节日文案键或None, 是否休息日, 是否调休补班)。
    英文界面下把中国传统节日名置为 None（不显示「中秋」这类名字）；
    休息日与调休补班照常返回——哪天休息是中国法定安排，与界面语言无关
    （想彻底不看中国工作日，把「国家」切到 Uzbekistan 即可）。"""
    hol, is_rest, makeup = (_day_marks_uz(d) if COUNTRY == "uz"
                            else _day_marks_cn(d))
    if hide_holiday(hol):
        hol = None
    return hol, is_rest, makeup


# 农历节日推算条件：键 -> (农历月, 农历日)；春节=正月初一、端午=五月初五、中秋=八月十五
_LUNAR_MATCH = {"h_spring": (1, 1), "h_dragon": (5, 5), "h_midaut": (8, 15)}


def upcoming_holidays():
    """返回未来约 13 个月的法定节日 [(文案键, 日期), ...]，按日期升序。
    乌兹别克斯坦：直接查内置节日表。中国：元旦/劳动节/国庆按公历直接推算，
    春节/端午/中秋用 cnlunar 逐日扫农历，清明用节气名识别。
    任一来源失败就跳过该项，绝不抛错。"""
    today = date.today()
    if COUNTRY == "uz":
        out = []
        for y in (today.year, today.year + 1):
            for (m, dd), key in UZ_FIXED_HOLIDAYS.items():
                if date(y, m, dd) >= today:
                    out.append((key, date(y, m, dd)))
            for key, (m, dd) in UZ_ISLAMIC_HOLIDAYS.get(y, {}).items():
                if date(y, m, dd) >= today:
                    out.append((key, date(y, m, dd)))
        return sorted(out, key=lambda kv: kv[1])
    out = {}  # 文案键 -> 最近的日期（同键只保留第一个）
    # 1) 公历固定日期节日：今年已过则取明年
    for key, (m, dd) in {"h_newyear": (1, 1), "h_labour": (5, 1),
                         "h_national": (10, 1)}.items():
        cand = date(today.year, m, dd)
        if cand < today:
            y = today.year + 1
            cand = date(y, m, dd)
        out[key] = cand
    # 2) 农历节日 + 清明节气：向未来扫 400 天，逐日查农历月/日与节气名
    try:
        import cnlunar
        d = today
        for _ in range(400):
            try:
                lu = cnlunar.Lunar(datetime(d.year, d.month, d.day), godType="8char")
                for key, (lm, ld) in _LUNAR_MATCH.items():
                    if key not in out and lu.lunarMonth == lm and lu.lunarDay == ld:
                        out[key] = d
                if "h_qingming" not in out and lu.todaySolarTerms == "清明":
                    out["h_qingming"] = d
            except Exception:  # noqa: BLE001  单日失败不影响后续
                pass
            if len(out) >= 7:
                break  # 七个节日都找到了，提前结束扫描
            d += timedelta(days=1)
    except Exception:  # noqa: BLE001  未装 cnlunar：只提供公历节日
        pass
    # 英文界面：剔除春节/清明/端午/中秋，倒计时下拉里也不出现
    return [kv for kv in sorted(out.items(), key=lambda kv: kv[1])
            if not hide_holiday(kv[0])]


def mix_hex(hex_color: str, white_ratio: float = 0.85) -> str:
    """把颜色向白色混合（white_ratio 为白色占比），用于生成主题色的浅色底"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda v: round(v + (255 - v) * white_ratio)  # noqa: E731
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def _clip_utf8(text: str, limit: int = 4000) -> str:
    """按 UTF-8 字节数安全截断。企业微信 markdown 上限 4096 字节，
    中文每字占 3 字节，按字符数切片（text[:4000]）最长可达 1.2 万字节，会被拒收。"""
    data = text.encode("utf-8")
    return text if len(data) <= limit else data[:limit].decode("utf-8", "ignore")


def wecom_push(webhook: str, content: str):
    """向企业微信群机器人发送 markdown 消息，返回 (是否成功, 错误信息)"""
    if not webhook:
        return False, "Webhook 地址为空"
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": _clip_utf8(content)}}
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("errcode") == 0:
                return True, ""
            return False, f"errcode={data.get('errcode')} {data.get('errmsg', '')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


_wecom_token_cache = {"token": "", "expire_at": 0.0}


def wecom_app_push(corpid: str, agentid, secret: str, content: str,
                   touser: str = "@all"):
    """通过企业微信自建应用发送应用消息（发到个人企业微信），返回 (是否成功, 错误信息)"""
    if not (corpid and agentid and secret):
        return False, "应用参数不完整（CorpID / AgentID / Secret）"
    now = time.time()
    token = _wecom_token_cache["token"]
    try:
        if not token or now >= _wecom_token_cache["expire_at"]:
            url = ("https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid="
                   + urllib.parse.quote(corpid)
                   + "&corpsecret=" + urllib.parse.quote(secret))
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("errcode"):
                return False, f"获取 access_token 失败：{data.get('errmsg')}"
            token = data["access_token"]
            _wecom_token_cache.update(
                token=token, expire_at=now + int(data.get("expires_in", 7200)) - 300)
        payload = json.dumps({
            "touser": touser or "@all",
            "msgtype": "markdown",
            "agentid": int(agentid),
            "markdown": {"content": _clip_utf8(content)},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token="
            + urllib.parse.quote(token),
            data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errcode") == 0:
            return True, ""
        _wecom_token_cache.update(token="", expire_at=0.0)  # 失败清缓存，下次重取
        return False, f"errcode={data.get('errcode')} {data.get('errmsg', '')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


_lunar_cache = {}


def _bind_click_tree(widget, handler):
    """把点击回调绑到控件**及其所有后代**上。

    Tkinter 没有事件冒泡：鼠标点在某个子控件上，事件只发给那个子控件，
    不会自动向上传递给父控件。所以只给容器绑定会导致「点到里面的文字没反应」——
    典型症状就是日历格子里有任务标题时点不动、空格子反而能切换。"""
    widget.bind("<Button-1>", handler)
    for child in widget.winfo_children():
        _bind_click_tree(child, handler)


def lunar_info(d: date):
    """返回 (农历显示文本, 节气名或None)。初一显示月名（如「八月」），其余显示日名；
    节气仅在当天是节气日时返回名称。未安装 cnlunar 时返回 ('', None)。
    英文界面一律返回 ('', None)：农历数字对英文用户没有意义，用户明确要求
    英文模式下不显示农历；节气也没有通用英文译名。在数据源头关掉，
    任何调用路径都不会再把农历带进英文界面（渲染层另有 show_lunar_eff 拦截）。"""
    if LANG == "en":
        return "", None
    key = (d.isoformat(), LANG)     # 结果随语言变化，缓存键必须带语言，否则切语言后拿到旧值
    if key not in _lunar_cache:
        text, term = "", None
        try:
            import cnlunar
            lu = cnlunar.Lunar(datetime(d.year, d.month, d.day), godType="8char")
            month_cn = re.sub(r"[大小]$", "", lu.lunarMonthCn)  # 「八月小」->「八月」
            text = month_cn if lu.lunarDayCn == "初一" else lu.lunarDayCn
            term = lu.todaySolarTerms if lu.todaySolarTerms not in ("无", "") else None
        except Exception:  # noqa: BLE001
            pass
        _lunar_cache[key] = (text, term)
    return _lunar_cache[key]

# 导入/导出使用的字段（CSV 表头与 JSON 键名）
EXPORT_COLUMNS = ["task_date", "title", "done", "repeat", "remind_time",
                  "important", "pinned"]


def parse_import_file(path: str):
    """解析导入文件（JSON 备份或 CSV 表格），返回清洗后的任务元组列表
    (task_date, title, done, repeat, remind_time)，无效行自动跳过"""
    path = str(path)
    items = []
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                items.append({k: (row.get(k) or "").strip() for k in EXPORT_COLUMNS})
    else:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        raw = data.get("tasks", []) if isinstance(data, dict) else data
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    items.append({k: str(row.get(k) or "").strip()
                                  for k in EXPORT_COLUMNS})

    valid_time = re.compile(r"([01]?\d|2[0-3]):[0-5]\d")
    out = []
    for it in items:
        try:
            d = date.fromisoformat(it["task_date"]).isoformat()
        except (KeyError, ValueError):
            continue
        if not it.get("title"):
            continue
        rep = it.get("repeat") if it.get("repeat") in ("day", "week", "month") else "day"
        rt = it.get("remind_time") if valid_time.fullmatch(it.get("remind_time") or "") else ""
        done = 1 if it.get("done") in ("1", 1, "true", "True") else 0
        imp = 1 if it.get("important") in ("1", 1, "true", "True") else 0
        pin = 1 if it.get("pinned") in ("1", 1, "true", "True") else 0
        out.append((d, it["title"], done, rep, rt, imp, pin))
    return out


def group_series_rows(items):
    """导入行归并系列：周/月任务按（标题, 类型, 提醒时间）归到同一条系列。
    返回 [(d, title, done, rep, rtime, imp, pin, sid), ...]。

    导出的 JSON/CSV 不携带系列号，备份里同一条系列的各期若在导入时各自
    新建系列，expand_series() 补期后会把一份备份放大成成片的重复任务；
    靠这三样把各期归队后，补期只会补缺的日期。"""
    out, sids = [], {}
    for d, title, done, rep, rtime, imp, pin in items:
        sid = ""
        if rep in ("week", "month"):
            key = (title, rep, rtime)
            sid = sids.get(key)
            if not sid:
                sid = sids[key] = new_series_id()
        out.append((d, title, done, rep, rtime, imp, pin, sid))
    return out


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_date  TEXT NOT NULL,           -- YYYY-MM-DD
            title      TEXT NOT NULL,
            done       INTEGER DEFAULT 0,
            repeat     TEXT DEFAULT 'day',      -- day / week / month
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(task_date)")
    try:  # 旧库升级：补 repeat 列，历史任务默认按日任务顺延
        conn.execute("ALTER TABLE tasks ADD COLUMN repeat TEXT DEFAULT 'day'")
    except sqlite3.OperationalError:
        pass
    try:  # 旧库升级：补提醒字段
        conn.execute("ALTER TABLE tasks ADD COLUMN remind_time TEXT DEFAULT ''")
        conn.execute("ALTER TABLE tasks ADD COLUMN last_remind TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:  # 旧库升级：重要 / 置顶标记
        conn.execute("ALTER TABLE tasks ADD COLUMN important INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE tasks ADD COLUMN pinned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:  # 旧库升级：周期系列号（周/月任务自动生成的各期共用同一个 id）
        conn.execute("ALTER TABLE tasks ADD COLUMN series_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_series ON tasks(series_id)")
    # 周期任务「墓碑」：被用户明确删除/清理掉的发生日记在这里，
    # expand_series() 补期时跳过——否则删掉最后一期或「清理已完成」后，
    # 下次补期会把它们当作缺期重新生成，任务「复活」
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS series_skips (
            series_id TEXT NOT NULL,
            task_date TEXT NOT NULL,
            PRIMARY KEY (series_id, task_date)
        )
        """
    )
    try:  # 旧库升级：周任务间隔（每 N 周），默认每周
        conn.execute("ALTER TABLE tasks ADD COLUMN interval INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    # v1.7.2 防重复三件套之一：同系列同日期唯一约束。
    # 先清掉历史脏数据（同一 series_id 同一天出现多条时只留最早一条），
    # 再建部分唯一索引兜底——从根上杜绝「同一天同一条任务出现数次」
    conn.execute(
        "DELETE FROM tasks WHERE series_id != '' AND id NOT IN ("
        "  SELECT MIN(id) FROM tasks WHERE series_id != '' "
        "  GROUP BY series_id, task_date)")
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_series_date "
            "ON tasks(series_id, task_date) WHERE series_id != ''")
    except sqlite3.OperationalError:
        pass  # 极老 SQLite 不支持部分索引：跳过，靠应用层检查兜底
    # 倒数日 / 纪念日：kind = annual 每年纪念日（可按农历）/ countdown 单次倒数
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            event_date TEXT NOT NULL,
            kind       TEXT DEFAULT 'countdown',
            lunar      INTEGER DEFAULT 0
        )
        """
    )
    # 键值表：备份/订阅时间戳等轻量状态
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 自动备份 / 键值状态 / 倒数日纪念日 / ICS 订阅
# ---------------------------------------------------------------------------
BACKUP_KEEP = 10        # data/backup/ 里保留的最近备份份数
BACKUP_INTERVAL = 86_400  # 备份最小间隔：24 小时


def auto_backup(conn, force: bool = False) -> str:
    """每日自动备份：把当前库完整备份到 data/backup/calendar-时间戳.db，
    24 小时内已备份过则跳过（force=True 强制备份），只保留最近 BACKUP_KEEP 份。
    用 SQLite 的 backup API 保证与打开中的连接一致；任何失败都不影响主流程。
    返回备份文件路径，跳过/失败返回空串。"""
    try:
        bdir = DB_PATH.parent / "backup"
        bdir.mkdir(parents=True, exist_ok=True)
        backups = sorted(bdir.glob("calendar-*.db"))
        if not force and backups and \
                time.time() - backups[-1].stat().st_mtime < BACKUP_INTERVAL:
            return ""
        dest = bdir / f"calendar-{datetime.now():%Y%m%d-%H%M%S}.db"
        dst = sqlite3.connect(dest)
        try:
            conn.backup(dst)
        finally:
            dst.close()
        for p in sorted(bdir.glob("calendar-*.db"))[:-BACKUP_KEEP]:
            try:
                p.unlink()
            except OSError:
                pass
        return str(dest)
    except Exception:  # noqa: BLE001  备份失败绝不影响主流程
        return ""


def kv_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def kv_set(conn, key: str, value: str):
    conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                 (key, str(value)))
    conn.commit()


def human_span(minutes: int) -> str:
    """分钟数转人话时长：45 -> 「45 分钟」，90 -> 「1 小时」，2880 -> 「2 天」"""
    if minutes < 60:
        return T("span_min", n=minutes)
    if minutes < 1440:
        return T("span_hour", n=minutes // 60)
    return T("span_day", n=minutes // 1440)


# ---------------- 倒数日 / 纪念日 ----------------

def db_events(conn):
    return conn.execute(
        "SELECT id, name, event_date, kind, lunar FROM events "
        "ORDER BY event_date, id").fetchall()


def add_event(conn, name: str, dstr: str, kind: str, lunar: bool):
    conn.execute(
        "INSERT INTO events (name, event_date, kind, lunar) VALUES (?, ?, ?, ?)",
        (name, dstr, kind, int(bool(lunar))))
    conn.commit()


def del_event(conn, eid: int):
    conn.execute("DELETE FROM events WHERE id = ?", (eid,))
    conn.commit()


def _lunar_md(d0: date):
    """d0 对应的农历 (月, 日)（闰月返回 None，避免换算歧义）；取不到也返回 None"""
    try:
        import cnlunar
        lu = cnlunar.Lunar(datetime(d0.year, d0.month, d0.day), godType="8char")
        if "闰" in (lu.lunarMonthCn or ""):
            return None
        return lu.lunarMonth, lu.lunarDay
    except Exception:  # noqa: BLE001
        return None


_lunar_annual_cache = {}


def lunar_annual_date(d0: date, year: int):
    """农历纪念日：d0 当天的农历月/日，在公历 year 年对应的日期（找不到返回 None）。
    逐日扫该年农历直到匹配，结果按 (d0, year) 缓存。"""
    key = (d0.isoformat(), year)
    if key in _lunar_annual_cache:
        return _lunar_annual_cache[key]
    md = _lunar_md(d0)
    got = None
    if md:
        try:
            import cnlunar
            d = date(year, 1, 1)
            while d <= date(year, 12, 31):
                try:
                    lu = cnlunar.Lunar(datetime(d.year, d.month, d.day),
                                       godType="8char")
                    if ("闰" not in (lu.lunarMonthCn or "")
                            and lu.lunarMonth == md[0] and lu.lunarDay == md[1]):
                        got = d
                        break
                except Exception:  # noqa: BLE001  单日失败不影响后续
                    pass
                d += timedelta(days=1)
        except Exception:  # noqa: BLE001
            pass
    _lunar_annual_cache[key] = got
    return got


def event_marks(conn, year: int, month: int) -> dict:
    """该月月历格子的生日/纪念日 🎂 与倒数日 ⏳ 角标：{day: emoji}"""
    marks = {}
    for _eid, _name, dstr, kind, lunar in db_events(conn):
        try:
            d0 = date.fromisoformat(dstr)
        except ValueError:
            continue
        if kind == "annual":
            if lunar:
                target = lunar_annual_date(d0, year)
            elif year < d0.year:
                target = None  # 纪念日还没开始：不标
            else:
                try:
                    target = d0.replace(year=year)
                except ValueError:      # 2/29 -> 平年无对应日，跳过
                    target = None
            if target and target.month == month and target.day not in marks:
                marks[target.day] = "🎂"
        elif d0.year == year and d0.month == month and d0.day not in marks:
            marks[d0.day] = "⏳"
    return marks


# ---------------- ICS 日历订阅 ----------------

def parse_ics_events(text: str):
    """极简 iCal 解析：返回 [(date, summary)]。支持 DTSTART;VALUE=DATE:YYYYMMDD
    与 DTSTART:YYYYMMDDTHHMMSS(Z)，处理以空格开头的折行。"""
    lines = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]        # RFC5545 折行：续行以空格/Tab 开头
        else:
            lines.append(raw)
    out, cur_date, cur_sum = [], None, ""
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            cur_date, cur_sum = None, ""
        elif ln.startswith("END:VEVENT"):
            if cur_date and cur_sum:
                out.append((cur_date, cur_sum))
            cur_date, cur_sum = None, ""
        elif ln.startswith("DTSTART"):
            val = ln.split(":", 1)[-1].strip()
            m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
            if m:
                try:
                    cur_date = date(int(m.group(1)), int(m.group(2)),
                                    int(m.group(3)))
                except ValueError:
                    cur_date = None
        elif ln.startswith("SUMMARY"):
            cur_sum = ln.split(":", 1)[-1].strip()
    return out


def ics_sync(conn, url: str):
    """拉取 ICS 订阅，把未来 6 个月内的事件按日期建为任务（标题加 📅 前缀），
    按（日期+标题）去重。返回 (新增, 跳过)。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", "ignore")
    today = date.today()
    horizon = today + timedelta(days=180)
    existing = {(d, t) for d, t in conn.execute("SELECT task_date, title FROM tasks")}
    added = skipped = 0
    for d, summary in parse_ics_events(text):
        if not (today <= d <= horizon):
            continue
        title = f"📅 {summary[:50]}"
        if (d.isoformat(), title) in existing:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO tasks (task_date, title, repeat, remind_time) "
            "VALUES (?, ?, 'day', '')",
            (d.isoformat(), title))
        existing.add((d.isoformat(), title))
        added += 1
    conn.commit()
    return added, skipped


# ---------------------------------------------------------------------------
# 周期系列（周任务 / 月任务自动生成后续各期）
# ---------------------------------------------------------------------------
# 每条周/月任务新增时一次性生成未来若干期，各自是独立的一行（各自可勾选完成、
# 各自到点提醒），靠 series_id 串成一条系列。提前生成的窗口：
SERIES_HORIZON_DAYS = {"week": 70, "month": 400, "workday": 70}   # 周任务约 10 期 / 月任务约 13 期 / 工作日约 10 周
SERIES_MAX_STEP = 300                              # 单次生成期数上限（防死循环）


def new_series_id() -> str:
    """生成一个新的系列号（周/月任务用），同系列各期共享"""
    return "s" + uuid.uuid4().hex[:12]


def is_workday_d(d: date) -> bool:
    """按当前国家规则判断是否工作日（法定调休的周末补班也算上班）"""
    return not day_marks(d)[1]


def next_workday(d: date) -> date:
    """d 当天是工作日就原样返回，否则向后找到下一个工作日"""
    nd = d
    while not is_workday_d(nd):
        nd += timedelta(days=1)
    return nd


def series_next(d: date, rep: str, mday0: int, interval: int = 1) -> date:
    """按周期规则给出下一期日期：周任务每 interval 周 +7*interval 天；
    月任务取下月同一天（不足则截断到月末）；工作日任务取下一个工作日
    （按当前国家规则，法定调休补班的周末也算上班，节假日自动跳过）"""
    if rep == "week":
        return d + timedelta(days=7 * max(1, interval))
    if rep == "workday":
        nd = d + timedelta(days=1)
        while not is_workday_d(nd):
            nd += timedelta(days=1)
        return nd
    y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
    return date(y, m, min(mday0, calendar.monthrange(y, m)[1]))


def series_horizon_end(rep: str, today: date) -> date:
    """该类型的生成窗口截止日（今天 + 预设天数）"""
    return today + timedelta(days=SERIES_HORIZON_DAYS.get(rep, 0))


def series_dates(first: date, rep: str, end: date, interval: int = 1) -> list:
    """列出从 first 起、按周期规则推进、不晚于 end 的所有期次日期（含 first）。
    工作日任务的首期若不是工作日（周末/节假日），自动顺延到下一个工作日，
    保证系列里的每一期都是工作日"""
    if rep not in SERIES_HORIZON_DAYS:
        return [first]
    if rep == "workday" and not is_workday_d(first):
        first = next_workday(first)
    out = [first]
    d, mday0 = first, first.day
    while len(out) < SERIES_MAX_STEP:
        d = series_next(d, rep, mday0, interval)
        if d > end:
            break
        out.append(d)
    return out


def series_count(conn, sid: str) -> int:
    """该系列当前共有几期"""
    if not sid:
        return 0
    return conn.execute("SELECT COUNT(*) FROM tasks WHERE series_id = ?",
                        (sid,)).fetchone()[0]


def adopt_legacy_series(conn) -> int:
    """把没有系列号的旧周/月任务收编成系列，让它们同样按周/月自动生成
    后续各期——否则老任务永远只有一条。收编只补 series_id、不动任务内容
    与日期；随后 expand_series() 会从各任务现有日期继续往后排。幂等。

    v1.7.2 修复：以前逐行各编一条系列——库里有两条同名旧周任务（比如当年
    手快加了两次）时会被编成两条并行系列，之后每个同星期几都会出现两条
    同名任务（用户报告的「同一个周一出现数次」就是这么来的）。现在按
    （标题, 类型, 星期几/几号, 间隔）归并：同 key 的旧行共用一条系列。"""
    rows = conn.execute(
        "SELECT id, title, task_date, repeat, interval FROM tasks "
        "WHERE (series_id IS NULL OR series_id = '') "
        "AND repeat IN ('week', 'month', 'workday')"
    ).fetchall()
    groups: dict = {}
    for tid, title, dstr, rep, interval in rows:
        try:
            d = date.fromisoformat(dstr)
        except ValueError:
            d = None
        if d is None:
            key = (title, rep, -1, interval or 1)
        elif rep == "week":
            key = (title, rep, d.weekday(), interval or 1)
        elif rep == "month":
            key = (title, rep, d.day, interval or 1)
        else:
            key = (title, rep, -1, 1)
        groups.setdefault(key, []).append(tid)
    adopted = 0
    for tids in groups.values():
        sid = new_series_id()
        for tid in tids:
            conn.execute("UPDATE tasks SET series_id = ? WHERE id = ?",
                         (sid, tid))
        adopted += 1
    if adopted:
        conn.commit()
    return len(rows)


def mark_series_skips(conn, ids):
    """把将要删除的周期任务发生日记入墓碑（series_skips），防止补期时复活。
    只记带系列号的周/月任务；日任务和散装任务删了就是删了。"""
    for tid in ids:
        row = conn.execute(
            "SELECT task_date, series_id FROM tasks WHERE id = ? "
            "AND repeat IN ('week', 'month', 'workday') AND series_id != ''",
            (tid,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO series_skips (series_id, task_date) "
                "VALUES (?, ?)", (row[1], row[0]))


def expand_series(conn, today: date) -> int:
    """给每个周期系列补齐未来的期次（启动 / 跨天 / 改系列后调用）。

    做法：取该系列已有的最后一期，按星期几 / 每月几号继续往后推，
    一直补到窗口截止日（周任务约 10 期、月任务约 13 期）。标题 / 提醒 /
    重要 / 置顶沿用系列首期的设置；同一天已有该系列的任务就跳过，
    不会重复插入。返回新增期数。

    收编老任务（adopt_legacy_series）后，锚点日期可能很早：早于本周
    （周任务）/ 本月（月任务）的历史期次**不回补**，避免一次性涌出
    一大堆「逾期」行；当前及未来各期照常生成。"""
    adopt_legacy_series(conn)
    rows = conn.execute(
        "SELECT series_id, repeat, MIN(task_date), MAX(task_date) FROM tasks "
        "WHERE series_id != '' AND repeat IN ('week', 'month', 'workday') "
        "GROUP BY series_id, repeat"
    ).fetchall()
    added = 0
    for sid, rep, first, last in rows:
        try:
            d0, d = date.fromisoformat(first), date.fromisoformat(last)
        except (ValueError, TypeError):
            continue
        tmpl = conn.execute(
            "SELECT title, remind_time, important, pinned, interval FROM tasks "
            "WHERE series_id = ? ORDER BY task_date, id LIMIT 1", (sid,)).fetchone()
        if not tmpl:
            continue
        title, rtime, imp, pin, interval = tmpl
        interval = max(1, int(interval or 1))
        end = series_horizon_end(rep, today)
        # 早于本周（周/工作日任务）/ 本月（月任务）的历史期次不补建：收编老任务时
        # 锚点日期可能很早，避免一次性涌出一大堆「逾期」行
        cutoff = (today - timedelta(days=today.weekday())) if rep in ("week", "workday") \
            else date(today.year, today.month, 1)
        skips = {r[0] for r in conn.execute(
            "SELECT task_date FROM series_skips WHERE series_id = ?", (sid,))}
        batch, step, seen = [], 0, set()
        while d < end and step < SERIES_MAX_STEP:
            d = series_next(d, rep, d0.day, interval)
            step += 1
            if d > end:
                break
            if d < cutoff or d.isoformat() in skips:
                continue
            if d.isoformat() in seen:      # 批内去重（防御：series_next 应单调递增）
                continue
            exists = conn.execute(
                "SELECT 1 FROM tasks WHERE series_id = ? AND task_date = ? LIMIT 1",
                (sid, d.isoformat())).fetchone()
            if exists:
                continue
            seen.add(d.isoformat())
            batch.append((d.isoformat(), title, rep, rtime or "", imp or 0,
                          pin or 0, sid, interval))
        if batch:
            conn.executemany(
                "INSERT INTO tasks (task_date, title, repeat, remind_time, "
                "important, pinned, series_id, interval) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                batch)
            added += len(batch)
    if added:
        conn.commit()
    return added


def roll_pending_tasks(conn, today: date) -> int:
    """顺延未完成的周期任务（启动时与跨天时调用）：
    日任务  —— 错过当天 -> 顺延到今天；
    周任务  —— 所在周已结束（下周一及以后才打开）-> 顺延到本周同一天；
    月任务  —— 所在月已结束 -> 顺延到本月同一天（不足按月末截断，如 1/31 -> 2/28）。
    返回顺延的任务数。

    注意：带 series_id 的周/月任务**不参与顺延**。它们已经按系列生成了未来各期，
    再顺延会把「上周没做的周报」搬到本周、和本周那一期撞在一起；留着显示为
    「逾期」更符合清单语义，后续各期照常按周/月生成。"""
    rows = conn.execute(
        "SELECT id, task_date, repeat FROM tasks "
        "WHERE done = 0 AND (series_id IS NULL OR series_id = '')"
    ).fetchall()
    updates = []
    for tid, dstr, rep in rows:
        try:
            d = date.fromisoformat(dstr)
        except ValueError:
            continue  # 脏数据行跳过，别让一条坏记录卡死启动/跨天顺延
        nd = d
        if rep in ("day", "workday"):
            while nd < today:
                nd += timedelta(days=1)
            if rep == "workday" and not is_workday_d(nd):
                nd = next_workday(nd)   # 今天是周末/节假日：顺延到下一个工作日
        elif rep == "week":
            week_start = today - timedelta(days=today.weekday())
            while nd < week_start:
                nd += timedelta(days=7)
        elif rep == "month":
            while (nd.year, nd.month) < (today.year, today.month):
                y, m = (nd.year, nd.month + 1) if nd.month < 12 else (nd.year + 1, 1)
                nd = date(y, m, min(nd.day, calendar.monthrange(y, m)[1]))
        if nd != d:
            updates.append((nd.isoformat(), tid))
    if updates:
        conn.executemany("UPDATE tasks SET task_date = ? WHERE id = ?", updates)
        conn.commit()
    return len(updates)


def db_tasks_on(conn, day: str):
    return conn.execute(
        "SELECT id, title, done, repeat, remind_time, important, pinned FROM tasks "
        "WHERE task_date = ? ORDER BY pinned DESC, done, id",
        (day,),
    ).fetchall()


def db_tasks_all(conn):
    return conn.execute(
        "SELECT id, task_date, title, done, repeat, remind_time, important, pinned "
        "FROM tasks ORDER BY task_date, pinned DESC, done, id"
    ).fetchall()


def db_counts_by_date(conn, first_day: str, last_day: str):
    rows = conn.execute(
        "SELECT task_date, COUNT(*) FROM tasks "
        "WHERE task_date BETWEEN ? AND ? GROUP BY task_date",
        (first_day, last_day),
    ).fetchall()
    return {d: n or 0 for d, n in rows}


# ---------------------------------------------------------------------------
# 设置与开机自启
# ---------------------------------------------------------------------------
def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(cfg: dict):
    try:
        SETTINGS_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        messagebox.showwarning(T("warn_title"), T("save_settings_failed", e=e))


def load_changelog() -> str:
    """读取修订日志文本：先找程序同目录，再找打包进 exe 的内部目录；都没有返回空串。

    有了它，改完代码把说明写进 CHANGELOG.md，之后任何时间点开
    「设置 → 📜 修订日志」都能回看改了什么，不必翻聊天记录。"""
    cands = [BASE_DIR / CHANGELOG_FILE]
    if getattr(sys, "_MEIPASS", ""):     # onefile 打包后数据解压在这个临时目录
        cands.append(Path(sys._MEIPASS) / CHANGELOG_FILE)  # noqa: SLF001
    for p in cands:
        try:
            if p.exists():
                return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def autostart_command() -> str:
    if getattr(sys, "frozen", False):  # 打包成 exe 后开机自启就是启动 exe 本身
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":  # 开机启动优先用无控制台的 pythonw
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    return f'"{exe}" "{Path(__file__).resolve()}"'


def is_autostart_on() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
            winreg.QueryValueEx(k, RUN_VALUE_NAME)
            return True
    except OSError:
        return False


def set_autostart(enable: bool):
    if winreg is None:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as k:
            if enable:
                winreg.SetValueEx(
                    k, RUN_VALUE_NAME, 0, winreg.REG_SZ, autostart_command()
                )
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError as e:
        messagebox.showwarning(T("warn_title"), T("autostart_failed", e=e))


# ---------------------------------------------------------------------------
# 可滚动容器
# ---------------------------------------------------------------------------
class ScrollFrame(tk.Frame):
    """带滚动条和鼠标滚轮的容器，内容放进 self.inner"""

    def __init__(self, master, bg="white"):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", tags="inner")
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure("inner", width=e.width)
        )
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.inner.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.inner.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")


class DateSpin(tk.Frame):
    """年/月/日三联上下选择框（v1.8.5）：替代手敲 YYYY-MM-DD 文本输入。
    天数随年月联动收紧（2 月闰年 29、大小月 30/31）；get_date() 返回 date，
    输入残缺/越界时返回 None（调用方据此弹原有的格式警告）。"""

    def __init__(self, master, font, on_change=None):
        super().__init__(master)
        self._on_change = on_change
        self._lock = False
        self.sb_y = tk.Spinbox(self, from_=1970, to=2999, width=5,
                               justify="center", font=font,
                               command=self._sync_days)
        self.sb_m = tk.Spinbox(self, from_=1, to=12, width=3,
                               justify="center", font=font,
                               command=self._sync_days)
        self.sb_d = tk.Spinbox(self, from_=1, to=31, width=3,
                               justify="center", font=font)
        self.sb_y.pack(side="left")
        tk.Label(self, text="-", font=font).pack(side="left")
        self.sb_m.pack(side="left")
        tk.Label(self, text="-", font=font).pack(side="left")
        self.sb_d.pack(side="left")
        for sb in (self.sb_y, self.sb_m, self.sb_d):
            sb.bind("<KeyRelease>", self._sync_days)

    def _ymd(self):
        """读三个框的整数（手输可能是残缺文本），残缺返回 None"""
        try:
            return int(self.sb_y.get()), int(self.sb_m.get()), int(self.sb_d.get())
        except ValueError:
            return None

    @staticmethod
    def _put(sb, val):
        """经典 tk.Spinbox 没有 .set()：走 delete/insert 写值"""
        sb.delete(0, "end")
        sb.insert(0, val)

    def _sync_days(self, *_):
        """年/月变化（点箭头或手输）后收紧天数上限，越界日期就近回落"""
        if self._lock:
            return
        self._lock = True
        try:
            v = self._ymd()
            y, m = ((v[0], v[1]) if v and v[0] > 0 and 1 <= v[1] <= 12
                    else (date.today().year, date.today().month))
            maxd = calendar.monthrange(y, m)[1]
            self.sb_d.config(to=maxd)
            cur = self._ymd()
            if cur and cur[2] > maxd:
                self._put(self.sb_d, str(maxd))
        finally:
            self._lock = False
        if self._on_change:
            try:
                self._on_change()
            except Exception:  # noqa: BLE001
                pass

    def get_date(self):
        """当前日期；残缺或非法（如 2 月 30）返回 None"""
        v = self._ymd()
        if not v:
            return None
        try:
            return date(*v)
        except ValueError:
            return None

    def set_date(self, d):
        self._lock = True
        try:
            self._put(self.sb_y, f"{d.year:04d}")
            self._put(self.sb_m, str(d.month))
            self.sb_d.config(to=calendar.monthrange(d.year, d.month)[1])
            self._put(self.sb_d, str(d.day))
        finally:
            self._lock = False


# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------
class CalendarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.tray = None                   # 先占位：_build_ui 里 render_title 会引用
        self.title(T("app_title"))
        self.geometry("1000x680")
        self.minsize(880, 600)
        self.resizable(False, False)  # 嵌桌面：不允许缩放/最大化
        self.conn = init_db()
        self.today = date.today()
        roll_pending_tasks(self.conn, self.today)
        expand_series(self.conn, self.today)   # 周/月任务：补齐未来各期
        self.view_year, self.view_month = self.today.year, self.today.month
        self.sel_date = self.today

        cfg = load_settings()
        # 界面语言（zh/en）：全局 LANG 决定 T() 取词，切换后重启生效；
        # 国家（cn/uz）决定月历工作日/休息日规则（day_marks 取哪国数据）
        global LANG, COUNTRY
        self.lang = cfg.get("language", "zh")
        if self.lang not in STR:
            self.lang = "zh"
        LANG = self.lang
        self.country = cfg.get("country", "cn")
        if self.country not in ("cn", "uz"):
            self.country = "cn"
        COUNTRY = self.country
        self.remind_early = int(cfg.get("remind_early", 0) or 0)
        if self.remind_early not in (0, 5, 10, 30, 60, 1440):
            self.remind_early = 0
        self.auto_backup = bool(cfg.get("auto_backup", True))
        self.ics_url = str(cfg.get("ics_url", "") or "")
        fc = cfg.get("cal_font", {})
        ft = cfg.get("task_font", {})
        self.cal_family = fc.get("family", "Microsoft YaHei UI")
        self.cal_size = max(8, min(22, int(fc.get("size", 10))))
        self.task_family = ft.get("family", "Microsoft YaHei UI")
        self.task_size = max(8, min(22, int(ft.get("size", 10))))
        self.alpha = min(1.0, max(0.5, float(cfg.get("alpha", 1.0))))
        self.topmost = bool(cfg.get("topmost", False))
        self.show_holiday = bool(cfg.get("show_holiday", True))
        self.show_weekno = bool(cfg.get("show_weekno", True))
        self.show_lunar = bool(cfg.get("show_lunar", True))
        self.show_terms = bool(cfg.get("show_terms", True))
        self.show_rest = bool(cfg.get("show_rest", True))
        self.week_start = cfg.get("week_start", "mon")
        if self.week_start not in ("mon", "sun"):
            self.week_start = "mon"
        self.cal_fg = cfg.get("cal_fg", "#1f2937")
        self.task_fg = cfg.get("task_fg", "#111827")   # 内容文字颜色，默认近黑（原效果）
        self.accent = cfg.get("accent", "#2563eb")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.cal_fg or ""):
            self.cal_fg = "#1f2937"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.task_fg or ""):
            self.task_fg = "#111827"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.accent or ""):
            self.accent = "#2563eb"
        self.wecom_webhook = str(cfg.get("wecom_webhook", "") or "")
        self.wecom_push = bool(cfg.get("wecom_push", True))
        self.wecom_corp_id = str(cfg.get("wecom_corp_id", "") or "")
        self.wecom_agent_id = str(cfg.get("wecom_agent_id", "") or "")
        self.wecom_corp_secret = str(cfg.get("wecom_corp_secret", "") or "")
        self.embedded = bool(cfg.get("embedded", True))  # 嵌桌面模式：无标题栏、不可拖动缩放
        self.desktop_bottom = bool(cfg.get("desktop_bottom", True))  # 固定时贴桌面底层（仅壁纸之上）
        self.bg_color = cfg.get("bg_color", "#f0f0f0")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.bg_color or ""):
            self.bg_color = "#f0f0f0"
        self.bg_image_path = str(cfg.get("bg_image_path", "") or "")
        if cfg.get("geometry"):
            self.geometry(cfg["geometry"])
        self.attributes("-topmost", self.topmost)
        self._geom_job = None
        self.bind("<Configure>", self._on_configure)
        self._split_tried = False  # 本次固定会话是否已尝试让系统分离壁纸层（0x052C 只发一次）
        self._bottom_job = None    # 周期校验/复位桌面底层的定时器
        self.bind("<Activate>", self._on_win_activate)
        # 输入保护（打字模式）：半透明窗口（WS_EX_LAYERED）下中文 IME 会失效；
        # 贴桌面模式常驻的 WS_EX_NOACTIVATE 又让窗口收不到键盘输入。
        # 焦点进入输入框时两者临时摘掉（见 _on_focus_in）；_ime_plain 记录临时状态
        self._ime_plain = False
        self.bind_all("<FocusIn>", self._on_focus_in, "+")
        self.bind_all("<FocusOut>", self._on_focus_out, "+")
        self._set_alpha(self.alpha)   # 用统一入口，避免无谓地给窗口加分层样式
        if self.auto_backup:
            auto_backup(self.conn)    # 每日自动备份（24 小时内已备份则跳过）

        self._build_fonts()
        ttk.Style(self).configure("TNotebook.Tab", padding=(18, 6))

        self._build_ui()  # 顶部签名条 + 语言切换 + 三个页面（抽成方法，便于切语言时整体重建）
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_idletasks()
        # 屏幕外救援：历史 geometry 可能指向已断开的副屏，或多屏改布局后
        # 窗口半截在桌面外（顶部被截最常见）——启动时整体钳制回可见桌面
        # （v1.7.1 救全出屏，v1.7.3 救部分出屏）
        _clamp_into_screen(self)
        # 托盘：窗口最小化时缩进通知区而非留在任务栏（见 _on_unmap）。
        # TrayIcon 本身不显示图标，只有真正最小化才出现；左键恢复、右键快捷菜单
        if TrayIcon is not None:
            self.tray = TrayIcon(self, BASE_DIR / "app.ico",
                                 self._tray_menu_items, self.show_from_tray,
                                 self._tray_menu_action,
                                 on_display_change=self._on_display_changed)
            self.bind("<Unmap>", self._on_unmap)
            self.tray.show(self._tray_tip())   # v1.8.2：启动即上托盘，不必等最小化
        else:
            self.tray = None
        self.after(60_000, self._tick)  # 每分钟检查是否跨天，跨天自动顺延
        self.after(2_000, self.check_reminders)  # 启动后开始提醒循环
        self.after(15_000, self._ics_auto_sync)  # 稍后静默同步一次 ICS 订阅

    # ---------------- 系统托盘 ----------------
    def _on_unmap(self, event):
        """最小化（iconic）时把图标加进托盘并隐藏窗口，等效「缩到托盘」。
        withdraw 本身也会触发 Unmap，用 state 检查挡住，避免自触发循环。"""
        if event.widget is not self or not self.tray:
            return
        if self.state() != "iconic" or not self.tray.show(self._tray_tip()):
            return
        self.withdraw()

    def show_from_tray(self):
        """从托盘恢复主窗口（托盘左键 / 菜单「显示主窗口」/ 第二实例拉起）。
        窗口本来就可见时只抢前台、**不动托盘图标**——图标现在常驻（v1.8.2 起
        启动即显示），只有窗口真的藏起来过才在恢复时移除图标。"""
        if self.state() != "normal":
            if self.tray:
                self.tray.show(self._tray_tip())   # 防御：图标丢了先补回
            self.wm_state("normal")
            self.deiconify()
            if self.state() != "normal":
                # 个别驱动切换后 overrideredirect 窗口 deiconify 不生效，
                # withdraw+deiconify 组合拳强制重映射（Unmap 处理器有 state
                # 检查，此处 state=withdrawn 不会触发缩托盘逻辑）
                self.withdraw()
                self.deiconify()
        self.lift()
        # 显示器热插拔/改布局后，窗口可能停在已消失的幽灵屏坐标或被系统甩到
        # 边角出屏——「恢复」必须连带钳制回可见桌面，否则等于没恢复（v1.8.4）
        try:
            _clamp_into_screen(self)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.focus_force()
        except Exception:  # noqa: BLE001  嵌桌面 NOACTIVATE 模式抢不到焦点也无妨
            pass

    def _on_display_changed(self):
        """显示器布局变化（WM_DISPLAYCHANGE 经托盘消息窗口转发，防抖 300ms）。
        热插拔外接屏/改分辨率后窗口常落在幽灵坐标或半截出屏且托盘恢复救不回
        （v1.8.3 及之前只有启动时救援）；现在实时钳制回可见桌面 + 补贴底。"""
        if getattr(self, "_disp_job", None):
            try:
                self.after_cancel(self._disp_job)
            except Exception:  # noqa: BLE001
                pass
        self._disp_job = self.after(300, self._display_fix)

    def _display_fix(self):
        self._disp_job = None
        try:
            _clamp_into_screen(self)
        except Exception:  # noqa: BLE001
            pass
        if self.embedded and self.desktop_bottom:
            try:
                self._ensure_desktop_bottom()
            except Exception:  # noqa: BLE001
                pass

    def _tray_tip(self):
        """托盘悬浮提示：今日待办条数"""
        n = sum(1 for _, _t, dn, _r, _rm, _i, _p
                in db_tasks_on(self.conn, self.today.isoformat()) if not dn)
        return T("tray_tip", n=n)

    def _tray_menu_items(self):
        """托盘右键菜单项；每次弹出时重新取词，语言切换立即生效"""
        return [
            ("show", T("tray_show"), True),
            ("add", T("tray_add"), True),
            (None, "", False),
            ("push", T("tray_push"), True),
            ("clean", T("tray_clean"), True),
            (None, "", False),
            ("settings", T("tray_settings"), True),
            ("exit", T("tray_exit"), True),
        ]

    def _tray_menu_action(self, key):
        if key == "show":
            self.show_from_tray()
        elif key == "add":
            self._tray_quick_add_dialog()
        elif key == "push":
            self._tray_push_today()
        elif key == "clean":
            self._tray_clean_done()
        elif key == "settings":
            self.show_from_tray()
            self.open_settings()
        elif key == "exit":
            self.on_close()

    def _tray_push_today(self):
        """托盘「推送今日待办」：跳过勾选框，直接推送今天全部未完成任务"""
        if not (self.wecom_webhook or (self.wecom_corp_id and self.wecom_agent_id
                                       and self.wecom_corp_secret)):
            self.tray_toast(T("no_wecom_cfg2"))
            return
        undone = [t for t in db_tasks_on(self.conn, self.today.isoformat())
                  if not t[2]]
        if not undone:
            self.tray_toast(T("tray_push_none"))
            return
        day = self.today
        lines = [T("push_lines", m=day.month, d=day.day, n=len(undone))]
        for _tid, title, _done, _rep, rtime, imp, pin in undone:
            mark = "🔴" if imp else "▫️"
            text = ("📌 " if pin else "") + title + (f"（⏰{rtime}）" if rtime else "")
            lines.append(f"{mark} {text}")

        def work():
            results = []
            if self.wecom_webhook:
                results.append(wecom_push(self.wecom_webhook, "\n".join(lines)))
            if self.wecom_corp_id and self.wecom_agent_id and self.wecom_corp_secret:
                results.append(wecom_app_push(self.wecom_corp_id, self.wecom_agent_id,
                                              self.wecom_corp_secret, "\n".join(lines)))
            ok = any(s for _n, s, _e in results)
            err = next((e for _n, s, e in results if not s), "")
            self.after(0, lambda: self.tray_toast(
                T("tray_push_sent", n=len(undone)) if ok
                else T("tray_push_fail", e=err or "?")))

        threading.Thread(target=work, daemon=True).start()

    def _tray_clean_done(self):
        """托盘「清理已完成任务」：与清单页清理按钮同一逻辑，气泡反馈结果"""
        n = self.conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 1").fetchone()[0]
        if not n:
            self.tray_toast(T("tray_clean_none"))
            return
        self.clear_done()
        self.tray_toast(T("tray_clean_done", n=n))

    def _tray_quick_add_dialog(self):
        """托盘「新增任务」：不开主窗口的轻量录入小窗。
        只做日任务（标题 + 今天/明天/后天 + 可选提醒时间 + 重要）——周/月/工作日
        任务需要星期几、几号、间隔等选项，仍走主窗口添加视图。
        重复防护与 v1.7.2 精神一致：同日同名日任务已存在则拦下并提示。"""
        win = tk.Toplevel(self)
        win.withdraw()
        win.title(T("qadd_title"))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=self.bg_color)
        frm = tk.Frame(win, bg=self.bg_color, padx=14, pady=12)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text=T("qadd_title"), font=self.font_base,
                 bg=self.bg_color, fg=self.cal_fg).pack(anchor="w")
        ent = tk.Entry(frm, font=self.font_base, width=28,
                       bg=COLOR["cell"], fg=self.task_fg)
        ent.pack(fill="x", pady=(6, 8))
        ent.focus_set()
        row1 = tk.Frame(frm, bg=self.bg_color)
        row1.pack(fill="x")
        tk.Label(row1, text=T("qadd_date"), font=self.font_small,
                 bg=self.bg_color, fg=self.task_fg).pack(side="left")
        cmb = ttk.Combobox(row1, state="readonly", width=6, font=self.font_small,
                           values=(T("qadd_today"), T("qadd_tomorrow"),
                                   T("qadd_dayafter")))
        cmb.current(0)
        cmb.pack(side="left", padx=(4, 10))
        tk.Label(row1, text=T("qadd_time"), font=self.font_small,
                 bg=self.bg_color, fg=self.task_fg).pack(side="left")
        t_ent = tk.Entry(row1, width=6, font=self.font_small,
                         bg=COLOR["cell"], fg=self.task_fg)
        t_ent.pack(side="left", padx=(4, 0))
        var_imp = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text=T("qadd_imp"), variable=var_imp,
                       font=self.font_small, bg=self.bg_color,
                       fg=self.task_fg, activebackground=self.bg_color
                       ).pack(anchor="w", pady=(6, 8))

        def do_add(_ev=None):
            title = ent.get().strip()
            if not title:
                ent.focus_set()
                return
            d = self.today + timedelta(days=cmb.current())
            rt = t_ent.get().strip()
            if rt and not self._valid_time(rt):
                messagebox.showwarning(T("warn_title"), T("qadd_time_bad"),
                                       parent=win)
                return
            n = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE title = ? AND task_date = ? "
                "AND repeat = 'day'", (title, d.isoformat())).fetchone()[0]
            if n:
                messagebox.showwarning(T("warn_title"), T("qadd_dup"), parent=win)
                return
            self.conn.execute(
                "INSERT INTO tasks (task_date, title, done, repeat, remind_time, "
                "important, pinned, series_id, interval) "
                "VALUES (?, ?, 0, 'day', ?, ?, 0, '', 1)",
                (d.isoformat(), title, rt, 1 if var_imp.get() else 0))
            self.conn.commit()
            self.refresh()
            self.tray_toast(T("qadd_added", t=title))
            win.destroy()

        btns = tk.Frame(frm, bg=self.bg_color)
        btns.pack(fill="x")
        tk.Button(btns, text=T("qadd_btn"), font=self.font_base, width=6,
                  command=do_add).pack(side="left")
        tk.Button(btns, text=T("btn_cancel"), font=self.font_base, width=6,
                  command=win.destroy).pack(side="left", padx=(8, 0))
        win.bind("<Return>", do_add)
        win.bind("<Escape>", lambda _e: win.destroy())
        self._qadd_win = win          # 引用防 GC；测试与后续调用可复用
        win._do_add = do_add
        win._ent, win._cmb, win._t_ent, win._var_imp = ent, cmb, t_ent, var_imp
        win.update_idletasks()
        # 主屏工作区居中偏上（主窗口可能藏在托盘，不跟随它定位）
        areas = _screen_rects()
        if areas:
            l, t, r, b = areas[0][1]
            win.geometry(f"+{l + max(0, (r - l - win.winfo_reqwidth()) // 2)}"
                         f"+{t + max(0, (b - t - win.winfo_reqheight()) // 3)}")
        win.deiconify()
        win.lift()
        win.focus_force()

    def tray_toast(self, text):
        """主窗口藏在托盘时的右下角小气泡提示（独立置顶小窗，2.5 秒自动消失）"""
        toast = tk.Toplevel(self)
        toast.withdraw()
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        tk.Label(toast, text=text, font=self.font_base, justify="left",
                 bg="#ffffff", fg=COLOR["text"],
                 padx=16, pady=10).pack()
        toast.update_idletasks()
        w, h = toast.winfo_reqwidth(), toast.winfo_reqheight()
        area = _primary_work_area()
        sw, sh = area if area else (self.winfo_screenwidth(), self.winfo_screenheight())
        toast.geometry(f"+{sw - w - 16}+{max(0, sh - h - 16)}")
        toast.deiconify()
        toast.after(2500, toast.destroy)

    def _ics_auto_sync(self):
        """ICS 订阅每日静默同步：距上次成功超过 24 小时才拉取，失败不打扰用户"""
        url = self.ics_url
        if not url:
            return
        try:
            last = kv_get(self.conn, "ics_last_sync")
            if last:
                if (datetime.now() - datetime.fromisoformat(last)) < timedelta(days=1):
                    return
        except Exception:  # noqa: BLE001
            return

        def work():
            try:
                c = sqlite3.connect(DB_PATH)   # 线程里另开连接，不动主连接
                try:
                    added, _skipped = ics_sync(c, url)
                    if added:
                        kv_set(c, "ics_last_sync", datetime.now().isoformat())
                        self.after(0, lambda: (self.refresh(),
                                               self._flash_tip(T("ics_ok", n=added, s=_skipped))))
                    else:
                        kv_set(c, "ics_last_sync", datetime.now().isoformat())
                finally:
                    c.close()
            except Exception:  # noqa: BLE001  静默失败，下次再试
                pass

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 界面构建 / 语言切换 ----------------
    def _build_ui(self):
        """构建整个界面：顶部签名条 + 语言切换 + 三个页面 + 主题 + 贴桌面。

        单独抽成方法是为了切换语言时能整体重建。为什么不逐个控件改文字：
        计算页是懒加载的、表格表头/下拉框选项/各页按钮分散在三处构建，
        逐个登记极易漏掉某处；整体重建可保证无一遗漏。"""
        # 顶部签名条：中文「王的出品」/ 英文 King's Product，右侧为语言切换
        self.top_bar = tk.Frame(self)
        self.top_bar.pack(fill="x", padx=12, pady=(8, 0))
        self.lbl_sign = tk.Label(self.top_bar, text=T("signature"),
                                 font=("Microsoft YaHei UI", 10, "bold"),
                                 fg=self.accent)
        self.lbl_sign.pack(side="left")
        self._build_lang_switch(self.top_bar)   # 语言切换放主界面，点击即时生效

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.tab_month = tk.Frame(self.notebook)
        self.tab_list = tk.Frame(self.notebook)
        self.tab_calc = tk.Frame(self.notebook)
        self.notebook.add(self.tab_month, text=T("tab_cal"))
        self.notebook.add(self.tab_list, text=T("tab_list"))
        self.notebook.add(self.tab_calc, text=T("tab_calc"))
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.refresh())

        self._calc_built = False     # 计算页懒加载标记（重建界面时重置）
        self._build_month_tab()
        self._build_list_tab()
        self._register_themed()
        self.apply_theme()
        if self.bg_image_path and Path(self.bg_image_path).exists():
            self.apply_bg_image()
        self.set_embedded(self.embedded)  # 启动即嵌桌面（无标题栏）
        self.refresh()

    def _build_lang_switch(self, parent):
        """主界面语言切换：中文 / English，当前语言高亮，点击即时切换（无需重启）"""
        box = tk.Frame(parent)
        box.pack(side="right")
        self._lang_btns = {}
        for code, label in (("zh", "中文"), ("en", "English")):
            btn = tk.Button(box, text=label, font=("Microsoft YaHei UI", 9),
                            width=7, bd=0, cursor="hand2",
                            command=lambda c=code: self.set_language(c))
            btn.pack(side="left", padx=(4, 0))
            self._lang_btns[code] = btn
        self._highlight_lang_btn()

    def _highlight_lang_btn(self):
        """当前语言按钮高亮（主题色底白字），另一个恢复常规配色"""
        for code, btn in self._lang_btns.items():
            if code == LANG:
                btn.config(bg=self.accent, fg="#ffffff",
                           activebackground=self.accent, activeforeground="#ffffff")
            else:
                btn.config(bg=self.bg_color, fg=COLOR["text"],
                           activebackground=self.bg_color,
                           activeforeground=COLOR["text"])

    def set_language(self, lang):
        """切换界面语言并立即生效（无需重启）：改全局 LANG 后整体重建界面。"""
        global LANG
        if lang not in STR or lang == LANG:
            return
        # 重建前保存界面状态，重建后原样恢复，避免用户被"弹回"默认视图
        try:
            tab = self.notebook.index(self.notebook.select())
        except Exception:
            tab = 0
        sel, vy, vm = self.sel_date, self.view_year, self.view_month
        had_calc = getattr(self, "_calc_built", False)   # 之前是否进过计算页
        draft = ""
        try:
            draft = self.ent_task.get()
        except Exception:
            pass

        LANG = lang
        self.lang = lang

        # 重建前必须先结束打字保护会话：重建会销毁正持有焦点的输入框，
        # FocusOut 不再触发、_ime_plain 闩锁永久卡死——之后所有贴底校验与
        # 固定操作被跳过，日历浮在最上层且点「固定」无效（v1.8.3 根因）。
        # 分层样式在此还原；NOACTIVATE 由重建里的 set_embedded 重新统一设置。
        if getattr(self, "_ime_plain", False):
            self._ime_plain = False
            self._restore_deferred = False
            self._stop_focus_watchdog()
            hwnd0 = _toplevel_hwnd(self)
            if _user32 and hwnd0 and self.alpha < self._ALPHA_OPAQUE:
                _set_layered(hwnd0, True)

        self.top_bar.destroy()
        self.notebook.destroy()
        self._build_ui()
        if had_calc:                       # 进过计算页就重建它，保持内容完整
            self._build_calc_tab()
            self._calc_built = True

        self.sel_date, self.view_year, self.view_month = sel, vy, vm
        if draft:
            try:
                self.ent_task.insert(0, draft)  # 保留输入框里没提交的内容
            except Exception:
                pass
        self.notebook.select(tab)
        self.refresh()
        self.persist_cfg()                 # 落盘，下次启动沿用


    def _register_themed(self):
        """需要跟随底色变化的静态容器/控件；动态渲染的控件在渲染时直接取 self.bg_color"""
        self._themed = [
            self, self.top_bar, self.lbl_sign, self.tab_month, self.tab_list,
            self.tab_calc, self.nav, self.body, self.cal,
            self.head_frame, self.panel, self.hdr, self.add_box, self.add_bar,
            self.type_extra, self.ent_row, self.chk_remind,
            self.lbl_month, self.lbl_sel, self.lbl_day_stat, self.list_bar,
            self.task_area.canvas, self.task_area.inner, self.grid_frame,
        ]

    def apply_theme(self):
        """把底色应用到窗口与容器（月历格子保持白卡样式，突出内容）"""
        s = self.bg_color
        for w in self._themed:
            try:
                w.configure(bg=s)
            except tk.TclError:
                pass
        style = ttk.Style(self)
        style.configure("TNotebook", background=s, borderwidth=0)
        style.configure("TNotebook.Tab", background=s)
        style.configure("Task.Treeview", background=s, fieldbackground=s,
                        rowheight=self.task_size + 12)
        if hasattr(self, "tree"):
            self.tree.configure(style="Task.Treeview")
        # 主题色联动：签名文字、语言切换按钮、计算页结果行（已建时）。
        # 只改 _themed 容器的底色不够，改色后这些 accent 相关控件会停留在旧色。
        try:
            self.lbl_sign.config(fg=self.accent)
            self._highlight_lang_btn()
            if getattr(self, "_calc_built", False):
                self.lbl_calc1.config(fg=self.accent)
                self.lbl_calc2.config(fg=self.accent)
                self.lbl_calc3.config(fg=self.accent)
        except (tk.TclError, AttributeError):
            pass

    def _tick(self):
        """每分钟检查是否跨天；跨天则自动跟到新的一天。

        修复：原先只更新 self.today 就刷新，但「选中日期」sel_date 仍停在前一天，
        于是任务面板继续显示昨天的清单，必须手点「今天」才会切过来。
        现在跨天时：
        - 若用户原本就停在当天 → 选中日期一起推进到新的一天；
        - 若用户正在翻看别的日期 → 不动，免得打断浏览；
        月历视图同理，只有原本显示的是当天所在月份才跟随跨月。"""
        try:
            now = date.today()
            if now != self.today:
                was_on_today = (self.sel_date == self.today)
                was_on_today_month = ((self.view_year, self.view_month)
                                      == (self.today.year, self.today.month))
                self.today = now
                roll_pending_tasks(self.conn, self.today)
                expand_series(self.conn, self.today)   # 新的一天：系列再往后补一期
                if was_on_today:
                    self.sel_date = self.today          # 跟随到新的一天
                if was_on_today_month:
                    self.view_year = self.today.year
                    self.view_month = self.today.month
                self.refresh()
        finally:
            self.after(60_000, self._tick)  # 放 finally：本次出错也不能让跨天检查停摆

    # ---------------- 界面搭建 ----------------
    def _build_month_tab(self):
        """日历页：顶部月份导航 + 左侧月历网格 + 右侧当日任务面板"""
        # 顶部：月份导航（翻月 / 今天 / 设置 / 固定-移动 / 关闭）
        self.nav = nav = tk.Frame(self.tab_month, pady=6)
        nav.pack(fill="x", padx=10)
        tk.Button(nav, text="‹", width=3, font=self.font_base,
                  command=lambda: self.shift_month(-1)).pack(side="left")
        self.lbl_month = tk.Label(nav, width=14, font=("Microsoft YaHei UI", 13, "bold"))
        self.lbl_month.pack(side="left", expand=True)
        tk.Button(nav, text="›", width=3, font=self.font_base,
                  command=lambda: self.shift_month(1)).pack(side="left")
        # 右侧按钮组按从右到左的顺序排：今天 / 设置 / 固定-移动。
        # 导航区不放关闭按钮：移动模式由标题栏 ✕ 关闭（唯一关闭入口），
        # 固定（嵌桌面）模式无标题栏，本就不提供关闭
        self.btn_today = tk.Button(nav, text=T("btn_today"), font=self.font_base,
                                   command=self.go_today)
        self.btn_today.pack(side="right")
        self.btn_settings = tk.Button(nav, text=T("btn_settings"), font=self.font_base,
                                      command=self.open_settings)
        self.btn_settings.pack(side="right", padx=(0, 6))
        # 「固定/移动」按钮：文字即当前可执行的动作（固定状态下显示「移动」）
        self.btn_move = tk.Button(nav, text=T("btn_pin"), font=self.font_base, width=6,
                                  command=self.toggle_embedded)
        self.btn_move.pack(side="right", padx=(0, 6))

        self.body = body = tk.Frame(self.tab_month)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # 左侧：月历网格（第 0 列为周数列，1-7 列为星期）
        self.cal = cal = tk.Frame(body)
        cal.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        cal.columnconfigure(0, weight=1)  # 让网格横向铺满可用宽度
        cal.rowconfigure(1, weight=1)     # 纵向铺满
        self.head_frame = tk.Frame(cal)
        self.head_frame.grid(row=0, column=0, sticky="ew", columnspan=8)
        self.grid_frame = tk.Frame(cal, bg="#e5e7eb")
        self.grid_frame.grid(row=1, column=0, sticky="nsew", columnspan=8)
        for r in range(6):
            self.grid_frame.rowconfigure(r, weight=1, uniform="row", minsize=64)
        for frame in (self.head_frame, self.grid_frame):
            frame.columnconfigure(0, minsize=26)
            for c in range(1, 8):
                frame.columnconfigure(c, weight=1, uniform="col")

        # 右侧：当日任务面板
        self.panel = panel = tk.Frame(body, width=320, bd=1, relief="solid")
        panel.grid(row=0, column=1, sticky="nsew")
        panel.pack_propagate(False)
        self.hdr = hdr = tk.Frame(panel)
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        self.lbl_sel = tk.Label(hdr, font=("Microsoft YaHei UI", 12, "bold"),
                                anchor="w")
        self.lbl_sel.pack(side="left")
        self.lbl_day_stat = tk.Label(hdr, font=self.font_small,
                                     fg=COLOR["text_sub"])
        self.lbl_day_stat.pack(side="right")
        self.task_area = ScrollFrame(panel, bg=self.bg_color)
        self.task_area.pack(fill="both", expand=True, padx=6)

        self.add_box = add_box = tk.Frame(panel, pady=8)
        add_box.pack(fill="x", side="bottom", padx=8)
        self.ent_row = ent_row = tk.Frame(add_box)
        ent_row.pack(fill="x")
        self.ent_task = tk.Entry(ent_row, font=self.font_base)
        self.ent_task.pack(side="left", fill="x", expand=True, ipady=3)
        self.ent_task.bind("<Return>", lambda e: self.add_task())
        tk.Button(ent_row, text=T("btn_add"), font=self.font_base, width=6,
                  command=self.add_task).pack(side="left", padx=(6, 0))
        self.add_bar = add_bar = tk.Frame(add_box)
        add_bar.pack(fill="x", pady=(6, 0))
        self.cmb_type = ttk.Combobox(add_bar, width=10, state="readonly",
                                     values=[T("type_day"), T("type_week"),
                                             T("type_month"), T("type_workday")],
                                     font=self.font_base)
        self.cmb_type.current(0)
        self.cmb_type.pack(side="left")
        self.cmb_type.bind("<<ComboboxSelected>>",
                           lambda _e: self.sync_type_selectors())
        # 周任务选星期（+每N周）、月任务选当月几号（按所选类型只显示其一）
        self.type_extra = tk.Frame(add_bar)
        self.type_extra.pack(side="left", padx=(6, 0))
        self.cmb_weekday = ttk.Combobox(self.type_extra, width=6, state="readonly",
                                        values=weekday_names(), font=self.font_small)
        self.cmb_winterval = ttk.Combobox(self.type_extra, width=6, state="readonly",
                                          values=T("iv_weeks"), font=self.font_small)
        self.cmb_winterval.current(0)
        self.cmb_mday = ttk.Combobox(self.type_extra, width=4, state="readonly",
                                     values=[str(i) for i in range(1, 32)],
                                     font=self.font_small)
        # 提醒时间下拉选择：默认不勾选（不提醒），勾选后预填下一个 5 分钟整点
        self.var_remind = tk.BooleanVar(value=False)
        self.chk_remind = tk.Checkbutton(add_bar, text=T("lbl_remind"),
                                         variable=self.var_remind,
                                         font=self.font_small, bg=self.bg_color,
                                         activebackground=self.bg_color,
                                         command=self._toggle_remind_ui)
        self.chk_remind.pack(side="left", padx=(8, 0))
        self.cmb_hour = ttk.Combobox(add_bar, width=3, state="disabled",
                                     values=[f"{h:02d}" for h in range(24)],
                                     font=self.font_small)
        self.cmb_hour.pack(side="left", padx=(3, 0))
        tk.Label(add_bar, text=":", font=self.font_small,
                 fg=COLOR["text_sub"]).pack(side="left")
        self.cmb_min = ttk.Combobox(add_bar, width=3, state="disabled",
                                    values=[f"{m:02d}" for m in range(0, 60, 5)],
                                    font=self.font_small)
        self.cmb_min.pack(side="left")
        # 提示行：添加周/月任务后显示「已生成 N 期」，几秒后自动消失
        self._tip_job = None
        self.lbl_tip = tk.Label(add_box, text="", font=self.font_small,
                                fg=COLOR["ok"], anchor="w")
        self.lbl_tip.pack(fill="x", pady=(4, 0))

    def _flash_tip(self, text: str):
        """在添加栏下方短暂显示一行绿色提示（6 秒后自动清空）。

        切语言会整体重建界面，旧定时器可能指向已销毁的控件，所以每次读写都先
        winfo_exists() 确认，避免 TclError 打断启动流程。"""
        if getattr(self, "_tip_job", None):
            try:
                self.after_cancel(self._tip_job)
            except Exception:      # noqa: BLE001
                pass
            self._tip_job = None

        def clear():
            try:
                if self.lbl_tip.winfo_exists():
                    self.lbl_tip.config(text="")
            except Exception:      # noqa: BLE001
                pass
            self._tip_job = None

        try:
            if self.lbl_tip.winfo_exists():
                self.lbl_tip.config(text=text)
                self._tip_job = self.after(6000, clear)
        except Exception:          # noqa: BLE001
            pass

    def _build_list_tab(self):
        """全部清单页：全量任务表格 + 批量操作工具栏"""
        self.list_bar = bar = tk.Frame(self.tab_list, pady=8)
        bar.pack(fill="x", padx=10)
        tk.Label(bar, text=T("list_hint"),
                 font=self.font_base, fg=COLOR["text_sub"]).pack(side="left")
        tk.Button(bar, text=T("btn_edit"), font=self.font_base,
                  command=self.edit_selected).pack(side="right", padx=4)
        tk.Button(bar, text=T("btn_toggle"), font=self.font_base,
                  command=self.toggle_selected).pack(side="right", padx=4)
        tk.Button(bar, text=T("btn_del_sel"), font=self.font_base,
                  command=self.delete_selected).pack(side="right", padx=4)
        tk.Button(bar, text=T("btn_clear"), font=self.font_base,
                  command=self.clear_done).pack(side="right", padx=4)
        tk.Button(bar, text=T("btn_export"), font=self.font_base,
                  command=self.export_tasks).pack(side="right", padx=4)
        tk.Button(bar, text=T("btn_import"), font=self.font_base,
                  command=self.import_tasks).pack(side="right", padx=4)

        cols = ("date", "status", "type", "remind", "title")
        self.tree = ttk.Treeview(self.tab_list, columns=cols, show="headings")
        self.tree.heading("date", text=T("col_date"))
        self.tree.heading("status", text=T("col_status"))
        self.tree.heading("type", text=T("col_type"))
        self.tree.heading("remind", text=T("col_remind"))
        self.tree.heading("title", text=T("col_task"))
        self.tree.column("date", width=110, anchor="center")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("type", width=50, anchor="center")
        self.tree.column("remind", width=60, anchor="center")
        self.tree.column("title", width=450, anchor="w")
        self.tree.tag_configure("overdue", foreground=COLOR["danger"])
        self.tree.tag_configure("done", foreground=COLOR["done"])
        self.tree.tag_configure("today", foreground=COLOR["accent"])
        self.tree.tag_configure("imp", foreground=COLOR["danger"])
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tree.bind("<Double-1>", lambda e: self.toggle_selected())
        # 右键菜单：清单页也能编辑 / 改提醒 / 删整系列（双击仍是切换完成）
        self.tree.bind("<Button-3>", self.show_list_menu)

    def show_list_menu(self, event):
        """全部清单页表格的右键菜单：先选中鼠标所在行，再给出可执行的操作"""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        tid = int(iid)
        row = self.conn.execute(
            "SELECT title, repeat, remind_time, important, series_id FROM tasks "
            "WHERE id = ?", (tid,)).fetchone()
        if not row:
            return
        _title, rep, rtime, imp, sid = row
        n = series_count(self.conn, sid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=T("menu_edit"),
                         command=lambda: self.edit_task(tid))
        menu.add_command(label=T("menu_remind"),
                         command=lambda: self.edit_reminder(tid, rtime))
        menu.add_command(label=T("menu_clear_remind"),
                         command=lambda: self.set_reminder(tid, ""))
        menu.add_separator()
        menu.add_command(label=T("menu_imp") if not imp else T("menu_unimp"),
                         command=lambda: self.toggle_flag(tid, "important"))
        menu.add_separator()
        menu.add_command(label=T("menu_del"),
                         command=lambda: self.delete_task(tid))
        if sid and n > 1:
            menu.add_command(label=T("menu_del_series", n=n),
                             command=lambda: self.delete_series(sid, _title))
        menu.tk_popup(event.x_root, event.y_root)

    # ---------------- 日期计算 ----------------
    def _build_calc_tab(self):
        """日期计算页：① 节日倒计时 ② 两日期相差 ③ 今天±N 天 ④ 倒数日/纪念日。
        内容超过一屏，整页放进可滚动容器"""
        sf = ScrollFrame(self.tab_calc, bg=self.bg_color)
        sf.pack(fill="both", expand=True)
        wrap = sf.inner
        pad = {"padx": 30, "pady": 3}

        def head(text):
            # 每节的标题行
            tk.Label(wrap, text=text, font=("Microsoft YaHei UI", 11, "bold"),
                     anchor="w").pack(fill="x", padx=30, pady=(14, 4))

        def result_lbl():
            # 每节的结果显示行（主题色加粗，一眼看到答案）
            return tk.Label(wrap, text="", font=("Microsoft YaHei UI", 12, "bold"),
                            fg=self.accent, anchor="w")

        # —— ① 节日倒计时：今天距离所选节日还有几天 ——
        head(T("calc_countdown"))
        row1 = tk.Frame(wrap)
        row1.pack(fill="x", padx=30)
        tk.Label(row1, text=T("calc_pick"), font=self.font_base).pack(side="left")
        self.holidays = upcoming_holidays()  # [(文案键, date)] 按日期升序
        names = [T(k) for k, _d in self.holidays]
        self.cmb_holiday = ttk.Combobox(row1, values=names, state="readonly",
                                        width=16, font=self.font_base)
        if names:
            self.cmb_holiday.current(0)  # 默认选最近的节日
        self.cmb_holiday.pack(side="left", padx=(8, 6))
        tk.Button(row1, text=T("calc_btn"), font=self.font_base,
                  command=self.calc_countdown).pack(side="left")
        self.lbl_calc1 = result_lbl()
        self.lbl_calc1.pack(fill="x", padx=30, pady=(4, 0))
        ttk.Separator(wrap).pack(fill="x", padx=30, pady=(16, 0))

        # —— ② 两日期相差 ——
        head(T("calc_between"))
        row2 = tk.Frame(wrap)
        row2.pack(fill="x", padx=30)
        tk.Label(row2, text=T("calc_date1"), font=self.font_small).pack(side="left")
        self.ent_calc1 = DateSpin(row2, self.font_small)
        self.ent_calc1.set_date(self.today)
        self.ent_calc1.pack(side="left", padx=(4, 14))
        tk.Label(row2, text=T("calc_date2"), font=self.font_small).pack(side="left")
        self.ent_calc2 = DateSpin(row2, self.font_small)
        self.ent_calc2.set_date(self.today + timedelta(days=30))
        self.ent_calc2.pack(side="left", padx=(4, 10))
        tk.Button(row2, text=T("calc_btn"), font=self.font_base,
                  command=self.calc_between).pack(side="left")
        self.lbl_calc2 = result_lbl()
        self.lbl_calc2.pack(fill="x", padx=30, pady=(4, 0))
        ttk.Separator(wrap).pack(fill="x", padx=30, pady=(16, 0))

        # —— ③ 今天 ± N 天 ——
        head(T("calc_offset"))
        row3 = tk.Frame(wrap)
        row3.pack(fill="x", padx=30)
        tk.Label(row3, text=T("calc_days"), font=self.font_small).pack(side="left")
        self.ent_calc3 = tk.Entry(row3, width=8, justify="center",
                                  font=self.font_small)
        self.ent_calc3.insert(0, "30")  # 默认 +30 天
        self.ent_calc3.pack(side="left", padx=(4, 10), ipady=2)
        tk.Button(row3, text=T("calc_btn"), font=self.font_base,
                  command=self.calc_offset).pack(side="left")
        self.lbl_calc3 = result_lbl()
        self.lbl_calc3.pack(fill="x", padx=30, pady=(4, 0))

        # 三个输入框都支持回车直接计算
        for ent, fn in ((self.ent_calc1, self.calc_between),
                        (self.ent_calc2, self.calc_between),
                        (self.ent_calc3, self.calc_offset)):
            ent.bind("<Return>", lambda e, f=fn: f())

        # —— ④ 倒数日 / 纪念日（含农历生日自动换算；当天右下角弹提示）——
        ttk.Separator(wrap).pack(fill="x", padx=30, pady=(16, 0))
        head(T("event_head"))
        erow = tk.Frame(wrap)
        erow.pack(fill="x", padx=30)
        tk.Button(erow, text=T("event_add"), font=self.font_small, bd=0,
                  cursor="hand2", command=self.add_event_dialog).pack(side="left")
        self.events_box = tk.Frame(wrap)
        self.events_box.pack(fill="x", padx=30, pady=(2, 0))
        self.render_events()

    def render_events(self):
        """倒数日/纪念日列表：每年纪念日显示下一次日期与剩余天数
        （农历条目自动换算公历），单次倒数显示剩余天数"""
        box = self.events_box
        for w in box.winfo_children():
            w.destroy()
        events = db_events(self.conn)
        if not events:
            tk.Label(box, text=T("event_none"), font=self.font_small,
                     fg=COLOR["text_other"], anchor="w").pack(fill="x")
            return
        for eid, name, dstr, kind, lunar in events:
            try:
                d0 = date.fromisoformat(dstr)
            except ValueError:
                continue
            if kind == "annual":
                icon = "🎂"
                if lunar:
                    desc = T("event_desc_lunar", m=d0.month, d=d0.day)
                    nxt = lunar_annual_date(d0, self.today.year)
                    if nxt and nxt < self.today:
                        nxt = lunar_annual_date(d0, self.today.year + 1) or nxt
                else:
                    desc = T("event_desc_annual", m=d0.month, d=d0.day)
                    nxt = None
                    try:
                        nxt = d0.replace(year=self.today.year)
                    except ValueError:
                        pass
                    if nxt and nxt < self.today:
                        try:
                            nxt = d0.replace(year=self.today.year + 1)
                        except ValueError:
                            pass
                if nxt:
                    n = (nxt - self.today).days
                    left = (T("event_today") if n == 0
                            else T("event_left", n=n) if n > 0
                            else T("event_past", n=-n))
                    state = f"{nxt.isoformat()} · {left}"
                else:
                    state = d0.isoformat()
            else:
                icon = "⏳"
                desc = d0.isoformat()
                n = (d0 - self.today).days
                left = (T("event_today") if n == 0
                        else T("event_left", n=n) if n > 0
                        else T("event_past", n=-n))
                state = left
            row = tk.Frame(box)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{icon} {name}", font=self.font_base,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"{desc} · {state}", font=self.font_small,
                     fg=COLOR["text_sub"], anchor="w").pack(side="left", padx=(8, 0))
            tk.Button(row, text="✕", bd=0, fg=COLOR["text_sub"],
                      font=self.font_small, cursor="hand2",
                      command=lambda i=eid: (del_event(self.conn, i),
                                             self.render_events())
                      ).pack(side="right")

    def add_event_dialog(self):
        """添加倒数日/纪念日：名称 + 日期 + 类型（每年纪念日 / 单次倒数）+ 是否农历。
        农历纪念日以后每年按该日期的农历月/日自动换算成公历（如农历生日）。"""
        win = tk.Toplevel(self)
        win.title(T("event_win_title"))
        win.resizable(False, False)
        win.transient(self)
        win.attributes("-topmost", True)
        frm = tk.Frame(win, padx=14, pady=10)
        frm.pack()
        tk.Label(frm, text=T("event_name"), font=self.font_base).grid(
            row=0, column=0, sticky="w")
        ent = tk.Entry(frm, width=24, font=self.font_base)
        ent.grid(row=0, column=1, sticky="we", padx=(6, 0), pady=(0, 6))
        ent.focus_set()
        tk.Label(frm, text=T("event_date"), font=self.font_base).grid(
            row=1, column=0, sticky="w")
        ent_date = DateSpin(frm, self.font_base)
        ent_date.set_date(self.today)
        ent_date.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(0, 6))
        tk.Label(frm, text=T("event_kind"), font=self.font_base).grid(
            row=2, column=0, sticky="w")
        kind_cb = ttk.Combobox(frm, values=[T("event_annual"), T("event_countdown")],
                               state="readonly", width=12, font=self.font_base)
        kind_cb.current(0)
        kind_cb.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(0, 6))
        var_lunar = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text=T("event_lunar"), variable=var_lunar,
                       font=self.font_base).grid(row=3, column=1, sticky="w")

        def on_ok():
            name = ent.get().strip()
            if not name:
                messagebox.showwarning(T("warn_title"), T("event_empty_name"),
                                       parent=win)
                return
            d0 = ent_date.get_date()
            if d0 is None:
                messagebox.showwarning(T("warn_title"), T("calc_bad_date"),
                                       parent=win)
                return
            kind = "annual" if kind_cb.current() == 0 else "countdown"
            add_event(self.conn, name, d0.isoformat(), kind, var_lunar.get())
            win.destroy()
            self.render_events()
            self.render_grid()

        btns = tk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        tk.Button(btns, text=T("btn_ok"), font=self.font_base, width=6,
                  command=on_ok).pack(side="left")
        tk.Button(btns, text=T("btn_cancel"), font=self.font_base, width=6,
                  command=win.destroy).pack(side="left", padx=(6, 0))
        win.bind("<Return>", lambda e: on_ok())
        win.grab_set()

    def calc_countdown(self):
        """① 节日倒计时：显示距离所选节日的天数与周数拆分"""
        if not getattr(self, "holidays", None):
            return
        key, d = self.holidays[self.cmb_holiday.current()]
        n = (d - self.today).days
        disp = f"{T(key)} {d.isoformat()}"
        if n == 0:
            self.lbl_calc1.config(text=T("calc_target_today", d=disp))
        else:
            self.lbl_calc1.config(text=T("calc_days_until", d=disp, n=n,
                                         w=n // 7, r=n % 7))

    def calc_between(self):
        """② 两日期相差：取绝对天数并按「周 + 天」拆分显示"""
        d1 = self.ent_calc1.get_date()
        d2 = self.ent_calc2.get_date()
        if d1 is None or d2 is None:
            messagebox.showwarning(T("warn_title"), T("calc_bad_date"),
                                   parent=self)
            return
        n = abs((d2 - d1).days)
        if n == 0:
            self.lbl_calc2.config(text=T("calc_same"))
        else:
            self.lbl_calc2.config(text=T("calc_diff", n=n, w=n // 7, r=n % 7))

    def calc_offset(self):
        """③ 今天 ± N 天：N 为正=往后推，为负=往前推，显示目标日期与星期"""
        try:
            n = int(self.ent_calc3.get().strip())
        except ValueError:
            messagebox.showwarning(T("warn_title"), T("calc_bad_days"),
                                   parent=self)
            return
        target = self.today + timedelta(days=n)
        w = weekday_names()[target.weekday()]
        if n >= 0:
            self.lbl_calc3.config(text=T("calc_offset_result", n=n,
                                         d=target.isoformat(), w=w))
        else:
            self.lbl_calc3.config(text=T("calc_offset_before", a=-n,
                                         d=target.isoformat(), w=w))

    # ---------------- 渲染 ----------------
    def refresh(self):
        """按当前所在页刷新对应视图（计算页为静态表单，无需刷新）"""
        self.render_title()
        if getattr(self, "tray", None):   # tray 在 __init__ 尾部才创建，_build_ui 期间无
            self.tray.set_tip(self._tray_tip())
        idx = self.notebook.index(self.notebook.select())
        if idx == 0:
            self.render_grid()
            self.render_day_panel()
        elif idx == 1:
            self.render_list()
        else:  # 日期计算页：首次进入才构建（农历节日扫描较慢，懒加载保启动速度）
            if not getattr(self, "_calc_built", False):
                self._build_calc_tab()
                self._calc_built = True
            self.calc_countdown()
            if getattr(self, "events_box", None):
                self.render_events()

    def render_title(self):
        """窗口标题显示今日待办数；月份导航显示当前年月"""
        pending_today = sum(
            1 for _, _t, dn, _r, _rm, _i, _p in db_tasks_on(self.conn, self.today.isoformat()) if not dn
        )
        self.title(T("title_pending", n=pending_today))
        if self.tray:                      # 托盘悬浮提示同步今日待办数
            self.tray.set_tip(self._tray_tip())
        self.lbl_month.config(text=T("month_label", y=self.view_year,
                                     m=self.view_month))

    def render_grid(self):
        # 英文界面不显示农历：数字形式的「7/28」对英文用户没有意义，
        # 用户明确要求切到英语后取消农历。节气在英文模式下 lunar_info 已返回 None。
        show_lunar_eff = self.show_lunar and LANG != "en"
        for frame in (self.head_frame, self.grid_frame):
            for w in frame.winfo_children():
                w.destroy()

        sun_first = self.week_start == "sun"  # 每周开始于周日时列序整体右移一天
        # 列顺序：0~6 = 周一~周日；周日开头则把周日(6)提到最前
        order = ([6, 0, 1, 2, 3, 4, 5] if sun_first else [0, 1, 2, 3, 4, 5, 6])
        wk_minsize = 26 if self.show_weekno else 0
        self.head_frame.columnconfigure(0, minsize=wk_minsize)
        self.grid_frame.columnconfigure(0, minsize=wk_minsize)
        if self.show_weekno:
            tk.Label(self.head_frame, text=T("week_head"), fg=COLOR["text_sub"],
                     bg=self.bg_color, font=self.font_small).grid(row=0, column=0)
        for i, wd in enumerate(order):
            tk.Label(self.head_frame, text=grid_weekday(wd), fg=self.cal_fg,
                     bg=self.bg_color, font=self.f_cal_head).grid(
                row=0, column=i + 1, sticky="nsew")

        first = date(self.view_year, self.view_month, 1)
        last = date(self.view_year, self.view_month,
                    calendar.monthrange(self.view_year, self.view_month)[1])
        counts = db_counts_by_date(self.conn, first.isoformat(), last.isoformat())
        emarks = event_marks(self.conn, self.view_year, self.view_month)
        offset = (first.weekday() + 1) % 7 if sun_first else first.weekday()
        start = first - timedelta(days=offset)
        sel = self.sel_date.isoformat()

        for r in range(6):
            row_first = start + timedelta(days=r * 7)
            if self.show_weekno:
                # 以行内的周一为基准取 ISO 周号（周日开头时周一是第 2 格）
                week_ref = row_first + timedelta(days=1) if sun_first else row_first
                tk.Label(self.grid_frame, text=week_ref.isocalendar()[1],
                         fg=COLOR["text_other"], bg=self.bg_color,
                         font=self.font_small).grid(row=r, column=0, sticky="nsew")
            for c in range(7):
                d = row_first + timedelta(days=c)
                in_month = d.month == self.view_month
                hname = is_rest = makeup = None
                if in_month:
                    hname, is_rest, makeup = day_marks(d)
                ltext, term = "", None
                if in_month and (show_lunar_eff or self.show_terms):
                    ltext, term = lunar_info(d)

                bg, fg = COLOR["cell"], self.cal_fg
                if hname and self.show_holiday:
                    bg, fg = "#fef2f2", COLOR["danger"]  # 法定节假日：淡红底红字
                if not in_month:
                    bg, fg = COLOR["cell_other"], COLOR["text_other"]
                if d == self.today:
                    bg = COLOR["cell_today"]
                if d.isoformat() == sel:
                    bg = mix_hex(self.accent, 0.85)  # 选中格：主题色淡化
                cell = tk.Frame(self.grid_frame, bg=bg, bd=1, relief="ridge",
                                cursor="hand2")
                cell.grid(row=r, column=c + 1, sticky="nsew", padx=1, pady=1)
                cell.pack_propagate(False)  # 关键：内容不得反撑列宽，否则周六周会被挤出窗口

                n = counts.get(d.isoformat(), 0) if in_month else 0
                top = tk.Frame(cell, bg=bg)
                top.pack(fill="x")
                tk.Label(top, text=d.day, bg=bg, fg=fg,
                         font=self.f_cal_day).pack(side="left", padx=4)
                # 日期旁的信息槽优先级：节日名(红) > 节气(绿) > 农历(灰)
                slot, slot_fg, slot_bold = None, COLOR["text_sub"], False
                if hname and self.show_holiday:
                    slot, slot_fg, slot_bold = holiday_disp(hname), COLOR["danger"], True
                elif self.show_terms and term:
                    slot, slot_fg, slot_bold = term, "#059669", True
                elif show_lunar_eff and ltext:
                    slot = ltext
                if slot:
                    tk.Label(top, text=slot, bg=bg, fg=slot_fg,
                             font=self.f_cal_head if slot_bold else self.font_small
                             ).pack(side="left")
                if n:
                    tk.Label(top, text=str(n), bg=bg, fg=self.accent,
                             font=self.f_cal_head).pack(side="right", padx=4)
                em = emarks.get(d.day) if in_month else None
                if em:  # 🎂 生日/纪念日、⏳ 倒数日到点：角标（任务数左侧）
                    tk.Label(top, text=em, bg=bg,
                             font=self.font_small).pack(side="right", padx=(0, 3))
                if in_month and self.show_rest and makeup:
                    tk.Label(top, text=T("mark_work"), bg="#dbeafe",
                             fg=COLOR["accent"],
                             font=self.font_small, width=2, justify="center"
                             ).pack(side="right", padx=(0, 4))
                elif in_month and self.show_rest and is_rest:
                    tk.Label(top, text=T("mark_rest"), bg="#fee2e2",
                             fg=COLOR["danger"],
                             font=self.font_small, width=2, justify="center"
                             ).pack(side="right", padx=(0, 4))
                day_tasks = db_tasks_on(self.conn, d.isoformat()) if in_month else []
                for _tid, t, dn, _r, _rm, imp, pin in day_tasks[:3]:
                    if pin:
                        t = "📌 " + t
                    tk.Label(cell, text=t[:12], bg=bg, anchor="w",
                             fg=(COLOR["danger"] if imp and not dn
                                 else COLOR["done"] if dn else self.task_fg),
                             font=self.f_cal_task_done if dn else self.f_cal_task
                             ).pack(fill="x", padx=5)
                if in_month and n > 3:
                    tk.Label(cell, text=T("more_tasks", n=n), bg=bg, anchor="w",
                             fg=self.accent, font=self.font_small).pack(fill="x", padx=5)
                # Tk 没有事件冒泡：点子控件时事件只发给该子控件，不会自动传给父控件。
                # 以前只给 cell 和 top 绑定，结果点到格子里的任务标题等 Label 上毫无反应
                # （表现就是"有任务的日期点不动，空格子反而能切"）。必须递归绑定到所有后代。
                _bind_click_tree(cell, lambda e, dd=d: self.select_day(dd))

    def render_day_panel(self):
        """右侧面板：所选日期的任务清单（勾选完成 / ✕删除 / 双击编辑 / 右键菜单）"""
        d = self.sel_date
        week = weekday_names()[d.weekday()]          # 当前语言的星期名
        mark = T("today_mark") if d == self.today else ""
        self.lbl_sel.config(text=T("day_header", m=d.month, d=d.day,
                                   week=week, mark=mark))
        tasks = db_tasks_on(self.conn, d.isoformat())
        inner = self.task_area.inner
        for w in inner.winfo_children():  # 清空旧内容后重建
            w.destroy()
        if not tasks:
            tk.Label(inner, text=T("empty_hint"),
                     bg=self.bg_color, fg=COLOR["text_other"], font=self.font_base,
                     justify="center", pady=24).pack(fill="x")
        for tid, title, done, rep, rtime, imp, pin in tasks:
            row = tk.Frame(inner, bg=self.bg_color, pady=3)
            row.pack(fill="x")
            var = tk.BooleanVar(value=bool(done))
            tk.Checkbutton(row, variable=var, bg=self.bg_color,
                           activebackground=self.bg_color,
                           command=lambda t=tid, v=var: self.toggle_task(t, v.get())
                           ).pack(side="left")
            tag_text = T("tag_" + rep if rep in TYPE_ORDER else "tag_day")
            tag_bg = TYPE_COLORS.get(rep, TYPE_COLORS["day"])
            tag_lbl = tk.Label(row, text=tag_text, bg=tag_bg, fg=COLOR["text"],
                               font=self.font_small, cursor="hand2", width=2,
                               justify="center")
            tag_lbl.pack(side="left", padx=(2, 4))
            disp_title = ("📌 " + title) if pin else title
            if imp and not done:
                tf, fg = self.font_base, COLOR["danger"]  # 重要任务红色显示
            elif done:
                tf, fg = self.font_done, COLOR["done"]
            else:
                tf, fg = self.font_base, self.task_fg  # 内容文字颜色可设置
            title_lbl = tk.Label(row, text=disp_title, bg=self.bg_color, fg=fg,
                                 font=tf, anchor="w")
            title_lbl.pack(side="left", fill="x", expand=True)
            tk.Button(row, text="✕", bd=0, bg=self.bg_color, fg=COLOR["text_sub"],
                      font=self.font_small, cursor="hand2",
                      command=lambda t=tid: self.delete_task(t)).pack(side="right")
            if rtime:
                tk.Label(row, text=f"⏰{rtime}", bg=self.bg_color, fg=self.accent,
                         font=self.font_small).pack(side="right", padx=(0, 4))
            tag_lbl.bind("<Button-1>", lambda e, t=tid: self.cycle_type(t))
            # 右键：编辑/提醒/重要/置顶；双击：打开编辑弹窗
            for w in (row, title_lbl, tag_lbl):
                w.bind("<Button-3>", lambda e, t=tid: self.show_task_menu(e, t))
                w.bind("<Double-1>", lambda e, t=tid: self.edit_task(t))
        pending = sum(1 for _, _, dn, _r, _rm, _i, _p in tasks if not dn)
        self.lbl_day_stat.config(text=T("day_stat", p=pending, n=len(tasks)))

    def render_list(self):
        self.tree.delete(*self.tree.get_children())
        for tid, dstr, title, done, rep, rtime, imp, pin in db_tasks_all(self.conn):
            try:
                d = date.fromisoformat(dstr)
            except ValueError:
                continue  # 跳过脏数据行，避免整页刷新崩掉
            # 状态列：已完成(灰) / 逾期(红) / 今天(蓝) / 未来(默认)，重要未完成标红
            if done:
                status, tag = T("st_done"), "done"
            elif d < self.today:
                status, tag = T("st_overdue"), "overdue"
            elif d == self.today:
                status, tag = T("st_today"), "today"
            else:
                status, tag = T("st_future"), ""
            if imp and not done:
                tag = "imp"
            tname = T("type_" + rep if rep in TYPE_ORDER else "type_day")
            disp_title = ("📌 " + title) if pin else title
            self.tree.insert("", "end", iid=str(tid),
                             values=(dstr, status, tname, rtime or "—", disp_title),
                             tags=(tag,))

    # ---------------- 动作 ----------------
    def shift_month(self, delta: int):
        y, m = self.view_year, self.view_month + delta
        if m == 0:
            y, m = y - 1, 12
        elif m == 13:
            y, m = y + 1, 1
        self.view_year, self.view_month = y, m
        self.refresh()

    def go_today(self):
        self.view_year, self.view_month = self.today.year, self.today.month
        self.sel_date = self.today
        self.notebook.select(0)
        self.refresh()

    def select_day(self, d: date):
        self.sel_date = d
        self.view_year, self.view_month = d.year, d.month
        self.refresh()

    def sync_type_selectors(self):
        """按任务类型切换附加选择器：周任务选星期+每N周、月任务选当月几号，
        工作日任务无附加项，默认跟随当前选中日期"""
        self.cmb_weekday.pack_forget()
        self.cmb_winterval.pack_forget()
        self.cmb_mday.pack_forget()
        names = weekday_names()  # 当前语言的星期名（与 date.weekday() 对齐）
        t = self.cmb_type.get()
        if t == T("type_week"):
            self.cmb_weekday.set(names[self.sel_date.weekday()])
            self.cmb_weekday.pack(side="left")
            self.cmb_winterval.pack(side="left", padx=(4, 0))
        elif t == T("type_month"):
            self.cmb_mday.set(str(self.sel_date.day))
            self.cmb_mday.pack(side="left")

    def _toggle_remind_ui(self):
        """勾选「提醒」激活时/分下拉并预填下一个 5 分钟整点；取消勾选则禁用（不提醒）"""
        if self.var_remind.get():
            base = datetime.now().replace(second=0, microsecond=0)
            base += timedelta(minutes=5 - base.minute % 5)
            self.cmb_hour.set(f"{base.hour:02d}")
            self.cmb_min.set(f"{base.minute:02d}")
            state = "readonly"
        else:
            state = "disabled"
        self.cmb_hour.config(state=state)
        self.cmb_min.config(state=state)

    def add_task(self):
        """添加任务：日任务 = 所选日期（只 1 条）；
        周任务（可每 N 周）/ 月任务 / 工作日任务 = **一次性生成未来各期**（同 series_id，
        每期各自可勾选完成、各自到点提醒），生成到窗口截止日为止
        （周任务约 10 期、月任务约 13 期、工作日约 10 周；跨天时再自动续一期）。
        工作日任务按当前国家规则跳过周末与法定节假日（调休补班照常算工作日）。
        提醒时间来自下拉选择，各期沿用同一时间。"""
        title = self.ent_task.get().strip()
        if not title:  # 没有内容就不添加（静默返回，避免打断输入）
            # 焦点刚被「添加」按钮拿走，还回输入框：用户可直接继续打字，
            # 也避免 _ime_guard_restore 在 60ms 后把窗口压回底层/收走键盘
            self.ent_task.focus_set()
            return
        # 显示名（随语言）-> 类型键
        rep = {T("type_day"): "day", T("type_week"): "week",
               T("type_month"): "month",
               T("type_workday"): "workday"}.get(self.cmb_type.get(), "day")
        # 勾选了「提醒」且时/分都有值才记提醒时间，否则为空（不提醒）
        rtime = f"{self.cmb_hour.get()}:{self.cmb_min.get()}"
        if not self.var_remind.get() or not self._valid_time(rtime):
            rtime = ""
        interval = 1
        d = self.sel_date
        if rep == "week":  # 周任务：当前所选周的星期几，本周该天已过则顺延到下周
            names = weekday_names()
            wd_txt = self.cmb_weekday.get()
            wd = names.index(wd_txt) if wd_txt in names else d.weekday()
            d = d - timedelta(days=d.weekday()) + timedelta(days=wd)
            if d < self.today:
                d += timedelta(days=7)
            interval = (1, 2, 3, 4, 6)[self.cmb_winterval.current()]
        elif rep == "month":  # 月任务：当月几号（超出月长截断到月末），已过则顺延到下月
            mday = int(self.cmb_mday.get() or d.day)
            d = date(d.year, d.month, min(mday, calendar.monthrange(d.year, d.month)[1]))
            if d < self.today:
                y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
                d = date(y, m, min(mday, calendar.monthrange(y, m)[1]))
        elif rep == "workday":  # 工作日任务：锚点落在最近的工作日（今天算则用今天）
            d = next_workday(max(d, self.today))
        # 周/月/工作日任务：首期 + 后续各期一起插入（共享 series_id）；日任务只插 1 条
        sid = new_series_id() if rep in SERIES_KINDS else ""
        dates = series_dates(d, rep, series_horizon_end(rep, self.today), interval)
        if rep in SERIES_KINDS:
            # v1.7.2 防重复：同名同类型任务已有期次落在相同日期时先确认。
            # 手滑重复添加（以为没加上再输一遍）会造出两条并行系列，
            # 之后每个同星期几都出现两条同名任务
            hit = self.conn.execute(
                "SELECT MIN(task_date), COUNT(*) FROM tasks "
                "WHERE title = ? AND repeat = ? AND task_date IN (%s)"
                % ",".join("?" * len(dates)),
                (title, rep, *[x.isoformat() for x in dates])).fetchone()
            if hit and hit[1] and not messagebox.askyesno(
                    T("warn_title"),
                    T("dup_series_ask", t=title, n=hit[1], d=hit[0]),
                    parent=self):
                return
        self.conn.executemany(
            "INSERT INTO tasks (task_date, title, repeat, remind_time, series_id, "
            "interval) VALUES (?, ?, ?, ?, ?, ?)",
            [(x.isoformat(), title, rep, rtime, sid, interval) for x in dates])
        self.conn.commit()
        self.ent_task.delete(0, "end")
        if sid:
            self._flash_tip(T("series_tip", n=len(dates),
                              d=dates[-1].isoformat()))
        self.sel_date = d  # 跳到新任务所在日期，右侧面板立刻能看到它
        self.view_year, self.view_month = d.year, d.month
        self.refresh()
        # focus_set 放在 refresh 之后：refresh 会销毁重建面板与网格的控件，
        # 重建完成后再把焦点还给输入框，保证连续录入始终有焦点可打字
        self.ent_task.focus_set()

    @staticmethod
    def _valid_time(text: str) -> bool:
        return bool(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", text))

    def show_task_menu(self, event, tid: int):
        """任务右键菜单：编辑 / 提醒 / 重要 / 置顶 / 删除（系列任务可删整系列）"""
        row = self.conn.execute(
            "SELECT remind_time, important, pinned, series_id FROM tasks WHERE id = ?",
            (tid,)
        ).fetchone()
        if not row:
            return
        rtime, imp, pin, sid = row
        n = series_count(self.conn, sid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=T("menu_edit"),
                         command=lambda: self.edit_task(tid))
        menu.add_command(label=T("menu_remind"),
                         command=lambda: self.edit_reminder(tid, rtime))
        menu.add_command(label=T("menu_clear_remind"),
                         command=lambda: self.set_reminder(tid, ""))
        menu.add_separator()
        menu.add_command(label=T("menu_imp") if not imp else T("menu_unimp"),
                         command=lambda: self.toggle_flag(tid, "important"))
        menu.add_command(label=T("menu_pin") if not pin else T("menu_unpin"),
                         command=lambda: self.toggle_flag(tid, "pinned"))
        menu.add_separator()
        menu.add_command(label=T("menu_del"),
                         command=lambda: self.delete_task(tid))
        if sid and n > 1:  # 周期系列：可一次删掉整条系列
            title = self.conn.execute(
                "SELECT title FROM tasks WHERE id = ?", (tid,)).fetchone()
            menu.add_command(
                label=T("menu_del_series", n=n),
                command=lambda: self.delete_series(sid, title[0] if title else ""))
        menu.tk_popup(event.x_root, event.y_root)

    def delete_series(self, sid: str, title: str):
        """删除整条周期系列（各期一起删）；删除前弹窗确认，避免误删一片"""
        if not sid:
            return
        n = series_count(self.conn, sid)
        if n <= 1:
            return
        if not messagebox.askyesno(T("warn_title"),
                                   T("del_series_ask", t=title, n=n),
                                   parent=self):
            return
        self.conn.execute("DELETE FROM tasks WHERE series_id = ?", (sid,))
        self.conn.execute("DELETE FROM series_skips WHERE series_id = ?", (sid,))
        self.conn.commit()
        self.refresh()

    def toggle_flag(self, tid: int, column: str):
        assert column in ("important", "pinned")
        self.conn.execute(
            f"UPDATE tasks SET {column} = 1 - {column} WHERE id = ?", (tid,))
        self.conn.commit()
        self.refresh()

    def edit_reminder(self, tid: int, current: str):
        """单独改提醒：弹窗下拉选择时:分（分钟 5 分钟步进）；
        取消勾选「开启提醒」再确定 = 清除提醒"""
        win = tk.Toplevel(self)
        win.title(T("remind_win_title"))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        frm = tk.Frame(win, padx=14, pady=10)
        frm.pack()
        var = tk.BooleanVar(value=bool(current))  # 已有提醒则默认勾选
        cur_h, cur_m = current.split(":") if self._valid_time(current or "") \
            else ("09", "00")
        hcb = ttk.Combobox(frm, width=3, state="readonly", font=self.font_base,
                           values=[f"{h:02d}" for h in range(24)])   # 时 00~23
        hcb.set(cur_h)
        mcb = ttk.Combobox(frm, width=3, state="readonly", font=self.font_base,
                           values=[f"{m:02d}" for m in range(0, 60, 5)])  # 分 5 步进
        mcb.set(cur_m)

        def sync_state():
            state = "readonly" if var.get() else "disabled"  # 未勾选时置灰
            hcb.config(state=state)
            mcb.config(state=state)

        tk.Checkbutton(frm, text=T("enable_remind"), variable=var,
                       font=self.font_base,
                       command=sync_state).grid(row=0, column=0, columnspan=5,
                                                sticky="w")
        tk.Label(frm, text=T("time_label"), font=self.font_base).grid(
            row=1, column=0, sticky="w", pady=(10, 0))
        hcb.grid(row=1, column=1, pady=(10, 0))
        tk.Label(frm, text=":", font=self.font_base).grid(
            row=1, column=2, pady=(10, 0))
        mcb.grid(row=1, column=3, pady=(10, 0))
        tk.Label(frm, text=T("min_step"), font=self.font_small,
                 fg=COLOR["text_sub"]).grid(row=1, column=4, sticky="w",
                                            padx=(8, 0), pady=(10, 0))

        def on_ok():
            self.set_reminder(
                tid, f"{hcb.get()}:{mcb.get()}" if var.get() else "")
            win.destroy()

        btns = tk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=5, sticky="e", pady=(12, 0))
        tk.Button(btns, text=T("btn_ok"), font=self.font_base, width=6,
                  command=on_ok).pack(side="left")
        tk.Button(btns, text=T("btn_cancel"), font=self.font_base, width=6,
                  command=win.destroy).pack(side="left", padx=(6, 0))
        sync_state()
        win.bind("<Return>", lambda e: on_ok())  # 回车即确定
        win.grab_set()

    def edit_task(self, tid: int):
        """编辑已有任务：标题 / 类型 / 日期 / 提醒一次改齐，点「保存」写库。

        入口有三处：右键菜单「✏️ 编辑任务」、双击任务行、全部清单页「✏️ 编辑选中」。
        若是周期系列（周/月任务），多一行「应用到整个系列」：
        - 只改内容（标题 / 提醒）-> 同步到本条及之后各期；
        - 改日期或类型 -> 以新日期为新锚点，撤掉其余未完成的期次后重新排期
          （已完成的期次作为历史保留，不动）。
        改提醒会重置已弹标记，到点重新弹窗。"""
        row = self.conn.execute(
            "SELECT title, task_date, repeat, remind_time, series_id FROM tasks "
            "WHERE id = ?", (tid,)).fetchone()
        if not row:
            return
        title, dstr, rep, rtime, sid = row
        n_series = series_count(self.conn, sid)
        win = tk.Toplevel(self)
        win.title(T("edit_title"))
        win.resizable(False, False)
        win.transient(self)              # 归属主窗口：任务栏不额外多一个图标
        win.attributes("-topmost", True)
        frm = tk.Frame(win, padx=14, pady=10)
        frm.pack()
        # —— 任务内容（回车即保存）——
        tk.Label(frm, text=T("edit_task"), font=self.font_base).grid(
            row=0, column=0, columnspan=4, sticky="w")
        ent = tk.Entry(frm, width=34, font=self.font_base)
        ent.insert(0, title)
        ent.grid(row=1, column=0, columnspan=4, sticky="we", pady=(2, 8))
        ent.focus_set()
        ent.select_range(0, "end")  # 全选方便直接覆盖输入
        # —— 类型 + 日期 ——
        tk.Label(frm, text=T("edit_type"), font=self.font_small).grid(
            row=2, column=0, sticky="w")
        cb_type = ttk.Combobox(frm, width=10, state="readonly",
                               font=self.font_small,
                               values=[T("type_day"), T("type_week"),
                                       T("type_month"), T("type_workday")])
        cb_type.set(T("type_" + rep if rep in TYPE_ORDER else "type_day"))
        cb_type.grid(row=2, column=1, sticky="w", padx=(4, 12))
        tk.Label(frm, text=T("edit_date"), font=self.font_small).grid(
            row=2, column=2, sticky="e")
        ent_date = DateSpin(frm, self.font_small)
        try:
            ent_date.set_date(date.fromisoformat(dstr))
        except ValueError:            # 库里脏数据兜底：退回今天
            ent_date.set_date(self.today)
        ent_date.grid(row=2, column=3, sticky="w", padx=(4, 0))
        # —— 提醒（勾选 + 时/分下拉，与添加栏一致）——
        var = tk.BooleanVar(value=bool(rtime))
        cur_h, cur_m = rtime.split(":") if self._valid_time(rtime or "") \
            else ("09", "00")
        # 时/分下拉必须挂在 rrow（pack 布局）上：挂到 frm 的话，frm 已用 grid
        # 管理其它控件，pack 会抛 TclError，弹窗残缺、连确定按钮都建不出来
        rrow = tk.Frame(frm)
        rrow.grid(row=4, column=0, columnspan=4, sticky="w", pady=(2, 0))
        hcb = ttk.Combobox(rrow, width=3, state="readonly", font=self.font_small,
                           values=[f"{h:02d}" for h in range(24)])
        hcb.set(cur_h)
        mcb = ttk.Combobox(rrow, width=3, state="readonly", font=self.font_small,
                           values=[f"{m:02d}" for m in range(0, 60, 5)])
        mcb.set(cur_m)

        def sync_state():
            st = "readonly" if var.get() else "disabled"
            hcb.config(state=st)
            mcb.config(state=st)

        tk.Checkbutton(frm, text=T("enable_remind"), variable=var,
                       font=self.font_small, command=sync_state).grid(
                row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        tk.Label(rrow, text=T("edit_remind"), font=self.font_small).pack(side="left")
        hcb.pack(side="left", padx=(6, 0))
        tk.Label(rrow, text=":", font=self.font_small).pack(side="left")
        mcb.pack(side="left")
        tk.Label(rrow, text=T("min_step"), font=self.font_small,
                 fg=COLOR["text_sub"]).pack(side="left", padx=(8, 0))
        # —— 周期系列：整系列同步（仅周/月任务显示）——
        var_apply = tk.BooleanVar(value=bool(sid))
        next_row = 5
        if sid and n_series > 1:
            srow = tk.Frame(frm)
            srow.grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))
            tk.Checkbutton(srow, text=T("apply_series"), variable=var_apply,
                           font=self.font_small).pack(side="left")
            last_d = self.conn.execute(
                "SELECT MAX(task_date) FROM tasks WHERE series_id = ?",
                (sid,)).fetchone()[0] or dstr
            tk.Label(frm, text=T("series_count", n=n_series, d=last_d),
                     font=self.font_small, fg=COLOR["text_sub"]).grid(
                row=6, column=0, columnspan=4, sticky="w")
            next_row = 7

        def on_ok():
            """校验输入后写库：标题非空、日期合法，提醒随勾选生成或清空"""
            new_title = ent.get().strip()
            if not new_title:
                messagebox.showwarning(T("warn_title"), T("no_empty_title"),
                                       parent=win)
                return
            new_date = ent_date.get_date()
            if new_date is None:
                messagebox.showwarning(T("warn_title"), T("calc_bad_date"),
                                       parent=win)
                return
            # 显示名（随语言）-> 类型键
            new_rep = {T("type_day"): "day", T("type_week"): "week",
                       T("type_month"): "month",
                       T("type_workday"): "workday"}.get(cb_type.get(), rep)
            new_rt = f"{hcb.get()}:{mcb.get()}" if var.get() else ""
            apply_all = bool(sid) and var_apply.get() and n_series > 1
            if sid and new_rep in SERIES_KINDS:
                # v1.7.2 防重复：同系列已有一期落在目标日期时拦截——单条改日期
                # 撞上另一期会造成同系列同日两条（数据库唯一索引也会拒写）
                clash = self.conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE series_id = ? "
                    "AND task_date = ? AND id != ?",
                    (sid, new_date.isoformat(), tid)).fetchone()[0]
                if clash:
                    messagebox.showwarning(T("warn_title"),
                                           T("edit_clash", d=new_date.isoformat()),
                                           parent=win)
                    return
            if apply_all:
                # 周期系列整体系列更新：历史（已完成）期次一律保留不动
                if new_rep not in SERIES_KINDS:
                    # 改回日任务：撤掉其余未完成的期次，本条脱离系列
                    self.conn.execute(
                        "DELETE FROM tasks WHERE series_id = ? AND id != ? "
                        "AND done = 0", (sid, tid))
                    self.conn.execute(
                        "UPDATE tasks SET title = ?, task_date = ?, repeat = ?, "
                        "remind_time = ?, last_remind = '', series_id = '' "
                        "WHERE id = ?",
                        (new_title, new_date.isoformat(), new_rep, new_rt, tid))
                elif (new_rep != rep) or (new_date.isoformat() != dstr):
                    # 换锚点 / 换周期：撤掉其余未完成期次，本条改成新规则再重排
                    self.conn.execute(
                        "DELETE FROM tasks WHERE series_id = ? AND id != ? "
                        "AND done = 0", (sid, tid))
                    self.conn.execute(
                        "UPDATE tasks SET title = ?, task_date = ?, repeat = ?, "
                        "remind_time = ?, last_remind = '' WHERE id = ?",
                        (new_title, new_date.isoformat(), new_rep, new_rt, tid))
                    self.conn.commit()
                    expand_series(self.conn, date.today())
                else:
                    # 只改内容：本条及之后各期同步（不改各自日期）
                    self.conn.execute(
                        "UPDATE tasks SET title = ?, remind_time = ?, "
                        "last_remind = '' WHERE series_id = ? AND task_date >= ?",
                        (new_title, new_rt, sid, dstr))
            else:
                # 单条更新（改提醒后 last_remind 清空，到点会重新弹窗）
                self.conn.execute(
                    "UPDATE tasks SET title = ?, task_date = ?, repeat = ?, "
                    "remind_time = ?, last_remind = '' WHERE id = ?",
                    (new_title, new_date.isoformat(), new_rep, new_rt, tid))
            self.conn.commit()
            self.sel_date = new_date                    # 跳到新日期便于确认
            self.view_year, self.view_month = new_date.year, new_date.month
            win.destroy()
            self.refresh()

        btns = tk.Frame(frm)
        btns.grid(row=next_row, column=0, columnspan=4, sticky="e", pady=(12, 0))
        tk.Button(btns, text=T("btn_save"), font=self.font_base, width=6,
                  command=on_ok).pack(side="left")
        tk.Button(btns, text=T("btn_cancel"), font=self.font_base, width=6,
                  command=win.destroy).pack(side="left", padx=(6, 0))
        sync_state()
        win.bind("<Return>", lambda e: on_ok())     # 回车即保存
        win.grab_set()
        win.lift()                                   # 贴桌面模式下也确保弹窗在最前
        win.focus_force()

    def edit_selected(self):
        """全部清单页：编辑选中（单条）；双击仍是切换完成状态"""
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo(T("warn_title"), T("no_selection"), parent=self)
            return
        self.edit_task(ids[0])

    def set_reminder(self, tid: int, rtime: str):
        self.conn.execute(
            "UPDATE tasks SET remind_time = ?, last_remind = '' WHERE id = ?",
            (rtime, tid),
        )
        self.conn.commit()
        self.refresh()

    # ---------------- 提醒 ----------------
    def check_reminders(self):
        """每 30 秒扫描一次：未完成且设了提醒的任务，到达「任务日期 + 提醒时间」即弹窗。
        设置了提前提醒（设置里）时，到期前再提前弹一次「即将开始」——只本地弹窗，
        不推企业微信。当天有生日/纪念日/倒数日到点时每天弹一次祝贺（check_event_day）。
        日/周/月任务顺延后日期变化，提醒键随之更新，自然实现按周期重复提醒。"""
        try:
            now = datetime.now()
            rows = self.conn.execute(
                "SELECT id, task_date, title, remind_time, last_remind FROM tasks "
                "WHERE done = 0 AND remind_time != ''"
            ).fetchall()
            due, early = [], []
            for tid, dstr, title, rtime, last in rows:
                key = f"{dstr} {rtime}"
                try:
                    due_dt = datetime.strptime(f"{dstr} {rtime}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                if now >= due_dt:
                    if last != key:
                        due.append((tid, dstr, title, rtime))
                    continue
                n = self.remind_early
                if n > 0:
                    e_key = f"{key}#e{n}"
                    if last not in (e_key, key) and \
                            now >= due_dt - timedelta(minutes=n):
                        early.append((tid, dstr, title, rtime, n))
            updates = ([(f"{d} {t}", tid) for tid, d, _t, t in due] +
                       [(f"{d} {t}#e{n}", tid) for tid, d, _t, t, n in early])
            if updates:
                self.conn.executemany(
                    "UPDATE tasks SET last_remind = ? WHERE id = ?", updates)
                self.conn.commit()
            if early:
                # 提前提醒：标题换成「即将开始」，行尾带剩余提前量
                self.show_reminder_toast(
                    [(tid, d, t, rt, n) for tid, d, t, rt, n in early],
                    title_key="toast_early", allow_done=False)
            if due:
                self.show_reminder_toast(due)
                if self.wecom_push:
                    content = self.format_wecom_reminder(due)
                    threading.Thread(target=lambda: self.notify_wecom(content, silent=True),
                                     daemon=True).start()
            self.check_event_day()
        finally:
            self.after(30_000, self.check_reminders)  # 放 finally：出错也不能让提醒停摆

    def check_event_day(self):
        """当天有生日/纪念日（农历自动换算）或倒数日到点时，每天弹一次提示"""
        try:
            today = self.today
            kday = f"event_toast_{today.isoformat()}"
            if kv_get(self.conn, kday):
                return
            lines = []
            for _eid, name, dstr, kind, lunar in db_events(self.conn):
                try:
                    d0 = date.fromisoformat(dstr)
                except ValueError:
                    continue
                if kind == "annual":
                    if lunar:
                        tgt = lunar_annual_date(d0, today.year)
                    else:
                        try:
                            tgt = d0.replace(year=today.year)
                        except ValueError:      # 2/29 -> 平年无对应日
                            tgt = None
                    hit = (tgt == today)
                else:
                    hit = (d0 == today)
                if hit:
                    icon = "🎂" if kind == "annual" else "⏳"
                    lines.append(f"{today.isoformat()}　{icon} {name}")
            if lines:
                kv_set(self.conn, kday, "1")
                self.show_reminder_toast(
                    [(0, today.isoformat(), ln, "") for ln in lines],
                    title_key="toast_event", allow_done=False)
        except Exception:  # noqa: BLE001  事件提示失败不影响提醒主流程
            pass

    def notify_wecom(self, content: str, parent=None, silent: bool = False):
        """把消息发到所有已配置的企业微信通道（群机器人 / 自建应用），后台线程执行"""
        channels = []
        if self.wecom_webhook:
            channels.append(("群机器人",
                             lambda: wecom_push(self.wecom_webhook, content)))
        if self.wecom_corp_id and self.wecom_agent_id and self.wecom_corp_secret:
            channels.append(("企业微信应用",
                             lambda: wecom_app_push(self.wecom_corp_id,
                                                    self.wecom_agent_id,
                                                    self.wecom_corp_secret, content)))
        if not channels:
            if not silent:
                messagebox.showwarning(
                    T("wecom_fail"), T("no_wecom_cfg"),
                    parent=parent or self)
            return

        def work():
            results = [(name, *fn()) for name, fn in channels]
            ok = [n for n, success, _e in results if success]
            fails = [f"{n}：{e}" for n, success, e in results if not success]
            if fails and not silent:
                self.after(0, lambda: messagebox.showwarning(
                    T("wecom_fail"), "\n".join(fails), parent=parent or self))
            elif not silent:
                msg = (T("wecom_result_ok", names="、".join(ok))
                       if ok else T("wecom_result_sent"))
                self.after(0, lambda: messagebox.showinfo(
                    T("wecom_fail"), msg, parent=parent or self))

        threading.Thread(target=work, daemon=True).start()

    def format_wecom_reminder(self, due_items):
        """提醒的企业微信 markdown 正文（标题随界面语言）"""
        lines = [T("wecom_remind_head")]
        for _tid, dstr, title, rtime in due_items:
            lines.append(f"> {dstr[5:]} {rtime}　{title}")
        return "\n".join(lines)

    def push_today_to_wecom(self, parent=None):
        """推送今日任务：弹出勾选框，只推送选中的任务"""
        if not (self.wecom_webhook or
                (self.wecom_corp_id and self.wecom_agent_id and self.wecom_corp_secret)):
            messagebox.showwarning(
                T("wecom_fail"), T("no_wecom_cfg2"),
                parent=parent or self)
            return
        tasks = db_tasks_on(self.conn, self.today.isoformat())
        if not tasks:
            messagebox.showinfo(T("wecom_fail"), T("no_tasks_today"),
                                parent=parent or self)
            return

        win = tk.Toplevel(parent or self)
        win.title(T("wecom_fail"))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        frm = tk.Frame(win, padx=14, pady=10)
        frm.pack()
        tk.Label(frm, text=T("push_pick", m=self.today.month, d=self.today.day),
                 font=self.font_base).pack(anchor="w", pady=(0, 6))

        area = ScrollFrame(frm, bg="#ffffff")
        area.pack(fill="both")
        checks = []
        for tid, title, done, rep, rtime, imp, pin in tasks:
            var = tk.BooleanVar(value=not done)  # 默认勾选未完成
            mark = "✅" if done else ("🔴" if imp else "▫️")
            text = ("📌 " if pin else "") + title + (f"（⏰{rtime}）" if rtime else "")
            tk.Checkbutton(area.inner, text=f"{mark} {text}", variable=var,
                           bg="#ffffff", anchor="w", font=self.font_base,
                           justify="left").pack(fill="x", anchor="w")
            checks.append((var, tid, title, done, rep, rtime, imp, pin))

        btns = tk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))

        def set_all(v):
            for var, *_rest in checks:
                var.set(v)

        tk.Button(btns, text=T("select_all"), font=self.font_small, width=6,
                  command=lambda: set_all(True)).pack(side="left")
        tk.Button(btns, text=T("select_none"), font=self.font_small, width=6,
                  command=lambda: set_all(False)).pack(side="left", padx=4)

        def do_push():
            sel = [row for row in checks if row[0].get()]
            if not sel:
                messagebox.showwarning(T("wecom_fail"), T("push_need_one"),
                                       parent=win)
                return
            day = self.today
            lines = [T("push_lines", m=day.month, d=day.day, n=len(sel))]
            for _var, _tid, title, done, _rep, rtime, imp, pin in sel:
                mark = "✅" if done else ("🔴" if imp else "▫️")
                text = ("📌 " if pin else "") + title
                if rtime:
                    text += f"（⏰{rtime}）"
                lines.append(f"{mark} {text}")
            win.destroy()
            self.notify_wecom("\n".join(lines), parent=parent)

        tk.Button(btns, text=T("push"), font=self.font_base, width=8,
                  command=do_push).pack(side="right")
        tk.Button(btns, text=T("btn_cancel"), font=self.font_base, width=8,
                  command=win.destroy).pack(side="right", padx=4)
        win.grab_set()

    def show_reminder_toast(self, due_items, title_key="toast_title",
                            allow_done=True):
        """右下角提醒弹窗。due_items 为 (tid, 日期, 标题, 提醒时间[, 提前分钟数])：
        带第 5 个元素时是「提前提醒」，行尾显示剩余提前量。
        allow_done=False 时（提前提醒/事件祝贺）不显示「全部完成」按钮。"""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:  # noqa: BLE001
            self.bell()
        toast = tk.Toplevel(self)
        toast.title(T(title_key))
        toast.attributes("-topmost", True)
        toast.resizable(False, False)
        tk.Label(toast, text=T(title_key), fg=COLOR["danger"],
                 font=("Microsoft YaHei UI", 13, "bold"), pady=6).pack()
        box = tk.Frame(toast, padx=14)
        box.pack()
        for item in due_items:
            tid, dstr, title, rtime = item[:4]
            line = f"{dstr[5:]} {rtime}　{title}"
            if len(item) > 4 and item[4]:
                line = f"{rtime}　{title}　（{T('early_in', n=human_span(item[4]))}）"
            tk.Label(box, text=line,
                     font=self.font_base, anchor="w").pack(fill="x", pady=1)
        btns = tk.Frame(toast, pady=10)
        btns.pack()
        real = [it for it in due_items if it[0]]

        def mark_done():
            for it in real:
                self.conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (it[0],))
            self.conn.commit()
            toast.destroy()
            self.refresh()

        if allow_done and real:
            tk.Button(btns, text=T("toast_all_done"), font=self.font_base,
                      command=mark_done).pack(side="left", padx=6)
        tk.Button(btns, text=T("toast_got"), font=self.font_base,
                  command=toast.destroy).pack(side="left", padx=6)

        # 从屏幕右下角滑入，停靠在任务栏上方的右下角（工作区不含任务栏）
        toast.update_idletasks()
        w, h = toast.winfo_reqwidth(), toast.winfo_reqheight()
        area = _primary_work_area()
        sw, sh = area if area else (self.winfo_screenwidth(), self.winfo_screenheight())
        x1, y1 = sw - w - 16, sh - h - 16
        toast.geometry(f"+{sw - 16}+{sh - 16}")
        self._slide_in(toast, sw - 16, sh - 16, x1, y1, 0)
        toast.after(120_000, toast.destroy)

    def _slide_in(self, win, x0, y0, x1, y1, step, steps=10, delay=15):
        """提醒弹窗从屏幕右下角滑入（ease-out 缓动）"""
        if not win.winfo_exists():
            return
        if step >= steps:
            win.geometry(f"+{x1}+{y1}")
            return
        ease = 1 - (1 - (step + 1) / steps) ** 3
        win.geometry(f"+{round(x0 + (x1 - x0) * ease)}+{round(y0 + (y1 - y0) * ease)}")
        win.after(delay, lambda: self._slide_in(win, x0, y0, x1, y1,
                                                step + 1, steps, delay))

    def cycle_type(self, tid: int):
        """点击任务前的类型标签，循环切换 日 -> 周 -> 月 -> 工作日。
        切成周/月/工作日后立刻补齐未来各期（不等下次启动的自动收编）"""
        cur = self.conn.execute("SELECT repeat FROM tasks WHERE id = ?", (tid,)).fetchone()
        if cur:
            order = TYPE_ORDER if cur[0] in TYPE_ORDER else TYPE_ORDER[:1]
            nxt = TYPE_ORDER[(order.index(cur[0]) + 1) % len(TYPE_ORDER)]
            self.conn.execute("UPDATE tasks SET repeat = ? WHERE id = ?", (nxt, tid))
            self.conn.commit()
            if nxt in SERIES_KINDS:
                expand_series(self.conn, date.today())
            self.refresh()

    def toggle_task(self, tid: int, done: bool):
        self.conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(done), tid))
        self.conn.commit()
        self.refresh()

    def delete_task(self, tid: int):
        mark_series_skips(self.conn, [tid])
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        self.conn.commit()
        self.refresh()

    def _selected_ids(self):
        return [int(i) for i in self.tree.selection()]

    def toggle_selected(self):
        for tid in self._selected_ids():
            cur = self.conn.execute("SELECT done FROM tasks WHERE id = ?", (tid,)).fetchone()
            if cur:
                self.conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (1 - cur[0], tid))
        self.conn.commit()
        self.refresh()

    def delete_selected(self):
        ids = self._selected_ids()
        mark_series_skips(self.conn, ids)
        self.conn.executemany("DELETE FROM tasks WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()
        self.refresh()

    def clear_done(self):
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM tasks WHERE done = 1").fetchall()]
        mark_series_skips(self.conn, ids)
        self.conn.executemany("DELETE FROM tasks WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()
        self.refresh()

    # ---------------- 导入 / 导出 ----------------
    def export_tasks(self):
        path = filedialog.asksaveasfilename(
            parent=self, title=T("export_title"), initialdir=str(BASE_DIR),
            initialfile=f"calendar_tasks_{date.today():%Y%m%d}.json",
            defaultextension=".json",
            filetypes=[(T("ft_json"), "*.json"), (T("ft_csv"), "*.csv")])
        if not path:
            return
        rows = db_tasks_all(self.conn)
        tasks = [dict(zip(EXPORT_COLUMNS, r[1:])) for r in rows]
        try:
            if path.lower().endswith(".csv"):
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
                    w.writeheader()
                    w.writerows(tasks)
            else:
                Path(path).write_text(json.dumps({
                    "app": "desktop_calendar", "version": 1,
                    "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(tasks), "tasks": tasks,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            messagebox.showerror(T("export_fail"), T("export_fail_msg").format(e=e),
                            parent=self)
            return
        messagebox.showinfo(T("export_done"),
                            T("export_done_msg").format(n=len(tasks), path=path),
                            parent=self)

    def import_tasks(self):
        path = filedialog.askopenfilename(
            parent=self, title=T("import_title"), initialdir=str(BASE_DIR),
            filetypes=[(T("ft_taskfile"), "*.json;*.csv"),
                       (T("ft_json_plain"), "*.json"), (T("ft_csv_plain"), "*.csv"),
                       (T("ft_all"), "*.*")])
        if not path:
            return
        try:
            items = parse_import_file(path)
        except (OSError, ValueError) as e:
            messagebox.showerror(T("import_fail"), T("import_read_fail").format(e=e),
                            parent=self)
            return
        if not items:
            messagebox.showwarning(T("import_fail"), T("import_none"),
                                   parent=self)
            return
        replace = messagebox.askyesno(
            T("import_title"), T("import_ask").format(n=len(items)),
            parent=self)
        if replace:
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM series_skips")   # 全量覆盖：旧墓碑一并清掉
            added, skipped = 0, 0
            for d, title, done, rep, rtime, imp, pin, sid in group_series_rows(items):
                # 周/月任务按（标题+类型+提醒）归并为系列，随后统一补齐未来各期
                self.conn.execute(
                    "INSERT INTO tasks (task_date, title, done, repeat, remind_time, "
                    "important, pinned, series_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (d, title, done, rep, rtime, imp, pin, sid))
                added += 1
        else:
            existing = {(d, t, r) for d, t, r in self.conn.execute(
                "SELECT task_date, title, remind_time FROM tasks")}
            added, skipped = 0, 0
            for d, title, done, rep, rtime, imp, pin, sid in group_series_rows(items):
                if (d, title, rtime) in existing:
                    skipped += 1
                    continue
                self.conn.execute(
                    "INSERT INTO tasks (task_date, title, done, repeat, remind_time, "
                    "important, pinned, series_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (d, title, done, rep, rtime, imp, pin, sid))
                existing.add((d, title, rtime))
                added += 1
        self.conn.commit()
        self.today = date.today()
        roll_pending_tasks(self.conn, self.today)
        expand_series(self.conn, self.today)   # 导入的周/月任务补齐后续各期
        self.refresh()
        messagebox.showinfo(T("import_done"),
                            T("import_done_msg", a=added, s=skipped),
                            parent=self)

    # ---------------- 字体 ----------------
    def _build_fonts(self):
        """创建日历/任务两组可动态重配置的 Font 对象；apply_fonts 只改属性即可全局刷新"""
        cs, ts = self.cal_size, self.task_size
        self.f_cal_head = tkfont.Font(family=self.cal_family, size=max(7, cs - 1),
                                      weight="bold")
        self.f_cal_day = tkfont.Font(family=self.cal_family, size=cs, weight="bold")
        self.f_cal_task = tkfont.Font(family=self.cal_family, size=max(7, cs - 2))
        self.f_cal_task_done = tkfont.Font(family=self.cal_family, size=max(7, cs - 2),
                                           overstrike=1)
        # 任务字体同时用于任务标题（font_base）与列表页 Treeview
        self.font_base = tkfont.Font(family=self.task_family, size=ts)
        self.font_done = tkfont.Font(family=self.task_family, size=ts, overstrike=1)
        self.font_small = tkfont.Font(family=self.task_family, size=max(7, ts - 2))
        self.font_small_done = tkfont.Font(family=self.task_family, size=max(7, ts - 2),
                                           overstrike=1)
        self.apply_fonts()

    def apply_fonts(self):
        """按当前 cal_family/cal_size、task_family/task_size 重配置所有字体对象，
        引用这些对象的控件（含 Treeview 样式）即时刷新，无需重建界面"""
        cs, ts = self.cal_size, self.task_size
        self.f_cal_head.configure(family=self.cal_family, size=max(7, cs - 1),
                                  weight="bold", overstrike=0)
        self.f_cal_day.configure(family=self.cal_family, size=cs, weight="bold",
                                 overstrike=0)
        self.f_cal_task.configure(family=self.cal_family, size=max(7, cs - 2),
                                  weight="normal", overstrike=0)
        self.f_cal_task_done.configure(family=self.cal_family, size=max(7, cs - 2),
                                       weight="normal", overstrike=1)
        self.font_base.configure(family=self.task_family, size=ts, overstrike=0)
        self.font_done.configure(family=self.task_family, size=ts, overstrike=1)
        self.font_small.configure(family=self.task_family, size=max(7, ts - 2),
                                  overstrike=0)
        self.font_small_done.configure(family=self.task_family, size=max(7, ts - 2),
                                       overstrike=1)
        style = ttk.Style(self)
        style.configure("Task.Treeview", font=self.font_base,
                        foreground=self.task_fg,
                        rowheight=self.task_size + 12)
        if hasattr(self, "tree"):
            self.tree.configure(style="Task.Treeview")

    def _on_configure(self, event):
        """窗口移动/缩放后防抖保存位置，下次启动恢复"""
        if event.widget is not self or self.state() != "normal":
            return
        if self._geom_job:
            self.after_cancel(self._geom_job)
        self._geom_job = self.after(800, self._on_settled)

    def _on_settled(self):
        self._geom_job = None
        if self.state() == "normal":
            self._rescale_bg()   # 窗口尺寸稳定后重铺背景图片
        self.persist_cfg()

    def persist_cfg(self):
        self._geom_job = None
        if self.state() == "normal":
            save_settings({
                "alpha": self.alpha,
                "topmost": self.topmost,
                "language": self.lang,   # 界面语言，启动时读取（切换需重启，见设置里的语言项）
                "country": self.country,  # 当前国家：月历工作日/休息日按国家规则
                "remind_early": self.remind_early,  # 提前提醒分钟数（0=不提前）
                "auto_backup": self.auto_backup,    # 每日自动备份
                "ics_url": self.ics_url,            # ICS 日历订阅网址
                "geometry": _persist_geometry(self),   # 钳制后再落盘（v1.7.3）
                "show_holiday": self.show_holiday,
                "show_weekno": self.show_weekno,
                "show_lunar": self.show_lunar,
                "show_terms": self.show_terms,
                "show_rest": self.show_rest,
                "week_start": self.week_start,
                "cal_fg": self.cal_fg,
                "task_fg": self.task_fg,
                "accent": self.accent,
                "wecom_webhook": self.wecom_webhook,
                "wecom_push": self.wecom_push,
                "wecom_corp_id": self.wecom_corp_id,
                "wecom_agent_id": self.wecom_agent_id,
                "wecom_corp_secret": self.wecom_corp_secret,
                "bg_color": self.bg_color,
                "bg_image_path": self.bg_image_path,
                "embedded": self.embedded,
                "desktop_bottom": self.desktop_bottom,
                "cal_font": {"family": self.cal_family, "size": self.cal_size},
                "task_font": {"family": self.task_family, "size": self.task_size},
            })

    def apply_alpha(self, value: float):
        self.alpha = min(1.0, max(0.5, value))
        self._set_alpha(self.alpha)

    # ---------------- 输入保护（IME / 键盘输入） ----------------
    # 背景：Tk 只要调用过 attributes("-alpha", x) 且 x < 1，窗口就会被加上
    # WS_EX_LAYERED 变成「分层窗口」。分层窗口与中文输入法有已知冲突：
    # IME 的组字窗/候选窗挂不到窗口上，于是点进输入框打不出中文（英文正常），
    # 要来回切几次输入法把 IME 上下文重建了才恢复。
    # 对策：① 透明度接近 1 时直接按 1.0 处理，让 Tk 摘掉分层样式；
    #       ② 确实半透明时，在打字期间临时恢复不透明，输完再还原；
    #       ③ 贴桌面模式常驻的 WS_EX_NOACTIVATE 让窗口永远成不了前台窗口，
    #          键盘输入全部流向当前前台应用——点进输入框任何字都打不出来。
    #          打字期间同样临时摘掉它并抢一次前台（_force_foreground），
    #          输完在 _ime_guard_restore 里与 ② 一起还原。
    # 透明度达到这个值就按「完全不透明」处理，不给窗口加分层样式。
    # 定在 0.95 的理由：95% 以上的半透明肉眼几乎看不出差别，却会让窗口变成
    # WS_EX_LAYERED 分层窗口；而分层窗口在中文输入法激活时会吞掉键盘输入——
    # 实测小写、大写（Shift+字母）全都打不进去。与其留着这点看不见的透明
    # 换来输入失灵，不如 95% 以上一律按不透明处理，从源头避免分层窗口。
    # 真想要明显半透效果，把滑块拉到 95% 以下即可（那时打字期间会自动
    # 临时摘掉分层，输完再还原，见 _on_focus_in）。
    _ALPHA_OPAQUE = 0.95

    _TEXT_CLASSES = ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox")

    def _set_alpha(self, value: float):
        """统一设置透明度的入口。

        接近不透明时按 1.0 处理，并且手动摘掉 WS_EX_LAYERED —— 因为 Tk 设回
        1.0 并不会摘样式位（实测），残留的分层样式会破坏中文输入法。"""
        v = min(1.0, max(0.5, float(value)))
        if v >= self._ALPHA_OPAQUE:
            v = 1.0
        try:
            self.attributes("-alpha", v)
        except Exception:      # noqa: BLE001  # 少数系统/远程桌面下不支持分层窗口
            pass
        if v >= 1.0:
            _set_layered(_toplevel_hwnd(self), False)

    def _is_text_widget(self, w) -> bool:
        """判断控件是否为可输入文本的控件（判断是否要保护输入法）"""
        try:
            return w is not None and w.winfo_class() in self._TEXT_CLASSES
        except Exception:      # noqa: BLE001  # 控件可能已被销毁
            return False

    def _guard_log(self, msg):
        """输入守护日志：打字模式每次进入/还原时记录前台窗口归属，写入
        data/guard.log（超 64KB 自动截尾保留末尾）。「点进输入框打不出字」
        是环境相关的偶发问题，留下取证便于复发时判断是哪一环失效。"""
        if _user32 is None:
            return
        try:
            path = BASE_DIR / "data" / "guard.log"
            if path.exists() and path.stat().st_size > 65536:
                tail = path.read_text(encoding="utf-8", errors="ignore")[-8192:]
                path.write_text(tail, encoding="utf-8")
            hwnd = _toplevel_hwnd(self)
            fg = _user32.GetForegroundWindow()
            where = "fg-ok" if fg == hwnd else f"fg-hwnd={fg}"
            stamp = datetime.now().strftime("%m-%d %H:%M:%S")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg} {where}\n")
        except Exception:  # noqa: BLE001  日志失败绝不影响功能
            pass

    def _on_focus_in(self, event):
        """焦点进入输入框：进入「打字模式」，临时恢复窗口的可输入状态。

        ① 半透明残留的 WS_EX_LAYERED 会让中文输入法失效——摘分层样式；
        ② 贴桌面模式常驻的 WS_EX_NOACTIVATE 让窗口永远成不了前台，键盘
           输入全部流向当前前台应用，点进输入框任何字都打不出来——
           摘掉该样式并把窗口抢到前台（焦点必须落回输入框本身，
           见 _force_foreground 的 child_hwnd 说明）。输完由
           _ime_guard_restore 还原；打字期间前台看门狗随时夺回被抢走的前台。"""
        if not self._is_text_widget(event.widget):
            return
        try:
            if event.widget.winfo_toplevel() is not self:
                return  # 弹窗（编辑/设置等）是普通窗口，天生可激活打字，别动主窗口
        except Exception:      # noqa: BLE001
            return
        hwnd = _toplevel_hwnd(self)
        need_layer = self.alpha < self._ALPHA_OPAQUE
        need_activate = bool(
            _user32 and hwnd and
            _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_NOACTIVATE)
        if not (need_layer or need_activate):
            return
        self._ime_plain = True
        self._restore_deferred = False
        if need_layer:
            _set_layered(hwnd, False)      # 摘分层：中文输入法才挂得上
        if need_activate:
            _set_no_activate(hwnd, False)  # 摘不可激活：窗口才收得到键盘
            ok = _force_foreground(hwnd, event.widget.winfo_id())
            self._ensure_win32_focus(event.widget)
            try:
                event.widget.focus_set()   # 重申 Tk 焦点在输入框（防被顶层截走）
            except Exception:              # noqa: BLE001
                pass
            self._guard_log("guard-on" if ok else "guard-on retry")
            self._start_focus_watchdog(hwnd)

    def _on_focus_out(self, event):
        """焦点离开输入框：稍后确认，因为可能只是移到同一窗口的另一个输入框"""
        if self._is_text_widget(event.widget):
            self.after(60, self._ime_guard_restore)

    def _ime_guard_restore(self):
        """确认焦点确实已不在任何输入框后，把窗口还原成打字前的挂件状态
        （半透明 / 贴桌面不可激活）。焦点还在主窗口的输入框则继续保护。

        焦点显示「不在任何控件上」（None / 顶层窗口）但前台仍是本窗口时，
        多等一拍再收——_force_foreground 抢回前台的瞬间 Win32/Tk 焦点同步
        有一拍延迟，立刻收尾会把还在打字的用户踢出打字模式（只延一次，
        防止无限推迟）。"""
        try:
            cur = self.focus_get()
        except Exception:      # noqa: BLE001
            cur = None
        if self._is_text_widget(cur):
            try:
                if cur.winfo_toplevel() is self:
                    return     # 还在主窗口的输入框里打字，继续保护
            except Exception:  # noqa: BLE001
                pass
        if not self._ime_plain:
            return
        if _user32 and (cur is None or cur is self):
            hwnd0 = _toplevel_hwnd(self)
            if hwnd0 and _user32.GetForegroundWindow() == hwnd0 and \
                    not getattr(self, "_restore_deferred", False):
                self._restore_deferred = True
                self.after(200, self._ime_guard_restore)
                return
        self._restore_deferred = False
        self._ime_plain = False
        self._stop_focus_watchdog()
        self._guard_log("guard-off")
        hwnd = _toplevel_hwnd(self)
        if self.alpha < self._ALPHA_OPAQUE:
            _set_layered(hwnd, True)              # 恢复半透明
        if self.embedded and self.desktop_bottom:
            _set_no_activate(hwnd, True)          # 恢复贴桌面挂件的不可激活
            self._ensure_desktop_bottom()         # 打字时跳过的底层复位，现在补上

    # ---------------- 前台看门狗（打字模式专用） ----------------
    def _ensure_win32_focus(self, widget):
        """确保 Win32 键盘焦点落在输入框本身。前台抢到后 Win32 焦点可能仍停在
        顶层窗口——光标看着在框里，任何按键却都进不来（第三次复现的根因）。"""
        if not _user32:
            return
        try:
            ch = widget.winfo_id()
            if ch and _user32.GetFocus() != ch:
                _user32.SetFocus(ch)
        except Exception:  # noqa: BLE001  控件可能已销毁
            pass

    def _start_focus_watchdog(self, hwnd):
        """打字期间每 300ms 校验：前台是否仍是本窗口、Win32 焦点是否还在
        输入框。被抢走就立刻夺回（用户点输入框打字本就是最近输入事件，
        系统允许抢回）。打字结束（_ime_guard_restore）或连续多次失败时
        停止并记日志。"""
        self._stop_focus_watchdog()
        self._fg_watch_hwnd = hwnd
        self._fg_watch_jobs = 0
        self._fg_watch_job = self.after(300, self._focus_watchdog_tick)

    def _stop_focus_watchdog(self):
        if getattr(self, "_fg_watch_job", None):
            try:
                self.after_cancel(self._fg_watch_job)
            except Exception:  # noqa: BLE001
                pass
        self._fg_watch_job = None

    def _focus_watchdog_tick(self):
        if not self._ime_plain:
            self._stop_focus_watchdog()
            return
        hwnd = getattr(self, "_fg_watch_hwnd", 0)
        if not (_user32 and hwnd):
            return
        self._fg_watch_jobs = getattr(self, "_fg_watch_jobs", 0) + 1
        if _user32.GetForegroundWindow() != hwnd:
            ok = _force_foreground(hwnd)
            if not ok:
                self._guard_log(f"watchdog miss x{self._fg_watch_jobs}")
        try:
            cur = self.focus_get()
        except Exception:  # noqa: BLE001
            cur = None
        if self._is_text_widget(cur) and \
                _user32.GetForegroundWindow() == hwnd:
            self._ensure_win32_focus(cur)
        if self._ime_plain and self._fg_watch_jobs < 20:
            self._fg_watch_job = self.after(300, self._focus_watchdog_tick)
        else:
            if self._fg_watch_jobs >= 20:
                self._guard_log("watchdog giveup")
            self._stop_focus_watchdog()

    # ---------------- 嵌桌面 / 移动模式 ----------------
    def set_embedded(self, value: bool):
        """固定（嵌桌面）：去标题栏、从任务栏消失、压到桌面底层（仅壁纸之上）；
        移动：恢复标题栏与任务栏按钮，临时可拖动，位置满意后再点「固定」"""
        self.embedded = value
        self.overrideredirect(value)          # 固定=无标题栏/无边框，移动=恢复标准窗口
        self.resizable(not value, not value)  # 移动模式交给系统拖边缩放；固定模式用把手
        self.minsize(640, 420)                # 再小月历就挤变形了
        self.update_idletasks()               # 让上面的样式切换立刻生效再取 HWND 操作
        _set_taskbar_button(self, not value)  # 固定=从任务栏隐藏，移动=任务栏显示
        # 加上 WS_EX_NOACTIVATE：贴桌面时窗口不参与激活/前台切换，
        # 系统就不会因为别处抢前台而顺带把它抬上来（修「启动其他程序就浮出」的关键一环）
        _set_no_activate(_toplevel_hwnd(self), value)
        self._apply_zorder()
        self.btn_move.config(text=T("btn_move") if value else T("btn_pin"))
        if value:
            self._create_resize_grips()   # 无标题栏时的边缘缩放把手
        else:
            self._destroy_resize_grips()  # 有标题栏直接拖系统边框
        if value:
            self.persist_cfg()
        else:
            self.lift()  # 移动模式浮到前面，方便抓着标题栏拖动
            self._split_tried = False  # 下次固定重新允许尝试分离壁纸层

    def toggle_embedded(self):
        self.set_embedded(not self.embedded)

    # ---------------- 边缘缩放把手（固定/无标题栏模式的鼠标缩放） ----------------
    _GRIP_PX = 6  # 边缘热区宽度

    def _create_resize_grips(self):
        """固定（嵌桌面）模式没有标题栏和系统边框，鼠标无法缩放——在窗口四边
        place() 一层与背景同色的窄条当「把手」，拖动改 geometry。place 不占
        布局空间，月历排版不受影响；把手只在固定模式存在（移动模式用系统边框）。"""
        if getattr(self, "_grips", None):
            return
        px = self._GRIP_PX
        self._grips = {}
        specs = {
            "right":  (1.0, 0.0, 0, 1.0, px, None, "right_side"),
            "left":   (0.0, 0.0, 0, 1.0, px, None, "left_side"),
            "bottom": (0.0, 1.0, 1.0, 0, None, px, "bottom_side"),
            "top":    (0.0, 0.0, 1.0, 0, None, px, "top_side"),
        }
        for side, (rx, ry, rw, rh, w, h, cur) in specs.items():
            f = tk.Frame(self, bg=self.bg_color, cursor=cur)
            f.place(relx=rx, rely=ry, relwidth=rw, relheight=rh,
                    width=w, height=h)
            for seq in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
                f.bind(seq, lambda e, s=side: self._grip_event(s, e))
            self._grips[side] = f

    def _destroy_resize_grips(self):
        for f in (getattr(self, "_grips", None) or {}).values():
            f.destroy()
        self._grips = None

    def _grip_event(self, side, e):
        """把手三事件：按下记起点，拖动改几何（反向边同时挪位置，保持对角不动），
        松手钳制回屏幕并保存。e.type 用名字比较（Tk 8.6 起 type 是枚举）。"""
        g = getattr(self, "_grips", None)
        if not g or side not in g:
            return
        st = self._grips[side]
        t = e.type.name
        if t == "ButtonPress":
            st.x0, st.y0 = e.x_root, e.y_root
            st.w0, st.h0 = self.winfo_width(), self.winfo_height()
            st.gx, st.gy = self.winfo_x(), self.winfo_y()
            st.active = True
        elif t == "Motion" and getattr(st, "active", False):
            dx, dy = e.x_root - st.x0, e.y_root - st.y0
            w, h, x, y = st.w0, st.h0, st.gx, st.gy
            mnw, mnh = self.minsize()
            if side == "right":
                w = max(mnw, st.w0 + dx)
            elif side == "left":
                w = max(mnw, st.w0 - dx)
                x = st.gx + (st.w0 - w)
            elif side == "bottom":
                h = max(mnh, st.h0 + dy)
            elif side == "top":
                h = max(mnh, st.h0 - dy)
                y = st.gy + (st.h0 - h)
            self.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        elif t == "ButtonRelease" and getattr(st, "active", False):
            st.active = False
            _clamp_into_screen(self)   # 拉大后可能越出屏幕，钳制回可见桌面
            self.persist_cfg()

    def _apply_zorder(self):
        """置顶 / 贴桌面底层 二选一生效（贴底层仅在固定状态生效）

        注意：这里绝不能用 attributes("-topmost", False) 来取消置顶。
        它底层是 SetWindowPos(hwnd, HWND_NOTOPMOST)，语义为「放到所有非置顶窗口的
        最前面」——也就是取消置顶的同时会把窗口顶到最上层。新程序启动引发层级重算
        时，这一句就是日历突然浮出的直接原因。改为只摘 WS_EX_TOPMOST 样式位，
        具体位置交给 _ensure_desktop_bottom 用 SetWindowPos 压到底层。"""
        hwnd = _toplevel_hwnd(self)
        if self.embedded and self.desktop_bottom:
            self.topmost = False          # 底层与置顶互斥
            _clear_topmost_style(hwnd)    # 只清置顶位，不做任何 Z 序抬升
            self._split_tried = False     # 新一轮固定：重新允许尝试分离壁纸层
            self._ensure_desktop_bottom()
            self._start_bottom_keep()
        else:
            self._stop_bottom_keep()
            _set_no_activate(hwnd, False)  # 非贴底层：恢复正常可激活窗口
            self.attributes("-topmost", self.topmost)  # 此处置顶是用户明确要的，允许抬升

    def _on_win_activate(self, _event):
        """贴底层状态下窗口被点到/激活时，稍候校验并压回底层。

        但用户正在输入框打字时不压——_on_focus_in 刚为打字把窗口抢到前台，
        若此时压回底层会立刻夺走键盘焦点，导致打不出字（输入框失活）。
        打字结束后 _ime_guard_restore 会补一次复位。"""
        if self.embedded and self.desktop_bottom and not self._typing_guard_active():
            self.after(120, self._ensure_desktop_bottom)

    def _typing_guard_active(self) -> bool:
        """打字保护是否真的应该生效：_ime_plain 为真【且】当前焦点确实还在
        主窗口的可输入控件里。返回 False 时会顺手把失效的闩锁清掉并还原
        挂件状态（半透明分层 / NOACTIVATE）。

        背景（v1.8.3 根因）：_ime_plain 一旦置位，贴底校验与固定操作全部
        跳过。而切换语言等 UI 整体重建会销毁正持有焦点的输入框，FocusOut
        不会触发，_ime_plain 就永久卡死——日历浮在最上层，来回点「固定」
        也无效。所以这里不能盲信闩锁，每次都实时核对焦点真实性。"""
        if not getattr(self, "_ime_plain", False):
            return False
        try:
            cur = self.focus_get()
        except Exception:          # noqa: BLE001
            cur = None
        if self._is_text_widget(cur):
            try:
                if cur.winfo_toplevel() is self:
                    return True    # 焦点确实在主窗口输入框：打字中，保持保护
            except Exception:      # noqa: BLE001
                pass
        # 闩锁已失效（焦点不在主窗口输入控件）——清掉并还原挂件状态
        self._ime_plain = False
        self._restore_deferred = False
        self._stop_focus_watchdog()
        self._guard_log("guard-stuck-clear")
        hwnd = _toplevel_hwnd(self)
        if _user32 and hwnd:
            if self.alpha < self._ALPHA_OPAQUE:
                _set_layered(hwnd, True)              # 恢复半透明分层
            _clear_topmost_style(hwnd)                # 防残留置顶位
            if self.embedded and self.desktop_bottom:
                _set_no_activate(hwnd, True)          # 恢复贴桌面不可激活
        return False

    def _ensure_desktop_bottom(self):
        """校验窗口是否贴在桌面底层（紧邻下层为 Progman/WorkerW），
        位置正确就什么都不做，被顶起才复位（定时器与激活事件共用入口）。

        修复要点：以前忽略 _pin_above_wallpaper 的返回值，压不下去也无人兜底，
        日历就一直停在被顶起的位置，直到下一次定时校验碰巧成功。
        现在失败会补一次绝对底层重压；且只有「确实复位成功」才认定壁纸层
        分离已生效，失败时保留重试机会，不再一次性把 _split_tried 锁死。

        打字保护：_on_focus_in 为让输入框收得到键盘，临时摘掉 NOACTIVATE 并抢
        前台；若此刻压回底层会把窗口重新推到不可激活状态，键盘焦点随之丢失，
        表现为点进输入框打不出字。检测到打字保护生效时直接跳过，等
        _ime_guard_restore 在打字结束后补一次复位。闩锁失效（如 UI 重建后）
        由 _typing_guard_active 实时发现并自愈，不再永久卡死。"""
        if _user32 is None:
            return
        if self._typing_guard_active():
            return  # 正在输入框打字：不压底层，否则会夺走键盘焦点
        hwnd = _toplevel_hwnd(self)
        if not hwnd:
            return
        # 已经贴着桌面层（Progman 或壁纸 WorkerW）：位置正确，直接返回，不做任何移动
        if _below_class(hwnd) in ("Progman", "WorkerW"):
            return
        ok = _pin_above_wallpaper(hwnd, ask_split=not self._split_tried)
        if ok:
            self._split_tried = True       # 复位成功：壁纸层结构已确认，下次不必再发 0x052C
            return
        # 兜底：清掉可能残留的置顶样式位，再压到绝对底层（不能靠 Tk 的 -topmost，
        # 那会用 HWND_NOTOPMOST 把窗口抬到非置顶层最前，反而更糟）
        _clear_topmost_style(hwnd)
        _user32.SetWindowPos(hwnd, _HWND_BOTTOM, 0, 0, 0, 0,
                             _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE)

    def _start_bottom_keep(self):
        self._stop_bottom_keep()
        # 500ms 一检：原来 2.5 秒太慢，新程序启动把日历顶起后要等两三秒才回落，
        # 用户会清楚看到「浮出到最上层」的过程；0.5 秒内基本无感。
        # 单次校验只是一次 GetWindow + GetClassName，开销可忽略。
        self._bottom_job = self.after(500, self._bottom_tick)

    def _stop_bottom_keep(self):
        if self._bottom_job:
            try:
                self.after_cancel(self._bottom_job)
            except Exception:  # noqa: BLE001
                pass
            self._bottom_job = None

    def _bottom_tick(self):
        """每 0.5 秒校验一次 Z 序：窗口正下方仍是桌面层（Progman/WorkerW）就
        什么都不做；被其他程序顶起（启动新程序、系统钩子窗口抬升等）则立刻
        复位到壁纸之上。全程不缓存任何参照窗口——旧实现缓存「锚点」跟随锚点
        移动，正是被其他程序连带顶到最上层的根因。

        打字期间跳过校验：_on_focus_in 为打字把窗口抢到前台，此时校验会判定
        窗口不在底层而压回去，立刻把键盘焦点带走，表现为输入框打不出字。
        是否真在打字由 _typing_guard_active 实时判定（闩锁卡死会就地自愈）。"""
        self._bottom_job = None
        if self.embedded and self.desktop_bottom:
            self._ensure_desktop_bottom()
            self._bottom_job = self.after(500, self._bottom_tick)

    def open_settings(self):
        """设置对话框：外观 / 显示项 / 窗口层级 / 自启 / 提醒 / 备份 / 订阅 / 企业微信。
        设置项越来越多，改为可滚动列表：底部按钮条固定，滚动区独立。"""
        win = tk.Toplevel(self)
        win.title(f"{T('settings')} · v{APP_VERSION}")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.geometry("620x640")
        # 底部按钮条固定在窗口下缘；上面的设置项整体可滚动
        btns = tk.Frame(win)
        btns.pack(side="bottom", fill="x", padx=16, pady=(0, 10))
        sf = ScrollFrame(win, bg="SystemButtonFace")
        sf.pack(fill="both", expand=True, padx=(12, 4), pady=(8, 4))
        frm = sf.inner

        def cn(zh_text, en_text):
            # 行内小文案的临时双语取词（颜色名等未进字典的短词）
            return zh_text if LANG == "zh" else en_text

        tk.Label(frm, text=T("opacity"), font=self.font_base).grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        scale = tk.Scale(frm, from_=50, to=100, orient="horizontal", length=230,
                         showvalue=True, command=lambda v: self.apply_alpha(int(v) / 100))
        scale.set(round(self.alpha * 100))
        scale.grid(row=1, column=0, sticky="we")
        tk.Label(frm, text=T("opacity_hint"), font=self.font_small,
                 fg=COLOR["text_sub"]).grid(row=2, column=0, sticky="w")

        # 日历字体 / 任务字体，各自独立设置，改动即时预览
        families = sorted(f for f in tkfont.families(root=self) if f and not f.startswith("@"))
        sizes = [str(i) for i in range(8, 23)]

        def font_row(row, label, fam_attr, size_attr):
            tk.Label(frm, text=label, font=self.font_base).grid(
                row=row, column=0, sticky="w", pady=(10, 2))
            sub = tk.Frame(frm)
            sub.grid(row=row + 1, column=0, sticky="w")
            fam_cb = ttk.Combobox(sub, values=families, width=22, state="readonly",
                                  font=self.font_small)
            fam_cb.set(getattr(self, fam_attr))
            fam_cb.pack(side="left")
            sz_cb = ttk.Combobox(sub, values=sizes, width=3, state="readonly",
                                 font=self.font_small)
            sz_cb.set(str(getattr(self, size_attr)))
            sz_cb.pack(side="left", padx=(6, 0))
            tk.Label(sub, text=T("size_unit"), font=self.font_small,
                     fg=COLOR["text_sub"]).pack(side="left", padx=(2, 0))

            def on_change(_e=None):
                setattr(self, fam_attr, fam_cb.get().strip() or "Microsoft YaHei UI")
                setattr(self, size_attr, int(sz_cb.get()))
                self.apply_fonts()

            fam_cb.bind("<<ComboboxSelected>>", on_change)
            sz_cb.bind("<<ComboboxSelected>>", on_change)

        font_row(3, T("cal_font"), "cal_family", "cal_size")
        font_row(5, T("task_font"), "task_family", "task_size")

        # 日历显示选项
        disp = tk.Frame(frm)
        disp.grid(row=7, column=0, sticky="w", pady=(12, 0))
        tk.Label(disp, text=T("disp_label"), font=self.font_base).pack(side="left")

        def set_disp(attr, val):
            setattr(self, attr, val)
            self.render_grid()

        for text, attr in [(T("disp_weekno"), "show_weekno"),
                           (T("disp_lunar"), "show_lunar"),
                           (T("disp_terms"), "show_terms"),
                           (T("disp_rest"), "show_rest")]:
            var = tk.BooleanVar(value=getattr(self, attr))
            # 英文界面不显示农历（数字农历对英文用户无意义），置灰避免勾了没反应
            off = (attr == "show_lunar" and LANG == "en")
            tk.Checkbutton(disp, text=text, variable=var, font=self.font_small,
                           state="disabled" if off else "normal",
                           command=lambda a=attr, v=var: set_disp(a, v.get())
                           ).pack(side="left", padx=(2, 6))

        ws_frame = tk.Frame(frm)
        ws_frame.grid(row=8, column=0, sticky="w", pady=(6, 0))
        tk.Label(ws_frame, text=T("week_start"), font=self.font_base).pack(side="left")
        ws_cb = ttk.Combobox(ws_frame, values=[T("monday"), T("sunday")], width=8,
                             state="readonly", font=self.font_base)
        ws_cb.set(T("monday") if self.week_start == "mon" else T("sunday"))
        ws_cb.pack(side="left", padx=(6, 0))

        def on_week_start(_e=None):
            self.week_start = "mon" if ws_cb.get() == T("monday") else "sun"
            self.render_grid()

        ws_cb.bind("<<ComboboxSelected>>", on_week_start)

        # 当前国家：月历按所选国家的实际工作日/休息日显示
        # （中国=法定节假日与调休补班；乌兹别克斯坦=当地法定节日与调休）
        cty_frame = tk.Frame(frm)
        cty_frame.grid(row=9, column=0, sticky="w", pady=(6, 0))
        tk.Label(cty_frame, text=T("country_label"),
                 font=self.font_base).pack(side="left")
        cty_cb = ttk.Combobox(cty_frame, values=[T("country_cn"), T("country_uz")],
                              width=14, state="readonly", font=self.font_base)
        cty_cb.current(0 if self.country == "cn" else 1)
        cty_cb.pack(side="left", padx=(6, 0))

        def on_country(_e=None):
            global COUNTRY
            self.country = "cn" if cty_cb.current() == 0 else "uz"
            COUNTRY = self.country
            # 计算页若已建过，节日倒计时列表还是旧国家的，需要同步换新
            if getattr(self, "_calc_built", False):
                self.holidays = upcoming_holidays()
                names = [T(k) for k, _d in self.holidays]
                self.cmb_holiday.config(values=names)
                if names:
                    self.cmb_holiday.current(0)
                self.calc_countdown()
            self.render_grid()

        cty_cb.bind("<<ComboboxSelected>>", on_country)

        z_frame = tk.Frame(frm)
        z_frame.grid(row=10, column=0, sticky="w", pady=(12, 0))
        topmost_var = tk.BooleanVar(value=self.topmost)
        bottom_var = tk.BooleanVar(value=self.desktop_bottom)

        def on_topmost():
            self.topmost = topmost_var.get()
            if self.topmost and self.desktop_bottom:
                self.desktop_bottom = False  # 置顶与贴底层互斥
                bottom_var.set(False)
            self._apply_zorder()

        def on_bottom():
            self.desktop_bottom = bottom_var.get()
            if self.desktop_bottom and self.topmost:
                self.topmost = False
                topmost_var.set(False)
            self._apply_zorder()

        tk.Checkbutton(z_frame, text=T("topmost"),
                       variable=topmost_var, command=on_topmost,
                       font=self.font_base).pack(anchor="w")
        tk.Checkbutton(z_frame, text=T("bottom_layer"),
                       variable=bottom_var, command=on_bottom,
                       font=self.font_base).pack(anchor="w")

        if winreg is not None:
            autostart_var = tk.BooleanVar(value=is_autostart_on())

            def on_autostart():
                set_autostart(autostart_var.get())

            tk.Checkbutton(frm, text=T("autostart"),
                           variable=autostart_var, command=on_autostart,
                           font=self.font_base).grid(row=11, column=0, sticky="w", pady=(6, 0))
        else:
            tk.Label(frm, text=T("autostart_na"), font=self.font_small,
                     fg=COLOR["text_sub"]).grid(row=11, column=0, sticky="w", pady=(6, 0))

        holiday_var = tk.BooleanVar(value=self.show_holiday)

        def on_holiday():
            self.show_holiday = holiday_var.get()
            self.render_grid()

        tk.Checkbutton(frm, text=T("show_holiday"),
                       variable=holiday_var, command=on_holiday,
                       font=self.font_base).grid(row=12, column=0, sticky="w", pady=(6, 0))

        # 提前提醒：所有到点提醒在「提前量」之前先弹一次本地提示（不推企业微信）
        ea_frame = tk.Frame(frm)
        ea_frame.grid(row=13, column=0, sticky="w", pady=(6, 0))
        tk.Label(ea_frame, text=T("remind_early"), font=self.font_base).pack(side="left")
        ea_vals = (0, 5, 10, 30, 60, 1440)
        ea_cb = ttk.Combobox(ea_frame, values=T("early_vals"), width=8,
                             state="readonly", font=self.font_base)
        ea_cb.current(ea_vals.index(self.remind_early)
                      if self.remind_early in ea_vals else 0)
        ea_cb.pack(side="left", padx=(6, 0))

        def on_early(_e=None):
            self.remind_early = ea_vals[ea_cb.current()]

        ea_cb.bind("<<ComboboxSelected>>", on_early)

        # 每日自动备份：把整个任务库快照到 data/backup/，保留最近 10 份
        ab_var = tk.BooleanVar(value=self.auto_backup)

        def on_backup():
            self.auto_backup = ab_var.get()

        tk.Checkbutton(frm, text=T("auto_backup"), variable=ab_var,
                       command=on_backup,
                       font=self.font_base).grid(row=14, column=0, sticky="w", pady=(6, 0))

        # 颜色设置
        def set_color(attr, col):
            setattr(self, attr, col)
            self.apply_theme()   # 静态容器/签名/语言按钮同步换色
            self.refresh()

        fg_frame = tk.Frame(frm)
        fg_frame.grid(row=15, column=0, sticky="w", pady=(12, 0))
        tk.Label(fg_frame, text=T("cal_fg"), font=self.font_base).pack(side="left")
        for name, col in [("黑", "#1f2937"), ("红", "#dc2626"), ("蓝", "#2563eb"),
                          ("棕", "#92400e"), ("紫", "#7c3aed")]:
            tk.Button(fg_frame, text=name, bg=col, fg="#ffffff", bd=0,
                      font=self.font_small, width=3, cursor="hand2",
                      command=lambda c=col: set_color("cal_fg", c)
                      ).pack(side="left", padx=2)
        tk.Button(fg_frame, text=T("custom"), bd=0, font=self.font_small,
                  cursor="hand2",
                  command=lambda: self.pick_color("cal_fg")).pack(side="left", padx=2)

        ac_frame = tk.Frame(frm)
        ac_frame.grid(row=16, column=0, sticky="w", pady=(8, 0))
        tk.Label(ac_frame, text=T("accent_color"), font=self.font_base).pack(side="left")
        for name, col in [("蓝", "#2563eb"), ("绿", "#16a34a"), ("紫", "#7c3aed"),
                          ("橙", "#ea580c"), ("红", "#dc2626"), ("青", "#0891b2")]:
            tk.Button(ac_frame, text=name, bg=col, fg="#ffffff", bd=0,
                      font=self.font_small, width=3, cursor="hand2",
                      command=lambda c=col: set_color("accent", c)
                      ).pack(side="left", padx=2)

        # 背景定制
        bgc_frame = tk.Frame(frm)
        bgc_frame.grid(row=17, column=0, sticky="w", pady=(12, 0))
        tk.Label(bgc_frame, text=T("bg_color"), font=self.font_base).pack(side="left")
        for name, col in [(T("bg_default"), "#f0f0f0"), (T("bg_blue"), "#e3edf8"), (T("bg_green"), "#e6f4ea"),
                          (T("bg_pink"), "#fbeef1"), (T("bg_beige"), "#f7f3e3"), (T("bg_gray"), "#3b4048")]:
            tk.Button(bgc_frame, text=name, bg=col,
                      fg="#ffffff" if col == "#3b4048" else COLOR["text"],
                      bd=0, font=self.font_small, width=4, cursor="hand2",
                      command=lambda c=col: set_color("bg_color", c)
                      ).pack(side="left", padx=2)
        tk.Button(bgc_frame, text=T("custom"), bd=0, font=self.font_small,
                  cursor="hand2",
                  command=lambda: self.pick_color("bg_color")).pack(side="left", padx=2)

        bgi_frame = tk.Frame(frm)
        bgi_frame.grid(row=18, column=0, sticky="w", pady=(8, 0))
        tk.Label(bgi_frame, text=T("bg_image"), font=self.font_base).pack(side="left")
        tk.Button(bgi_frame, text=T("pick_image"), font=self.font_small, bd=0,
                  cursor="hand2", command=self.pick_bg_image).pack(side="left", padx=2)
        tk.Button(bgi_frame, text=T("clear_image"), font=self.font_small, bd=0,
                  cursor="hand2",
                  command=lambda: (self.clear_bg_image(), self.persist_cfg())
                  ).pack(side="left", padx=2)
        tk.Label(bgi_frame, text=T("bg_image_hint"), font=self.font_small,
                 fg=COLOR["text_sub"]).pack(side="left", padx=(4, 0))

        # 日历订阅（ICS）：外部日历（如节假日）事件按日期自动建为任务
        tk.Label(frm, text=T("ics_head"), font=self.font_base).grid(
            row=19, column=0, sticky="w", pady=(12, 0))
        ics_fr = tk.Frame(frm)
        ics_fr.grid(row=20, column=0, sticky="w")
        ics_entry = tk.Entry(ics_fr, width=46, font=self.font_small)
        ics_entry.insert(0, self.ics_url)
        ics_entry.pack(side="left", ipady=2)

        def on_ics_sync():
            url = ics_entry.get().strip()
            if not url:
                messagebox.showwarning(T("warn_title"), T("ics_no_url"), parent=win)
                return
            self.ics_url = url

            def work():
                try:
                    c = sqlite3.connect(DB_PATH)   # 线程里另开连接
                    try:
                        added, skipped = ics_sync(c, url)
                        kv_set(c, "ics_last_sync", datetime.now().isoformat())
                    finally:
                        c.close()
                    msg = T("ics_ok", n=added, s=skipped)
                except Exception as e:  # noqa: BLE001
                    msg = T("ics_fail", e=e)
                self.after(0, lambda: (messagebox.showinfo(T("warn_title"), msg,
                                                           parent=win),
                                       self.refresh()))

            threading.Thread(target=work, daemon=True).start()

        tk.Button(ics_fr, text=T("ics_sync"), font=self.font_small, width=8,
                  command=on_ics_sync).pack(side="left", padx=(4, 0))
        tk.Label(frm, text=T("ics_hint"), font=self.font_small, fg=COLOR["text_sub"],
                 wraplength=560, justify="left").grid(
            row=21, column=0, sticky="w", pady=(2, 0))

        # 企业微信推送
        tk.Label(frm, text=T("wecom_hook"), font=self.font_base).grid(
            row=22, column=0, sticky="w", pady=(12, 0))
        wr = tk.Frame(frm)
        wr.grid(row=23, column=0, sticky="w")
        wecom_entry = tk.Entry(wr, width=46, font=self.font_small)
        wecom_entry.insert(0, self.wecom_webhook)
        wecom_entry.pack(side="left", ipady=2)

        def on_test_wecom():
            hook = wecom_entry.get().strip()
            if not hook:
                messagebox.showwarning(
                    T("wecom_fail"),
                    cn("请先填写 Webhook 地址", "Please enter the Webhook URL first"),
                    parent=win)
                return
            self.wecom_webhook = hook

            def work():
                ok, err = wecom_push(hook, T("wecom_test_msg"))
                if ok:
                    msg = T("wecom_test_sent")
                elif "93000" in err:
                    msg = T("wecom_bad_hook")
                else:
                    msg = T("wecom_send_fail", e=err)
                self.after(0, lambda: messagebox.showinfo(
                    T("wecom_fail"), msg, parent=win))

            threading.Thread(target=work, daemon=True).start()

        tk.Button(wr, text=T("btn_test"), font=self.font_small, width=5,
                  command=on_test_wecom).pack(side="left", padx=(4, 0))
        tk.Label(frm, text=T("wecom_hook_hint"),
                 font=self.font_small, fg=COLOR["text_sub"]).grid(
            row=24, column=0, sticky="w", pady=(2, 0))

        wr2 = tk.Frame(frm)
        wr2.grid(row=25, column=0, sticky="w", pady=(6, 0))
        wp_var = tk.BooleanVar(value=self.wecom_push)

        def on_wecom_push():
            self.wecom_push = wp_var.get()

        tk.Checkbutton(wr2, text=T("wecom_also_push"), variable=wp_var,
                       command=on_wecom_push, font=self.font_base).pack(side="left")
        tk.Button(wr2, text=T("btn_push_today"), font=self.font_small,
                  command=lambda: self.push_today_to_wecom(parent=win)
                  ).pack(side="left", padx=(10, 0))

        # 企业微信自建应用（消息发到个人，无需建群）
        tk.Label(frm, text=T("wecom_app"), font=self.font_base).grid(
            row=26, column=0, sticky="w", pady=(12, 0))
        app_fr = tk.Frame(frm)
        app_fr.grid(row=27, column=0, sticky="w")
        tk.Label(app_fr, text="CorpID", font=self.font_small).pack(side="left")
        corp_entry = tk.Entry(app_fr, width=22, font=self.font_small)
        corp_entry.insert(0, self.wecom_corp_id)
        corp_entry.pack(side="left", padx=(2, 6))
        tk.Label(app_fr, text="AgentID", font=self.font_small).pack(side="left")
        agent_entry = tk.Entry(app_fr, width=8, font=self.font_small)
        agent_entry.insert(0, self.wecom_agent_id)
        agent_entry.pack(side="left", padx=(2, 6))
        tk.Label(app_fr, text="Secret", font=self.font_small).pack(side="left")
        secret_entry = tk.Entry(app_fr, width=32, font=self.font_small, show="*")
        secret_entry.insert(0, self.wecom_corp_secret)
        secret_entry.pack(side="left", padx=(2, 0))

        def on_test_app():
            cid, aid, sec = (corp_entry.get().strip(), agent_entry.get().strip(),
                             secret_entry.get().strip())
            if not (cid and aid and sec):
                messagebox.showwarning(T("wecom_fail"), T("wecom_fill"),
                                       parent=win)
                return
            self.wecom_corp_id, self.wecom_agent_id, self.wecom_corp_secret = cid, aid, sec

            def work():
                ok, err = wecom_app_push(cid, aid, sec, T("wecom_app_test_msg"))
                msg = T("wecom_test_ok") if ok else T("wecom_ip_hint", e=err)
                self.after(0, lambda: messagebox.showinfo(
                    T("wecom_fail"), msg, parent=win))

            threading.Thread(target=work, daemon=True).start()

        app_fr2 = tk.Frame(frm)
        app_fr2.grid(row=28, column=0, sticky="w", pady=(4, 0))
        tk.Button(app_fr2, text=T("btn_test_app"), font=self.font_small,
                  command=on_test_app).pack(side="left")
        tk.Label(app_fr2, text=T("wecom_app_hint"),
                 font=self.font_small, fg=COLOR["text_sub"]).pack(side="left")

        # 注：界面语言已移到主界面顶部（点击即时切换，无需重启），此处不再提供

        # 内容文字颜色（任务预览、日清单、全部清单的任务文字）
        tfg_frame = tk.Frame(frm)
        tfg_frame.grid(row=32, column=0, sticky="w", pady=(8, 0))
        tk.Label(tfg_frame, text=T("task_fg"), font=self.font_base).pack(side="left")
        for name, col in [("黑", "#111827"), ("灰", "#4b5563"), ("蓝", "#2563eb"),
                          ("绿", "#16a34a"), ("紫", "#7c3aed")]:
            tk.Button(tfg_frame, text=name, bg=col, fg="#ffffff", bd=0,
                      font=self.font_small, width=3, cursor="hand2",
                      command=lambda c=col: set_color("task_fg", c)
                      ).pack(side="left", padx=2)
        tk.Button(tfg_frame, text=T("custom"), bd=0, font=self.font_small,
                  cursor="hand2",
                  command=lambda: self.pick_color("task_fg")).pack(side="left", padx=2)

        # 窗口尺寸：直接输入宽高（固定模式也可以拖窗口边缘缩放，见 _grip_event）
        tk.Label(frm, text=T("win_size"), font=self.font_base).grid(
            row=34, column=0, sticky="w", pady=(14, 0))
        ws_fr = tk.Frame(frm)
        ws_fr.grid(row=35, column=0, sticky="w", pady=(4, 0))
        tk.Label(ws_fr, text=T("win_w"), font=self.font_small).pack(side="left")
        w_var = tk.StringVar(value=str(self.winfo_width()))
        tk.Entry(ws_fr, width=5, textvariable=w_var,
                 font=self.font_small).pack(side="left", padx=(2, 6))
        tk.Label(ws_fr, text=T("win_h"), font=self.font_small).pack(side="left")
        h_var = tk.StringVar(value=str(self.winfo_height()))
        tk.Entry(ws_fr, width=5, textvariable=h_var,
                 font=self.font_small).pack(side="left", padx=(2, 10))

        def on_apply_size():
            try:
                w = max(640, min(4000, int(float(w_var.get()))))
                h = max(420, min(3000, int(float(h_var.get()))))
            except ValueError:
                messagebox.showwarning(T("warn_title"), T("size_invalid"),
                                       parent=win)
                return
            self.geometry(f"{w}x{h}")
            self.update_idletasks()
            _clamp_into_screen(self)   # 拉大后可能越出屏幕，钳制回可见桌面
            self.persist_cfg()
            self.refresh()

        tk.Button(ws_fr, text=T("btn_apply_size"), font=self.font_small,
                  command=on_apply_size).pack(side="left")
        tk.Label(ws_fr, text=T("win_size_hint"), font=self.font_small,
                 fg=COLOR["text_sub"]).pack(side="left")

        def on_done():
            self.wecom_webhook = wecom_entry.get().strip()
            self.wecom_corp_id = corp_entry.get().strip()
            self.wecom_agent_id = agent_entry.get().strip()
            self.wecom_corp_secret = secret_entry.get().strip()
            self.ics_url = ics_entry.get().strip()
            self.persist_cfg()
            win.destroy()

        # 底部按钮条（固定在窗口下缘，不随滚动）：左「修订日志」，右「完成」
        tk.Button(btns, text=T("btn_changelog"), font=self.font_small,
                  command=lambda: self.show_changelog(parent=win)
                  ).pack(side="left")
        tk.Button(btns, text=T("btn_done"), font=self.font_base, width=8,
                  command=on_done).pack(side="right")
        win.grab_set()

    def show_changelog(self, parent=None):
        """打开修订日志窗口：读取程序同目录的 CHANGELOG.md（打包后从 exe 内部读）。

        每次改代码就把版本与说明写进那个文件，之后任何时候点开都能回看
        「哪天改了什么」，不必翻聊天记录。"""
        text = load_changelog()
        win = tk.Toplevel(parent or self)
        win.title(f"{T('changelog_title')} · v{APP_VERSION}")
        win.geometry("620x520")
        win.transient(self)
        win.attributes("-topmost", True)
        frm = tk.Frame(win, padx=10, pady=10)
        frm.pack(fill="both", expand=True)
        box = tk.Text(frm, wrap="word", font=("Microsoft YaHei UI", 10),
                      bg="#ffffff", fg=COLOR["text"], relief="solid", bd=1)
        box.insert("1.0", text or T("changelog_missing"))
        box.config(state="disabled")            # 只读，避免误改日志
        sb = tk.Scrollbar(frm, command=box.yview)
        box.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        tk.Button(win, text=T("btn_close"), font=self.font_base, width=8,
                  command=win.destroy).pack(pady=(0, 10))
        win.grab_set()
        win.lift()
        win.focus_force()

    def pick_color(self, attr):
        color = colorchooser.askcolor(parent=self, title="选择颜色")
        if color and color[1]:
            setattr(self, attr, color[1])
            self.apply_theme()   # 静态容器/签名/语言按钮同步换色
            self.refresh()

    # ---------------- 背景定制 ----------------
    def apply_bg_image(self):
        """把背景图片铺满窗口底层（cover 模式，居中裁剪），内容浮于其上"""
        if not self.bg_image_path or not Path(self.bg_image_path).exists():
            return
        try:
            from PIL import Image
        except ImportError:
            messagebox.showwarning(T("warn_title"), T("no_pillow"))
            return
        try:
            self._bg_source = Image.open(self.bg_image_path).convert("RGB")
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning(T("warn_title"), T("pillow_read_fail", e=e))
            return
        self._rescale_bg()

    def _rescale_bg(self):
        source = getattr(self, "_bg_source", None)
        if source is None:
            return
        from PIL import ImageTk
        w = max(self.winfo_width(), 200)
        h = max(self.winfo_height(), 150)
        scale = max(w / source.width, h / source.height)
        nw, nh = max(w, round(source.width * scale)), max(h, round(source.height * scale))
        resized = source.resize((nw, nh))
        left, top = (nw - w) // 2, (nh - h) // 2
        cropped = resized.crop((left, top, left + w, top + h))
        self._bg_photo = ImageTk.PhotoImage(cropped, master=self)
        if not hasattr(self, "_bg_label"):
            self._bg_label = tk.Label(self, bd=0)
            self._bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            self._bg_label.lower()
        self._bg_label.configure(image=self._bg_photo)

    def clear_bg_image(self):
        self.bg_image_path = ""
        self._bg_source = None
        if hasattr(self, "_bg_label"):
            self._bg_label.place_forget()

    def pick_bg_image(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择背景图片",
            filetypes=[("图片", "*.png;*.jpg;*.jpeg;*.bmp"), ("全部文件", "*.*")])
        if not path:
            return
        try:
            from PIL import Image
            Image.open(path).verify()
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning(T("warn_title"), T("pillow_read_fail", e=e),
                                   parent=self)
            return
        dest = BASE_DIR / "data" / ("bg" + Path(path).suffix.lower())
        shutil.copyfile(path, dest)  # 拷进工具目录，原图片移动/删除不影响
        self.bg_image_path = str(dest)
        self.apply_bg_image()
        self.persist_cfg()

    def on_close(self):
        if self.tray:
            self.tray.destroy()
            self.tray = None
        self.persist_cfg()
        self.conn.close()
        self.destroy()


if __name__ == "__main__":
    # ===== 授权校验已停用（2026-09-10 用户要求）：程序直接启动，不再要求激活 =====
    # 需要重新启用时，把下面三行的注释放开、并注释掉最后一行即可。
    # 校验必须放在 CalendarApp() 之前：CalendarApp 继承 tk.Tk，一旦实例化窗口就已经建好，
    # 校验若放进 __init__ 里，未授权时窗口会先闪一下再退出，很难看。
    # import license_guard
    #
    # if license_guard.ensure_licensed(app_name=license_guard.APP_NAME):
    #     CalendarApp().mainloop()

    # 崩溃日志：windowed exe 无控制台，未捕获异常直接吞掉、进程静默退出；
    # 写到同目录 crash.log 便于排查「双击后一闪就没」类问题
    import traceback as _tb

    def _log_crash(args):
        try:
            with open(BASE_DIR / "crash.log", "a", encoding="utf-8") as f:
                f.write("\n[%s]\n" % datetime.now().isoformat(timespec="seconds"))
                f.write("".join(_tb.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
        except Exception:  # noqa: BLE001  # 记日志失败也不能影响退出流程
            pass

    sys.excepthook = _log_crash
    if hasattr(threading, "excepthook"):
        threading.excepthook = _log_crash

    # 单实例保护（v1.7.1）：已有实例在跑就把它的窗口带到前台，然后本次启动直接退出。
    # 不加的话连点几次会堆出多个实例，同时写同一个 SQLite 也不安全
    cal_mutex = _kernel32.CreateMutexW(None, False,
                                       "DesktopCalendar_SingleInstance")
    if cal_mutex and _kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        _raise_existing_instance()
        sys.exit(0)          # __main__ 顶层不能 return，直接退出本次启动

    CalendarApp().mainloop()
