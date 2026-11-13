#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器绑定授权模块（离线 / 对称 HMAC / 零第三方依赖）

原理
----
1. 采集本机硬件特征（Windows 安装 GUID + 系统盘卷序列号 + CPU 型号），
   算出唯一「机器码」；
2. 你用自己的密钥（SECRET）把「机器码 + 有效期」签成授权码发给同事；
3. 程序启动时重算机器码并校验授权码，机器对不上或已过期就拒绝运行。

效果：同事把 exe 原样拷给别人 → 对方机器上机器码不同 → 启动即拒绝。
定位：防「随手转发」，不防专业逆向（见 README「这方案防不住什么」）。

接入方式（三行）
----------------
    from license_guard import ensure_licensed
    if not ensure_licensed(app_name="我的工具"):
        sys.exit(0)

打包前必做
----------
把下面的 SECRET 换成你自己的随机串，绝不要保留默认值：
    python -c "import secrets; print(secrets.token_hex(32))"
"""

import base64
import hashlib
import hmac
import os
import re
from datetime import date, timedelta

# ===========================================================================
# 需要你修改的配置
# ===========================================================================

# 签名密钥：整个方案的安全根基。必须改！用上面的命令生成一个随机串。
# 注意：这个密钥会被打进 exe，理论上可被提取（本方案的固有上限，见 README）。
SECRET = b"dc9242c0446c2975d804d69c2197f47caf47fd909b0252e832745534eaf78a46"

# 程序名：决定授权文件的存放目录（%APPDATA%\<APP_NAME>\license.key）
# 每个程序用不同名字，避免几个工具互相覆盖授权文件
APP_NAME = "DesktopCalendar"

# ===========================================================================
# 以下为实现，一般不需要改
# ===========================================================================

# 硬件特征里常见的「无效占位值」，某些厂商会填这些，参与哈希会导致机器码雷同
_INVALID = {
    "", "none", "null", "0", "unknown", "default string",
    "to be filled by o.e.m.", "to be filled by o.e.m", "not specified",
    "00000000", "0000000000000000", "ffffffff",
}


def _clean(value):
    """去掉首尾空白，无效占位值统一返回空串"""
    v = (value or "").strip()
    return "" if v.lower() in _INVALID else v


def _reg_value(root, path, name):
    """读注册表字符串值；读不到（权限/键不存在/非 Windows）返回空串"""
    try:
        import winreg
        with winreg.OpenKey(root, path) as key:
            return _clean(winreg.QueryValueEx(key, name)[0])
    except Exception:
        return ""


def _machine_guid():
    """Windows 安装 GUID：重装系统才会变，是最稳定的主特征"""
    try:
        import winreg
        return _reg_value(winreg.HKEY_LOCAL_MACHINE,
                          r"SOFTWARE\Microsoft\Cryptography", "MachineGuid")
    except Exception:
        return ""


def _volume_serial(drive="C:\\"):
    """系统盘卷序列号：格式化/换硬盘才会变（用 Win32 API，快且不依赖 PowerShell）"""
    try:
        import ctypes
        serial = ctypes.c_uint(0)
        name_buf = ctypes.create_unicode_buffer(1024)
        fs_buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive), name_buf, 1024,
            ctypes.byref(serial), None, None, fs_buf, 1024)
        text = "%08X" % (serial.value & 0xFFFFFFFF)
        return _clean(text)
    except Exception:
        return ""


def _cpu_name():
    """CPU 型号：换 CPU 才会变"""
    try:
        import winreg
        return _reg_value(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            "ProcessorNameString")
    except Exception:
        return ""


def _motherboard_serial():
    """主板序列号：注册表一般不直接给，走 Win32_BaseBoard 太慢且可能被策略禁用，
    这里用系统产品名替代（差异化有限，仅作补充特征）"""
    try:
        import winreg
        return _reg_value(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct")
    except Exception:
        return ""


def machine_id():
    """返回本机的 16 位大写十六进制机器码（给同事让用户报给你这个）"""
    parts = [_machine_guid(), _volume_serial(), _cpu_name(), _motherboard_serial()]
    parts = [p for p in parts if p]                    # 丢掉采集失败的项
    if not parts:                                       # 极端情况：全都拿不到
        parts = ["fallback-machine"]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16].upper()


def _b32(data):
    """base32 编码并去掉补位等号，便于人工抄写"""
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _sign(mid, expire):
    """对「机器码|有效期」做 HMAC-SHA256，返回前 12 个 base32 字符"""
    payload = f"{mid}|{expire}".encode("utf-8")
    digest = hmac.new(SECRET, payload, hashlib.sha256).digest()
    return _b32(digest)[:12]


def make_license(mid, days=0):
    """生成授权码。

    mid  : 目标机器的机器码（16 位大写十六进制）
    days : 有效天数，0 表示永久
    返回 : 形如 XXXXX-XXXXX-XXXXX-XXXXX 的授权码
    """
    mid = (mid or "").strip().upper()
    # 有效期存进码里：00000000 代表永久，否则是 YYYYMMDD
    expire = "00000000" if days <= 0 else \
        (date.today() + timedelta(days=days)).strftime("%Y%m%d")
    token = expire + _sign(mid, expire)        # 8 位有效期 + 12 位签名 = 20 字符
    return "-".join(token[i:i + 5] for i in range(0, 20, 5))


def parse_license(code):
    """把授权码还原成 (有效期字符串, 签名)；格式不对返回 None"""
    if not code:
        return None
    token = re.sub(r"[^0-9A-Z]", "", (code or "").strip().upper())
    return (token[:8], token[8:]) if len(token) == 20 else None


def verify(mid, code):
    """校验授权码。返回 (是否通过, 提示文字)。

    compare_digest 做常量时间比较，避免通过响应时间差暴力猜解签名。
    """
    parsed = parse_license(code)
    if not parsed:
        return False, "授权码格式不正确（应为 4 组 5 位字符）"
    expire, signature = parsed
    mid = (mid or "").strip().upper()
    if not hmac.compare_digest(signature, _sign(mid, expire)):
        # 机器码不匹配 或 授权码被篡改，都归到这一类（不区分，避免给出伪造线索）
        return False, "授权码无效，或不属于这台电脑"
    if expire != "00000000":
        try:
            end = date(int(expire[:4]), int(expire[4:6]), int(expire[6:8]))
        except ValueError:
            return False, "授权码已损坏（有效期无法识别）"
        if date.today() > end:
            return False, f"授权已于 {end.strftime('%Y-%m-%d')} 到期，请联系作者续期"
        left = (end - date.today()).days
        if left <= 7:                       # 只剩一周内才提醒，避免刚签发就报"即将到期"
            return True, f"授权有效（剩余 {left} 天，即将到期）"
    return True, "授权有效"


# ---------------------------------------------------------------------------
# 授权文件的读写（存 RoamingAppData，拷走也没用，因为内容绑定机器码）
# ---------------------------------------------------------------------------
def _roaming_appdata():
    """权威获取 RoamingAppData 真实路径，不依赖 APPDATA 环境变量。
    优先级：环境变量 → 注册表 User Shell Folders\\AppData → 兜底 expanduser。"""
    base = os.environ.get("APPDATA")
    if base:
        return base
    # explorer 自己就是读这里拿到 AppData 的，比 SHGetKnownFolderPath 更兼容
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        ) as k:
            val, _ = winreg.QueryValueEx(k, "AppData")
        if isinstance(val, str) and val:
            return os.path.expandvars(val)
    except OSError:
        pass
    return os.path.expanduser("~")


def license_path(app_name=APP_NAME):
    base = _roaming_appdata()
    folder = os.path.join(base, app_name)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return os.path.join(folder, "license.key")


def load_saved(app_name=APP_NAME):
    """读取已保存的授权码；没有或损坏返回空串"""
    try:
        with open(license_path(app_name), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_license(code, app_name=APP_NAME):
    """保存授权码；失败返回 False（不影响使用，只是下次要重新输入）"""
    try:
        with open(license_path(app_name), "w", encoding="utf-8") as f:
            f.write(code.strip().upper())
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 激活窗口（有 tkinter 就用图形界面，没有就退回命令行输入）
# ---------------------------------------------------------------------------
def _ask_gui(mid, app_name, message):
    """弹窗显示机器码并要求输入授权码；返回用户输入的码，取消返回 None"""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        return None

    result = {"code": None}
    root = tk.Tk()
    root.title(f"{app_name} — 激活")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.eval("tk::PlaceWindow . center")       # 居中显示

    frame = tk.Frame(root, padx=20, pady=16)
    frame.pack()

    tk.Label(frame, text="本软件需要激活后使用",
             font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(0, 10))

    if message:                                  # 之前填错过就给出原因
        tk.Label(frame, text=message, fg="#dc2626",
                 font=("Microsoft YaHei UI", 9), wraplength=380).pack(pady=(0, 8))

    tk.Label(frame, text="本机机器码（把这串发给作者获取授权码）：",
             font=("Microsoft YaHei UI", 9)).pack(anchor="w")
    mid_row = tk.Frame(frame)
    mid_row.pack(fill="x", pady=(2, 10))
    mid_var = tk.StringVar(value=mid)
    mid_entry = tk.Entry(mid_row, textvariable=mid_var, width=24,
                         font=("Consolas", 13, "bold"), justify="center",
                         fg="#2563eb", relief="solid", bd=1)
    mid_entry.pack(side="left")
    mid_entry.configure(state="readonly")

    def copy_mid():
        root.clipboard_clear()
        root.clipboard_append(mid)
        copy_btn.config(text="已复制 ✓")

    copy_btn = tk.Button(mid_row, text="复制", font=("Microsoft YaHei UI", 8),
                         command=copy_mid, cursor="hand2")
    copy_btn.pack(side="left", padx=(6, 0))

    tk.Label(frame, text="授权码：", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
    code_var = tk.StringVar()
    tk.Entry(frame, textvariable=code_var, width=30,
             font=("Consolas", 11), justify="center").pack(pady=(2, 12))

    def on_ok(_event=None):
        result["code"] = code_var.get().strip()
        root.destroy()

    def on_cancel():
        result["code"] = None
        root.destroy()

    btn_row = tk.Frame(frame)
    btn_row.pack()
    tk.Button(btn_row, text="激活", width=10, command=on_ok,
              font=("Microsoft YaHei UI", 9), cursor="hand2").pack(side="left", padx=4)
    tk.Button(btn_row, text="退出", width=10, command=on_cancel,
              font=("Microsoft YaHei UI", 9), cursor="hand2").pack(side="left", padx=4)

    root.bind("<Return>", on_ok)
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()
    return result["code"]


def _ask_cli(mid, app_name, message):
    """没有图形界面时的命令行激活"""
    print("=" * 50)
    print(f" {app_name} — 激活")
    print("=" * 50)
    if message:
        print(f" 提示：{message}\n")
    print(f" 本机机器码：{mid}")
    print(" 把这串机器码发给作者，换取授权码。\n")
    try:
        return input(" 请输入授权码（直接回车退出）：").strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def ensure_licensed(app_name=APP_NAME, parent=None):
    """程序启动时调用：已授权返回 True，未激活/用户放弃返回 False。

    典型用法：
        if not ensure_licensed(app_name="我的工具"):
            sys.exit(0)
    """
    mid = machine_id()

    # 第一次：本地已有授权码，直接校验
    saved = load_saved(app_name)
    if saved:
        ok, _msg = verify(mid, saved)
        if ok:
            return True

    # 没有或失效：弹窗要求激活，最多重试 3 次
    message = "授权码无效或已过期" if saved else ""
    for _ in range(3):
        code = _ask_gui(mid, app_name, message)
        if code is None:                    # 图形界面不可用
            code = _ask_cli(mid, app_name, message)
        if code is None:                    # 用户主动放弃
            return False
        ok, message = verify(mid, code)
        if ok:
            save_license(code, app_name)
            return True
        message = message or "授权码无效，请检查后重试"
    return False


if __name__ == "__main__":
    # 直接运行本文件：显示本机机器码，方便你报给作者
    print("本机机器码：", machine_id())
    saved = load_saved()
    if saved:
        print("当前授权状态：", verify(machine_id(), saved)[1])
    else:
        print("当前状态：未激活")
