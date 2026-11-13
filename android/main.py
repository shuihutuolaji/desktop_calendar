"""桌面日历清单 · 安卓版

Flet 实现：月历（周数/农历/节气/法定节假日调休）+ 每日任务（完成/重要/置顶/编辑）
+ 周期任务（周任务 / 月任务自动生成后续各期）+ 企业微信推送（勾选任务后发送）。
数据存手机应用沙盒（SQLite），与企业微信的配置保存在同一数据库。

业务规则与桌面版（../calendar_app.py）保持一致，改动请两边同步，
并在 CHANGELOG.md 顶部补一条修订日志。
"""

import calendar as pycal
import json
import os
import re
import shutil
import sqlite3
import threading
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import flet as ft

ACCENT = "#2563eb"
DANGER = "#dc2626"
TEXT_SUB = "#6b7280"
WEEK = ["一", "二", "三", "四", "五", "六", "日"]
TYPE_META = {"day": "日", "week": "周", "month": "月"}

HOLIDAY_CN = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Qingming Festival": "清明",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午",
    "Mid-autumn Festival": "中秋",
    "National Day": "国庆",
}


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------
def db_path() -> Path:
    """任务库路径：优先放 FLET_APP_STORAGE_DATA（应用私有持久目录）。

    旧版本误用 FLET_APP_STORAGE_CACHE——那是系统可随时清空的缓存目录，
    存储空间紧张时用户的全部任务会被静默清掉。这里顺带做一次性迁移：
    data 目录还没有库、而旧 cache 目录里有时，把它搬过来保住已有数据。"""
    data = os.environ.get("FLET_APP_STORAGE_DATA")
    if not data:  # 桌面开发模式（flet run）：落在脚本同目录
        return Path(__file__).resolve().parent / "calendar.db"
    path = Path(data) / "calendar.db"
    cache = os.environ.get("FLET_APP_STORAGE_CACHE")
    if cache and not path.exists():
        old = Path(cache) / "calendar.db"
        if old.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, path)
            except OSError:
                pass  # 迁移失败（只读等）不拦启动，按新库处理
    return path


# ---------------------------------------------------------------------------
# 周期系列（周任务 / 月任务自动生成后续各期）—— 与桌面版 v1.5.0 同一套规则
# ---------------------------------------------------------------------------
# 每条周/月任务新增时一次性生成未来若干期，各自是独立的一行（各自可勾选完成、
# 各自到点提醒），靠 series_id 串成一条系列。提前生成的窗口：
SERIES_HORIZON_DAYS = {"week": 70, "month": 400}   # 周任务约 10 期 / 月任务约 13 期
SERIES_MAX_STEP = 300                              # 单次生成期数上限（防死循环）


def new_series_id() -> str:
    """生成一个新的系列号（周/月任务用），同系列各期共享"""
    return "s" + uuid.uuid4().hex[:12]


def series_next(d: date, rep: str, mday0: int) -> date:
    """按周期规则给出下一期日期：周任务 +7 天；月任务取下月同一天（不足截断到月末）"""
    if rep == "week":
        return d + timedelta(days=7)
    y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
    return date(y, m, min(mday0, pycal.monthrange(y, m)[1]))


def series_horizon_end(rep: str, today: date) -> date:
    """该类型的生成窗口截止日（今天 + 预设天数）"""
    return today + timedelta(days=SERIES_HORIZON_DAYS.get(rep, 0))


def series_dates(first: date, rep: str, end: date) -> list:
    """列出从 first 起、按周期规则推进、不晚于 end 的所有期次日期（含 first）"""
    out = [first]
    if rep not in SERIES_HORIZON_DAYS:
        return out
    d, mday0 = first, first.day
    while len(out) < SERIES_MAX_STEP:
        d = series_next(d, rep, mday0)
        if d > end:
            break
        out.append(d)
    return out


def expand_series(conn, today: date) -> int:
    """给每个周期系列补齐未来的期次（启动 / 跨天 / 改系列后调用）。

    取该系列已有的最后一期，按星期几 / 每月几号继续往后推，一直补到窗口截止日。
    标题 / 提醒 / 重要 / 置顶沿用系列首期；同一天已有该系列的任务就跳过。
    返回新增期数。"""
    rows = conn.execute(
        "SELECT series_id, repeat, MIN(task_date), MAX(task_date) FROM tasks "
        "WHERE series_id != '' AND repeat IN ('week', 'month') "
        "GROUP BY series_id, repeat").fetchall()
    added = 0
    for sid, rep, first, last in rows:
        try:
            d0, d = date.fromisoformat(first), date.fromisoformat(last)
        except (ValueError, TypeError):
            continue
        tmpl = conn.execute(
            "SELECT title, remind_time, important, pinned FROM tasks "
            "WHERE series_id = ? ORDER BY task_date, id LIMIT 1", (sid,)).fetchone()
        if not tmpl:
            continue
        title, rtime, imp, pin = tmpl
        end = series_horizon_end(rep, today)
        batch, step = [], 0
        while d < end and step < SERIES_MAX_STEP:
            d = series_next(d, rep, d0.day)
            step += 1
            if d > end:
                break
            if conn.execute(
                "SELECT 1 FROM tasks WHERE series_id = ? AND task_date = ? LIMIT 1",
                    (sid, d.isoformat())).fetchone():
                continue
            batch.append((d.isoformat(), title, rep, rtime or "", imp or 0,
                          pin or 0, sid))
        if batch:
            conn.executemany(
                "INSERT INTO tasks (task_date, title, repeat, remind_time, "
                "important, pinned, series_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch)
            added += len(batch)
    if added:
        conn.commit()
    return added


class Store:
    def __init__(self):
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_date TEXT NOT NULL, title TEXT NOT NULL,
                done INTEGER DEFAULT 0, repeat TEXT DEFAULT 'day',
                remind_time TEXT DEFAULT '', important INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0, series_id TEXT DEFAULT '')"""
        )
        try:  # 旧库升级：补周期系列号（已有任务不受影响，仍是空串）
            self.conn.execute("ALTER TABLE tasks ADD COLUMN series_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_series ON tasks(series_id)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.conn.commit()

    def tasks_on(self, day: str):
        # 末尾多返回 repeat：任务行要显示「周 / 月」标签
        return self.conn.execute(
            "SELECT id, title, done, important, pinned, remind_time, repeat FROM tasks "
            "WHERE task_date = ? ORDER BY pinned DESC, done, id", (day,)).fetchall()

    def counts_by_date(self, first: str, last: str):
        rows = self.conn.execute(
            "SELECT task_date, COUNT(*) FROM tasks WHERE task_date BETWEEN ? AND ? "
            "GROUP BY task_date", (first, last)).fetchall()
        return dict(rows)

    def add(self, day: str, title: str, repeat: str, important: bool,
            rtime: str = ""):
        """添加任务；周/月任务一次性生成未来各期（共享 series_id）。
        返回 (生成期数, 最后一期日期)。"""
        try:
            first = date.fromisoformat(day)
        except ValueError:
            return 0, day
        sid = new_series_id() if repeat in ("week", "month") else ""
        dates = series_dates(first, repeat, series_horizon_end(repeat, date.today()))
        self.conn.executemany(
            "INSERT INTO tasks (task_date, title, repeat, remind_time, important, "
            "series_id) VALUES (?,?,?,?,?,?)",
            [(d.isoformat(), title, repeat, rtime, int(important), sid)
             for d in dates])
        self.conn.commit()
        return len(dates), dates[-1].isoformat()

    def task_row(self, tid: int):
        """取一条任务的完整字段（编辑弹窗用）"""
        return self.conn.execute(
            "SELECT title, task_date, repeat, remind_time, series_id FROM tasks "
            "WHERE id = ?", (tid,)).fetchone()

    def series_count(self, sid: str) -> int:
        if not sid:
            return 0
        return self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE series_id = ?", (sid,)).fetchone()[0]

    def update_task(self, tid: int, title: str, day: str, repeat: str,
                    rtime: str, apply_series: bool = False):
        """保存修改。apply_series=True（周期系列）时：
        - 只改内容 -> 同步到本条及之后各期；
        - 改日期或类型 -> 以新日期为新锚点，撤掉其余未完成期次后重排；
        - 改回日任务 -> 撤掉其余未完成期次，本条脱离系列。
        已完成的期次一律作为历史保留。"""
        row = self.task_row(tid)
        if not row:
            return
        old_title, dstr, rep, _rt, sid = row
        n = self.series_count(sid)
        if apply_series and sid and n > 1:
            if repeat not in ("week", "month"):
                self.conn.execute(
                    "DELETE FROM tasks WHERE series_id = ? AND id != ? AND done = 0",
                    (sid, tid))
                self.conn.execute(
                    "UPDATE tasks SET title=?, task_date=?, repeat=?, remind_time=?, "
                    "series_id='' WHERE id=?", (title, day, repeat, rtime, tid))
            elif (repeat != rep) or (day != dstr):
                self.conn.execute(
                    "DELETE FROM tasks WHERE series_id = ? AND id != ? AND done = 0",
                    (sid, tid))
                self.conn.execute(
                    "UPDATE tasks SET title=?, task_date=?, repeat=?, remind_time=? "
                    "WHERE id=?", (title, day, repeat, rtime, tid))
                self.conn.commit()
                expand_series(self.conn, date.today())
            else:
                self.conn.execute(
                    "UPDATE tasks SET title=?, remind_time=? WHERE series_id = ? "
                    "AND task_date >= ?", (title, rtime, sid, dstr))
        else:
            self.conn.execute(
                "UPDATE tasks SET title=?, task_date=?, repeat=?, remind_time=? "
                "WHERE id=?", (title, day, repeat, rtime, tid))
        self.conn.commit()

    def delete_series(self, sid: str):
        if sid:
            self.conn.execute("DELETE FROM tasks WHERE series_id = ?", (sid,))
            self.conn.commit()

    def expand(self, today: date) -> int:
        """补齐所有周期系列的后续期次（启动 / 跨天时调用）"""
        return expand_series(self.conn, today)

    def toggle_done(self, tid: int, done: bool):
        self.conn.execute("UPDATE tasks SET done=? WHERE id=?", (int(done), tid))
        self.conn.commit()

    def toggle_important(self, tid: int):
        self.conn.execute("UPDATE tasks SET important = 1 - important WHERE id=?", (tid,))
        self.conn.commit()

    def delete(self, tid: int):
        self.conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()


# ---------------------------------------------------------------------------
# 农历 / 节假日（纯 Python 库，缺失时优雅降级）
# ---------------------------------------------------------------------------
_lunar_cache = {}


def day_marks(d: date):
    try:
        from chinese_calendar import get_holiday_detail, is_workday
        is_hol, name = get_holiday_detail(d)
        work = is_workday(d)
        cn = HOLIDAY_CN.get(name, (name or "")[:6]) if (is_hol and name) else None
        makeup = (not is_hol) and work and d.weekday() >= 5
        # 休息日 = 法定节假日 或 没被调成上班的周末。不能直接拿 is_hol：
        # 装了 chinese_calendar 后普通周末 is_hol=False，月历就全都不显示「休」，
        # 与未装库时的兜底行为（周末即休）不一致。桌面版也修过同样的问题。
        is_rest = is_hol or (d.weekday() >= 5 and not work)
        return cn, is_rest, makeup
    except Exception:  # noqa: BLE001
        return None, d.weekday() >= 5, False


def lunar_info(d: date):
    key = d.isoformat()
    if key not in _lunar_cache:
        text, term = "", None
        try:
            import cnlunar
            lu = cnlunar.Lunar(datetime(d.year, d.month, d.day), godType="8char")
            month_cn = re.sub(r"[大小]$", "", lu.lunarMonthCn)
            text = month_cn if lu.lunarDayCn == "初一" else lu.lunarDayCn
            term = lu.todaySolarTerms if lu.todaySolarTerms not in ("无", "") else None
        except Exception:  # noqa: BLE001
            pass
        _lunar_cache[key] = (text, term)
    return _lunar_cache[key]


# ---------------------------------------------------------------------------
# 修订日志（与桌面版同一份习惯：改完代码在 CHANGELOG.md 顶部补一条）
# ---------------------------------------------------------------------------
CHANGELOG_PATH = Path(__file__).resolve().parent / "CHANGELOG.md"


def load_changelog() -> str:
    """读取修订日志；文件缺失返回空串（界面会给出提示文案）"""
    try:
        return CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 企业微信推送
# ---------------------------------------------------------------------------
def _clip_utf8(text: str, limit: int = 4000) -> str:
    """按 UTF-8 字节数安全截断。企业微信 markdown 上限 4096 字节，
    中文每字占 3 字节，按字符切片（text[:4000]）最长可达 1.2 万字节，会被拒收。"""
    data = text.encode("utf-8")
    return text if len(data) <= limit else data[:limit].decode("utf-8", "ignore")


def wecom_push(webhook: str, content: str):
    if not webhook:
        return False, "Webhook 为空"
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": _clip_utf8(content)}}
    ).encode()
    req = urllib.request.Request(webhook, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("errcode") == 0:
                return True, ""
            return False, f"{data.get('errcode')} {data.get('errmsg', '')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------------------------------------------------------------------------
# 界面
# ---------------------------------------------------------------------------
class CalendarApp:
    def __init__(self, page: ft.Page):
        self.page = page
        page.title = "桌面日历清单"
        page.padding = 0
        page.bgcolor = ft.Colors.GREY_100
        self.store = Store()
        self.today = date.today()
        self.sel_date = self.today
        self.view_year, self.view_month = self.today.year, self.today.month

        self.txt_month = ft.Text(size=18, weight=ft.FontWeight.BOLD, expand=True,
                                 text_align=ft.TextAlign.CENTER)
        self.grid_area = ft.Column(spacing=0)
        self.lbl_day = ft.Text(size=15, weight=ft.FontWeight.BOLD)
        self.lbl_stat = ft.Text(size=12, color=TEXT_SUB)
        self.task_list = ft.ListView(spacing=4, expand=True)
        self.ent_task = ft.TextField(hint_text="新任务…", expand=True, dense=True,
                                     on_submit=lambda e: self.add_task())
        # 新增任务的类型（日/周/月）与附加选项：周任务选星期、月任务选几号、
        # 提醒时间（HH:MM，可空）。周/月任务会按系列一次性生成未来各期。
        self.rep = "day"
        self.rep_weekday = self.sel_date.weekday()
        self.ent_mday = ft.TextField(hint_text="几号", width=70, dense=True,
                                     value=str(self.sel_date.day))
        self.ent_remind = ft.TextField(hint_text="提醒 HH:MM", width=110, dense=True)
        self.type_chips = {}
        self.week_chips = {}

        page.add(self.build_root())
        self.store.expand(self.today)   # 启动时补齐周期系列的未来各期
        self.set_rep("day")             # 初始化类型块外观（周/月附加项默认隐藏）
        self.refresh()

    # ----- 构建 -----
    def _chip(self, label: str, on_click, selected: bool):
        """小块按钮（Container 实现，比 Dropdown 更省事，也不受 Flet 版本 API 差异影响）"""
        return ft.Container(
            ft.Text(label, size=12,
                    color=ft.Colors.WHITE if selected else ft.Colors.GREY_800),
            bgcolor=ACCENT if selected else ft.Colors.WHITE,
            border_radius=6, padding=4, ink=True, on_click=on_click)

    def set_rep(self, rep: str):
        """切换新任务类型：重画类型块，并按类型显示「选星期」或「选几号」"""
        self.rep = rep
        for key, c in self.type_chips.items():
            on = (key == rep)
            c.bgcolor = ACCENT if on else ft.Colors.WHITE
            c.content.color = ft.Colors.WHITE if on else ft.Colors.GREY_800
        if self.week_chips:
            for i, c in self.week_chips.items():
                on = (i == self.rep_weekday)
                c.bgcolor = ACCENT if on else ft.Colors.WHITE
                c.content.color = ft.Colors.WHITE if on else ft.Colors.GREY_800
        self.week_row.visible = (rep == "week")
        self.ent_mday.visible = (rep == "month")
        self.page.update()

    def set_weekday(self, i: int):
        self.rep_weekday = i
        self.set_rep(self.rep)
    def build_root(self):
        header = ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: self.shift(-1)),
            self.txt_month,
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: self.shift(1)),
            ft.IconButton(ft.Icons.TODAY, tooltip="今天", on_click=lambda e: self.go_today()),
        ])
        week_row = ft.Row([
            ft.Container(ft.Text("周", size=11, color=TEXT_SUB,
                                 text_align=ft.TextAlign.CENTER),
                         expand=2),
            *[ft.Container(ft.Text("周" + w, size=12, weight=ft.FontWeight.BOLD,
                                   color=TEXT_SUB, text_align=ft.TextAlign.CENTER),
                           expand=5) for w in WEEK],
        ], spacing=2)
        # 类型块：日 / 周 / 月（周任务再选星期、月任务再选几号）
        type_row = ft.Row(spacing=6)
        for key, label in (("day", "日任务"), ("week", "周任务"), ("month", "月任务")):
            chip = self._chip(label, lambda e, k=key: self.set_rep(k),
                              key == "day")
            self.type_chips[key] = chip
            type_row.controls.append(chip)
        self.week_row = ft.Row(spacing=4, wrap=True, visible=False)
        for i, w in enumerate(WEEK):
            chip = self._chip("周" + w, lambda e, i=i: self.set_weekday(i), False)
            self.week_chips[i] = chip
            self.week_row.controls.append(chip)
        self.ent_mday.visible = False
        return ft.Column([
            ft.Container(header, padding=ft.Margin.symmetric(horizontal=4, vertical=2)),
            ft.Container(week_row, padding=ft.Margin.symmetric(horizontal=8)),
            ft.Container(self.grid_area, padding=ft.Margin.symmetric(horizontal=8)),
            ft.Divider(height=2),
            ft.Container(
                ft.Row([self.lbl_day, ft.Container(expand=True), self.lbl_stat]),
                padding=ft.Margin.symmetric(horizontal=12, vertical=4)),
            self.task_list,
            ft.Container(
                ft.Row([
                    self.ent_task,
                    ft.Button("添加", on_click=lambda e: self.add_task()),
                ], spacing=6),
                padding=8),
            ft.Container(
                ft.Column([
                    type_row,
                    ft.Row([self.week_row, self.ent_mday, self.ent_remind],
                           spacing=6, wrap=True),
                ], spacing=4, tight=True),
                padding=ft.Margin.only(left=8, right=8, bottom=4)),
            ft.Container(
                ft.Row([
                    ft.Button("推送今日待办到企业微信",
                                      icon=ft.Icons.SEND,
                                      on_click=lambda e: self.open_push_dialog()),
                    ft.IconButton(ft.Icons.SETTINGS, tooltip="设置",
                                  on_click=lambda e: self.open_settings()),
                ], alignment=ft.MainAxisAlignment.CENTER),
                padding=ft.Margin.only(bottom=8)),
        ], expand=True, spacing=2)

    def refresh(self):
        # 跨天滚动：应用常驻后台过午夜后 today 仍停在昨天，
        # 「今天」高亮和「推送今日待办」都会错位，每次刷新先校准；
        # 选中日期正停在「今天」时一并跟到新的一天（翻月浏览则不打扰）
        now = date.today()
        if now != self.today:
            if self.sel_date == self.today:
                self.sel_date = now
            self.today = now
            self.store.expand(self.today)   # 新的一天：周期系列再往后补一期
        self.txt_month.value = f"{self.view_year} 年 {self.view_month} 月"
        first = date(self.view_year, self.view_month, 1)
        last = date(self.view_year, self.view_month,
                    pycal.monthrange(self.view_year, self.view_month)[1])
        counts = self.store.counts_by_date(first.isoformat(), last.isoformat())
        start = first - timedelta(days=first.weekday())
        sel = self.sel_date.isoformat()

        rows = []
        for r in range(6):
            cells = [ft.Container(ft.Text(
                (start + timedelta(days=r * 7)).isocalendar()[1],
                size=10, color=TEXT_SUB, text_align=ft.TextAlign.CENTER), expand=2)]
            for c in range(7):
                d = start + timedelta(days=r * 7 + c)
                cells.append(self.day_cell(d, d.month == self.view_month,
                                           counts.get(d.isoformat(), 0), sel))
            rows.append(ft.Row(cells, spacing=2))
        self.grid_area.controls = rows
        self.render_day_panel()
        self.page.update()

    def day_cell(self, d: date, in_month: bool, n: int, sel: str):
        hname, is_rest, makeup = day_marks(d) if in_month else (None, False, False)
        ltext, term = lunar_info(d) if in_month else ("", None)
        bg = ft.Colors.WHITE
        fg = ft.Colors.GREY_800
        if hname:
            bg = "#fef2f2"
            fg = DANGER
        if not in_month:
            bg = ft.Colors.GREY_100
            fg = ft.Colors.GREY_400
        if d == self.today:
            bg = "#fef9c3"
        if d.isoformat() == sel:
            bg = "#dbeafe"
        # 日期旁信息槽优先级：节日名(红) > 节气(绿) > 农历(灰)
        slot, slot_color = None, TEXT_SUB
        if hname:
            slot, slot_color = hname, DANGER
        elif term:
            slot, slot_color = term, "#059669"
        elif ltext:
            slot = ltext

        top = ft.Row([
            ft.Text(str(d.day), size=14, weight=ft.FontWeight.BOLD, color=fg),
            ft.Text(slot or "", size=9, color=slot_color),
        ], spacing=2)
        badges = []
        if n:
            badges.append(ft.Container(ft.Text(str(n), size=9, color=ACCENT), bgcolor="#dbeafe", border_radius=8, padding=2))
        if in_month and makeup:
            badges.append(ft.Container(ft.Text("班", size=9, color=ACCENT), bgcolor="#dbeafe", border_radius=8, padding=2))
        elif in_month and is_rest:
            badges.append(ft.Container(ft.Text("休", size=9, color=DANGER), bgcolor="#fee2e2", border_radius=8, padding=2))
        top_row = ft.Row([top, ft.Row(badges, spacing=2, wrap=True)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        lines = [ft.Text(t[:6], size=8,
                         color=DANGER if (imp and not dn) else
                         (ft.Colors.GREY_400 if dn else TEXT_SUB))
                 for _tid, t, dn, imp, _p, _r, _rep in
                 self.store.tasks_on(d.isoformat())[:2]
                 ] if in_month else []
        content = ft.Column([top_row, *lines], spacing=0, tight=True)
        return ft.Container(content, expand=5, bgcolor=bg, border_radius=6,
                            padding=3, ink=True,
                            on_click=lambda e, dd=d: self.select_day(dd))

    def render_day_panel(self):
        d = self.sel_date
        week = "周" + WEEK[d.weekday()]
        tasks = self.store.tasks_on(d.isoformat())
        pending = sum(1 for _i, _t, dn, _im, _p, _r, _rp in tasks if not dn)
        mark = "（今天）" if d == self.today else ""
        self.lbl_day.value = f"{d.month}月{d.day}日 {week}{mark}"
        self.lbl_stat.value = f"待办 {pending} / 共 {len(tasks)}"
        rows = []
        if not tasks:
            rows.append(ft.Container(ft.Text("当天暂无任务", color=ft.Colors.GREY_400),
                                     alignment=ft.MainAxisAlignment.CENTER, padding=20))
        for tid, title, done, imp, pin, rtime, rep in tasks:
            # 周/月任务带类型标签，一眼看出这是自动生成的周期任务
            tag = f"[{TYPE_META.get(rep, '')}]" if rep in ("week", "month") else ""
            disp = ("📌 " if pin else "") + tag + title
            if rtime:
                disp += f" ⏰{rtime}"
            color = ft.Colors.GREY_400 if done else (DANGER if imp else ft.Colors.GREY_800)
            rows.append(ft.Container(
                ft.Row([
                    ft.Checkbox(value=bool(done), on_change=lambda e, t=tid: (
                        self.store.toggle_done(t, e.control.value), self.refresh())),
                    ft.Text(disp, size=14, color=color,
                            weight=ft.FontWeight.W_500 if imp and not done else None,
                            expand=True),
                    ft.IconButton(ft.Icons.EDIT, icon_color=TEXT_SUB,
                                  icon_size=18, tooltip="编辑",
                                  on_click=lambda e, t=tid: self.open_edit_dialog(t)),
                    ft.IconButton(ft.Icons.STAR if imp else ft.Icons.STAR_BORDER,
                                  icon_color=DANGER if imp else TEXT_SUB,
                                  icon_size=18, tooltip="重要",
                                  on_click=lambda e, t=tid: (
                                      self.store.toggle_important(t), self.refresh())),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=TEXT_SUB,
                                  icon_size=18, tooltip="删除",
                                  on_click=lambda e, t=tid: (
                                      self.store.delete(t), self.refresh())),
                ], spacing=0),
                bgcolor=ft.Colors.WHITE, border_radius=8, padding=2))
        self.task_list.controls = rows

    # ----- 动作 -----
    def select_day(self, d: date):
        self.sel_date = d
        if (d.year, d.month) != (self.view_year, self.view_month):
            self.view_year, self.view_month = d.year, d.month
        self.refresh()

    def shift(self, delta: int):
        m = self.view_month + delta
        if m == 0:
            self.view_year, self.view_month = self.view_year - 1, 12
        elif m == 13:
            self.view_year, self.view_month = self.view_year + 1, 1
        else:
            self.view_month = m
        self.refresh()

    def go_today(self):
        self.today = date.today()
        self.sel_date = self.today
        self.view_year, self.view_month = self.today.year, self.today.month
        self.refresh()

    def add_task(self):
        """添加任务：日任务 = 所选日期（1 条）；周/月任务 = 按所选星期 / 几号
        一次性生成未来各期（同 series_id，每期各自可勾选完成、提醒时间相同）。"""
        title = (self.ent_task.value or "").strip()
        if not title:
            return
        rtime = (self.ent_remind.value or "").strip()
        if rtime and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", rtime):
            self.toast("提醒时间应为 HH:MM，例如 09:30")
            return
        d = self.sel_date
        if self.rep == "week":
            # 本周所选星期几；那天已过则顺延到下一周
            d = d - timedelta(days=d.weekday()) + timedelta(days=self.rep_weekday)
            if d < self.today:
                d += timedelta(days=7)
        elif self.rep == "month":
            try:
                mday = int((self.ent_mday.value or "").strip() or d.day)
            except ValueError:
                mday = d.day
            mday = max(1, min(31, mday))
            d = date(d.year, d.month,
                     min(mday, pycal.monthrange(d.year, d.month)[1]))
            if d < self.today:      # 本月这天已过 -> 顺延到下月
                y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
                d = date(y, m, min(mday, pycal.monthrange(y, m)[1]))
        n, last = self.store.add(d.isoformat(), title, self.rep, False, rtime)
        self.ent_task.value = ""
        self.ent_task.focus()
        self.sel_date = d          # 跳到新任务所在日期，面板立刻能看到它
        self.view_year, self.view_month = d.year, d.month
        self.refresh()
        if n > 1:
            self.toast(f"已生成 {n} 期（到 {last}）")

    def toast(self, msg: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(msg), duration=2500))

    # ----- 编辑任务（保存按钮 / 周期系列同步） -----
    def open_edit_dialog(self, tid: int):
        """编辑已有任务：标题 / 日期 / 类型 / 提醒，点「保存」写库。

        周期系列（周/月任务）多一项「应用到整个系列」：只改内容则同步后续各期；
        改日期或类型则以新日期为新锚点重排后续未完成期次（已完成的当历史保留）。"""
        row = self.store.task_row(tid)
        if not row:
            return
        title, dstr, rep, rtime, sid = row
        n = self.store.series_count(sid)
        f_title = ft.TextField(label="任务内容", value=title)
        f_date = ft.TextField(label="日期 YYYY-MM-DD", value=dstr, width=170)
        f_remind = ft.TextField(label="提醒 HH:MM（可空）", value=rtime or "",
                                width=170)
        state = {"rep": rep}
        chips = {}

        def pick(k):
            state["rep"] = k
            for key, c in chips.items():
                on = (key == k)
                c.bgcolor = ACCENT if on else ft.Colors.WHITE
                c.content.color = ft.Colors.WHITE if on else ft.Colors.GREY_800
            self.page.update()

        chip_row = ft.Row(spacing=6)
        for key, label in (("day", "日任务"), ("week", "周任务"),
                           ("month", "月任务")):
            chips[key] = self._chip(label, lambda e, k=key: pick(k), key == rep)
            chip_row.controls.append(chips[key])

        content = [f_title, ft.Row([f_date, f_remind], spacing=6, wrap=True),
                   chip_row]
        cb_series = None
        if sid and n > 1:
            cb_series = ft.Checkbox(label=f"应用到整个系列（共 {n} 期）", value=True)
            content.append(cb_series)
            content.append(ft.Text("改日期或类型会重排后续未完成的期次",
                                   size=11, color=TEXT_SUB))

        def on_save(e):
            new_title = (f_title.value or "").strip()
            if not new_title:
                self.toast("任务内容不能为空")
                return
            try:
                new_date = date.fromisoformat((f_date.value or "").strip())
            except ValueError:
                self.toast("日期应为 YYYY-MM-DD")
                return
            new_rt = (f_remind.value or "").strip()
            if new_rt and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", new_rt):
                self.toast("提醒时间应为 HH:MM")
                return
            apply_all = bool(cb_series and cb_series.value)
            self.store.update_task(tid, new_title, new_date.isoformat(),
                                   state["rep"], new_rt, apply_all)
            self.page.pop_dialog()
            self.sel_date = new_date
            self.view_year, self.view_month = new_date.year, new_date.month
            self.refresh()
            self.toast("已保存")

        actions = [
            ft.TextButton("取消", on_click=lambda e: self.page.pop_dialog()),
            ft.FilledButton("保存", on_click=on_save),
        ]
        edit_dlg = ft.AlertDialog(
            title=ft.Text("编辑任务"),
            content=ft.Column(content, tight=True, spacing=6),
            actions=actions)
        if sid and n > 1:
            actions.insert(1, ft.TextButton(
                "删整系列",
                on_click=lambda e: self.confirm_delete_series(sid, edit_dlg)))
        self.page.show_dialog(edit_dlg)

    def confirm_delete_series(self, sid: str, close_also=None):
        """删整条系列前的二次确认（一次会删掉该系列的所有期次）。

        close_also：从编辑弹窗里点进来时，把编辑弹窗一起关掉——
        任务已不存在，留着它会出现「改了不存在的任务」的错觉。"""
        n = self.store.series_count(sid)

        def do_delete(e):
            self.store.delete_series(sid)
            self.page.pop_dialog()          # 关确认框
            if close_also is not None:      # 再关它下面的编辑框
                try:
                    self.page.pop_dialog()
                except Exception:            # noqa: BLE001
                    pass
            self.refresh()
            self.toast(f"已删除整个系列（{n} 期）")

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("删除整个系列？"),
            content=ft.Text(f"该周期任务共 {n} 期，将全部删除。"),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self.page.pop_dialog()),
                ft.FilledButton("删除", on_click=do_delete),
            ]))

    # ----- 企业微信 -----
    def open_push_dialog(self):
        tasks = self.store.tasks_on(self.today.isoformat())
        if not tasks:
            self.toast("今天还没有任务")
            return
        items = [{"tid": t[0], "title": t[1], "done": t[2], "imp": t[3],
                  "pin": t[4], "rtime": t[5], "v": not t[2]} for t in tasks]
        column = ft.Column(spacing=2, tight=True)
        for it in items:
            disp = ("📌 " if it["pin"] else "") + it["title"] \
                + (f" ⏰{it['rtime']}" if it["rtime"] else "")
            mark = "✅ " if it["done"] else ("🔴 " if it["imp"] else "")
            column.controls.append(ft.Checkbox(
                label=f"{mark}{disp}", value=it["v"],
                on_change=lambda e, it=it: it.__setitem__("v", e.control.value)))
        dlg = ft.AlertDialog(
            title=ft.Text(f"推送 {self.today.month}月{self.today.day}日 任务"),
            content=ft.Container(column, width=320,
                                 height=min(60 + 40 * len(items), 380)))

        def do_push(e):
            sel = [it for it in items if it["v"]]
            if not sel:
                self.toast("请至少勾选一条")
                return
            self.page.pop_dialog()
            lines = [f"**📋 桌面日历清单 · {self.today.month}月{self.today.day}日（{len(sel)} 条）**"]
            for it in sel:
                mark = "✅" if it["done"] else ("🔴 " if it["imp"] else "")
                text = ("📌 " if it["pin"] else "") + it["title"] \
                    + (f"（⏰{it['rtime']}）" if it["rtime"] else "")
                lines.append(f"{mark} {text}")
            self.send_to_wecom("\n".join(lines))

        dlg.actions = [
            ft.TextButton("取消", on_click=lambda e: self.page.pop_dialog()),
            ft.FilledButton("推送", on_click=do_push),
        ]
        self.page.show_dialog(dlg)

    def send_to_wecom(self, content: str):
        webhook = self.store.get_setting("webhook")
        if not webhook:
            self.toast("请先在设置里填写 Webhook")
            self.open_settings()
            return

        def work():
            ok, err = wecom_push(webhook, content)
            msg = "已推送到企业微信" if ok else f"推送失败：{err}"
            self.page.show_dialog(ft.SnackBar(ft.Text(msg), duration=3000))

        threading.Thread(target=work, daemon=True).start()

    def open_settings(self):
        ent = ft.TextField(label="企业微信 Webhook",
                           value=self.store.get_setting("webhook"),
                           hint_text="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…")

        def on_test(e):
            hook = ent.value.strip()
            if not hook:
                self.toast("请先填写 Webhook")
                return

            def work():
                ok, err = wecom_push(hook, "**桌面日历清单** 安卓版推送测试成功 ✅")
                msg = "测试成功，请到群里查看" if ok else f"失败：{err}"
                self.page.show_dialog(ft.SnackBar(ft.Text(msg), duration=3000))

            threading.Thread(target=work, daemon=True).start()

        def on_save(e):
            self.store.set_setting("webhook", ent.value.strip())
            self.page.pop_dialog()
            self.toast("已保存")

        dlg = ft.AlertDialog(
            title=ft.Text("设置"),
            content=ft.Column([ent,
                               ft.Text("获取：群聊 → 设置 → 群机器人 → 添加 → 复制地址",
                                       size=11, color=TEXT_SUB)], tight=True),
            actions=[
                ft.TextButton("修订日志", on_click=lambda e: self.open_changelog()),
                ft.TextButton("测试", on_click=on_test),
                ft.TextButton("保存", on_click=on_save),
                ft.TextButton("取消", on_click=lambda e: self.page.pop_dialog()),
            ])
        self.page.show_dialog(dlg)

    def open_changelog(self):
        """显示修订日志：读同目录 CHANGELOG.md，方便随时回看改了什么"""
        text = load_changelog()
        if not text:
            self.toast("未找到 CHANGELOG.md（应放在程序同目录）")
            return
        lv = ft.ListView(spacing=2, expand=True)
        lv.controls = [ft.Text(text, size=11)]
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("修订日志"),
            content=ft.Container(lv, width=340, height=380),
            actions=[ft.TextButton("关闭",
                                   on_click=lambda e: self.page.pop_dialog())]))


def main(page: ft.Page):
    CalendarApp(page)


if __name__ == "__main__":
    ft.run(main)
