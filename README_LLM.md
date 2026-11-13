# README_LLM.md —— 给 AI/大模型的项目技术档案

> **本文用途**：让任何大模型（或新维护者）读完后能直接、安全地修改本项目。
> 请配合 `README.md`（用户视角功能说明）和 `CHANGELOG.md`（逐版本变更史）一起阅读。
> 行号以 **v1.7.1** 的 `calendar_app.py`（约 5068 行）为准，改动后行号会漂移，
> 以符号名（类/函数/常量）搜索为准。

---

## 0. 一句话认识本项目

Windows 桌面日历 + 待办清单。**单文件 tkinter 应用**（`calendar_app.py`，约 5000 行），
Python 3.12 开发，PyInstaller 打包为**完全无依赖的单文件 exe**。数据全部落在本机
SQLite，无任何联网依赖（企业微信推送和 ICS 订阅是仅有的两种主动出网，均用户可选）。

- 源码运行：`run.bat` 或 `python calendar_app.py`
- 正式发布：`DesktopCalendar.exe`（用户日常双击的就是它）

## 1. 目录文件清单

| 文件 | 作用 |
|---|---|
| `calendar_app.py` | **全部业务代码**（UI + 数据 + 打包配置引用的唯一源文件） |
| `DesktopCalendar.spec` | PyInstaller 打包配置（单文件、图标、打包 CHANGELOG.md） |
| `DesktopCalendar.exe` | 成品 exe（重新打包后覆盖它） |
| `app.ico` | 窗口/托盘/exe 图标（托盘运行时从程序目录加载，exe 内也内嵌一份） |
| `README.md` | 面向用户的功能说明书 |
| `CHANGELOG.md` | 修订日志（**最新条目在最上面**；程序内「设置→📜修订日志」读它） |
| `run.bat` | 源码运行入口（找系统 Python 3.12 路径） |
| `settings.json` | 用户设置（运行时生成/读写，**含企业微信凭据勿外传**） |
| `data/calendar.db` | SQLite 数据库（任务/倒数日/kv） |
| `data/backup/` | 每日自动备份（保留最近 10 份） |
| `_test_float.py` | 手工测试脚本（浮窗/嵌入模式调试用，不参与打包） |
| `crash.log` / `guard.log` | 运行期问题日志（出现时读它定位） |

## 2. 构建 / 运行 / 发布流程

```powershell
# 语法检查（不会写 __pycache__）
C:\Users\W\AppData\Local\Programs\Python\Python312\python.exe -c "import ast; ast.parse(open(r'E:\99 tool\30 独立小项目\desktop_calendar\calendar_app.py', encoding='utf-8').read())"

# 源码跑起来看效果（3.12 自带 tkinter，无第三方库要求）
C:\Users\W\AppData\Local\Programs\Python\Python312\python.exe "E:\99 tool\30 独立小项目\desktop_calendar\calendar_app.py"

# 打包（必须先关掉正在运行的 DesktopCalendar.exe，否则 exe 被占用写入失败）
cd "E:\99 tool\30 独立小项目\desktop_calendar"
C:\Users\W\AppData\Local\Programs\Python\Python312\python.exe -m PyInstaller DesktopCalendar.spec --noconfirm --distpath . --workpath build
```

- spec 要点：`onefile`、`console=False`、图标 `app.ico`、`datas=[("CHANGELOG.md",".")]`。
- 打包产物直接覆盖 `DesktopCalendar.exe`（`--distpath .`）。
- **改代码的固定三步**：① 改 `APP_VERSION`；② `CHANGELOG.md` 顶部加条目；
  ③ 重新打包 exe。
- 新增**标准库以外**的依赖时必须确认 PyInstaller 能静态收集到（本项目目前
  只用标准库，托盘功能特意做成纯 ctypes 就是为了零依赖）。

## 3. calendar_app.py 代码地图（v1.7.1 行号）

| 行号 | 区块 | 说明 |
|---|---|---|
| 38–112 | Win32 助手 | `ctypes` 导入（`_user32/_kernel32/_shell32`，非 Windows 置 None）、`_toplevel_hwnd()`(115) 取 Tk 控件的真实 HWND、`_pin_above_wallpaper()`(178) 贴桌面壁纸层、`_primary_work_area()` 多显示器工作区 |
| 333–412 | 屏幕外救援 + 单实例（v1.7.1） | `_screen_work_areas()` 枚举显示器、`_clamp_into_screen()` 启动时把屏幕外窗口拉回主屏、`_raise_existing_instance()` 配合 `__main__` 的 CreateMutexW 做单实例保护 |
| 427–690 | **TrayIcon 类** | 系统托盘（v1.7.0 新增，见 §7），纯 ctypes |
| 628–1104 | `STR` 双语文案 | 中英两套 dict，见 §4 |
| 1106–1186 | `LANG` / `T()` | 全局语言与取词函数 `T(key, **kw)`（支持 `{n}` 占位符） |
| 1188–1360 | 工具/日期 | `day_marks()`(1282) 某日的标记（农历/节日/倒数日/任务数） |
| 1362–1435 | 企业微信 | `wecom_push(webhook, content)`(1362) 群机器人、`wecom_app_push(...)` 自建应用，均返回 `(bool, str)` |
| 1437–1462 | 农历 | `lunar_info()` 农历月日/生肖/干支（内置数据表） |
| 1464–1517 | 导入解析 | `parse_import_file()` 支持 .txt/.md/.csv/.json 四种格式 |
| 1519–1592 | **数据库** | `init_db()` 建表/旧库迁移，见 §5 |
| 1595–1797 | 备份/倒数日/ICS | `auto_backup()`(1602) 每日备份；`ics_sync()`(1772) 拉取 ICS 订阅生成任务（标题前缀 📅） |
| 1799–2030 | 周期任务引擎 | `expand_series()`(1903) 补期、`roll_pending_tasks()`(1966) 跨天顺延 |
| 2035–2108 | 设置 | `load_settings()` / `save_settings()`（settings.json 读写） |
| 2113–2137 | `ScrollFrame` | 可滚动容器（设置窗、清单页用） |
| 2142–4945 | **CalendarApp 类** | 主窗口（继承 tk.Tk），见 §6 |
| 4947–4974 | `__main__` | 授权校验已停用（4948 注释块，可恢复）；`sys.excepthook`/`threading.excepthook` 写 `crash.log`；最后 `CalendarApp().mainloop()` |

### CalendarApp 关键方法速查

| 方法 | 行号(≈) | 作用 |
|---|---|---|
| `__init__` | 2142 | 读设置→字体→DB→`_build_ui()`→**托盘初始化 + `<Unmap>` 绑定**→三个 after 循环 |
| `_on_unmap` | 2244 | **最小化进托盘入口**：state=="iconic" 时 `tray.show()` + `withdraw()` |
| `show_from_tray` | 2253 | 托盘恢复窗口：`tray.hide()` + deiconify + lift |
| `_tray_menu_items` / `_tray_menu_action` / `_tray_push_today` / `_tray_clean_done` / `tray_toast` / `_tray_tip` | ~2270–2330 | 托盘右键菜单项定义/分发、免弹窗直推、气泡反馈 |
| `_tick` | 2523 | 每分钟检查跨天 → `roll_pending_tasks` + 重渲染 |
| `refresh` | 3019 | 全量重渲染入口（日历格 + 清单页 + 标题） |
| `render_title` | 3036 | 窗口标题 + **同步托盘悬浮提示** |
| `add_task` | 3288 | 弹输入框加任务（支持 `明天 xxx`、`每周三 xxx`、`!` 重要、`@HH:MM` 时间） |
| `check_reminders` | 3638 | 每 30s 扫描到期任务 → `show_reminder_toast` |
| `push_today_to_wecom` | 3762 | 带勾选框的推送对话框（托盘推送是其免交互版本） |
| `show_reminder_toast` | 3832 | 右下角滑入提醒浮条 |
| `export_tasks` | 3947 | 导出 txt/md/csv/json |
| `persist_cfg` | 4088 | 窗口几何/透明度/状态回写 settings.json（仅 state=="normal" 时保存几何） |
| `set_embedded` | 4328 | 嵌入/移动模式切换（overrideredirect、贴壁纸层、底部吸附） |
| `open_settings` | 4440 | 设置对话框（含 📜修订日志页） |
| `on_close` | 4938 | **先 `tray.destroy()`** → persist → 关库 → destroy |

## 4. 数据库 schema（data/calendar.db，sqlite3）

```sql
tasks(
  id INTEGER PK AUTOINCREMENT,
  task_date TEXT NOT NULL,      -- 'YYYY-MM-DD'
  title   TEXT NOT NULL,
  done    INTEGER DEFAULT 0,
  repeat  TEXT DEFAULT 'day',   -- day / week / month；week 另有 interval（每 N 周）
  remind_time TEXT DEFAULT '',  -- 'HH:MM'，空=不提醒
  last_remind TEXT DEFAULT '',  -- 上次已提醒的 (date,time)，防重复弹
  important INTEGER DEFAULT 0,  -- 🔴 重要
  pinned    INTEGER DEFAULT 0,  -- 📌 置顶（清单页排序优先）
  series_id TEXT DEFAULT '',    -- 周期系列号：同系列各期共用；''=单次任务
  interval  INTEGER DEFAULT 1,  -- 周任务间隔周数
  created_at TEXT)
series_skips(series_id, task_date, PRIMARY KEY(series_id, task_date))  -- 「墓碑」
events(id, name, event_date TEXT, kind TEXT 'annual'|'countdown', lunar INTEGER)
kv(key TEXT PK, value TEXT)          -- 备份/订阅时间戳
索引：idx_tasks_date(task_date)、idx_tasks_series(series_id)
```

**series_skips 是核心设计**：用户删掉某期周期任务或「清理已完成」时，把
`(series_id, task_date)` 记进墓碑表；`expand_series()` 补期时跳过墓碑，
否则被删的期数会被当作缺期重新生成（任务「复活」bug）。**任何删除周期任务的
代码路径都必须先写墓碑**（搜 `mark_series_skips` 看现有用法）。

迁移方式：`init_db()` 里每个新列用 `try: ALTER TABLE ... except OperationalError: pass`
追加，禁止改旧列定义（用户库是活的）。

## 5. settings.json 键全集

`alpha`(0.5–1 透明度)、`topmost`(置顶)、`language`("zh"/"en")、`country`("cn" 假期库)、
`remind_early`(提前提醒分钟)、`auto_backup`、`ics_url`、`geometry`("WxH±X±Y")、
`show_holiday/show_weekno/show_lunar/show_terms/show_rest`、`week_start`("mon"/"sun")、
`cal_fg`、`accent`、`wecom_webhook`、`wecom_push`、`wecom_corp_id/wecom_agent_id/
wecom_corp_secret`(自建应用)、`bg_color`、`bg_image_path`、`embedded`(贴桌面模式)、
`desktop_bottom`(吸底)、`cal_font`/`task_font`(`{family,size}`)。

读写只有 `load_settings()/save_settings()` 两处；写入失败会弹 messagebox（模态）。
**注意**：`persist_cfg()` 只在窗口 state=="normal" 时保存 geometry，隐藏/最小化
状态下退出不会破坏已存几何。

## 6. 主程序运行时模型（理解了才能安全改）

1. **单窗口三页**：日历 / 全部清单 / 倒数日，顶部签名条切换，同一 Tk 窗口。
2. **刷新模型**：任何数据变更后调用 `self.refresh()` 全量重渲染（数据量小，够快）。
3. **三个 after 循环**：`_tick`（60s 跨天检测）、`check_reminders`（30s 提醒扫描）、
   `_ics_auto_sync`（启动后一次 + 之后低频）。都是 `self.after` 主线程定时器，**没有后台线程改 UI**；网络（WeCom/ICS）用 `threading.Thread` + 结果经 `self.after(0,...)` 回主线程。
4. **语言切换**：改 `LANG` 后 `_rebuild_ui()` 整体重建所有带文字的控件（STR 是静态
   dict，不会热刷新，新增界面必须走 `T(key)`）。
5. **嵌桌面模式**（`embedded=True`，用户默认开启）：`overrideredirect(True)` +
   `_pin_above_wallpaper` 贴壁纸层 + 吸底。此时**没有标题栏、没有最小化按钮**，
   托盘的最小化功能只作用于移动模式（`embedded=False`）——这是设计事实，不是 bug。
6. **IME 坑**：无边框窗口下 `Entry` 打不出字是历史反复出现的 bug（见 CHANGELOG
   v1.4.x–v1.6.1），根因是 `overrideredirect`/exstyle 与 IME 冲突，已有
   `_ime_safe_unoverrideredirect` 等防护。**动窗口样式相关代码前必读 CHANGELOG**。

## 7. 系统托盘（v1.7.0，纯 ctypes 零依赖）

**为什么不用 pystray/PIL**：打包体积与零依赖原则；ctypes 直调 Win32 即可。

- `TrayIcon` 类（345–608）：
  - `_create_msg_window()`：注册自己的窗口类 `DC_TrayMsgWnd` + 隐藏消息窗口。
    关键认知：**Tcl/Tk 主循环本来就在泵消息**，同线程所有窗口的消息（含托盘回调
    `WM_APP+0x11`）都会被派发，因此托盘事件天然在 Tk 主线程，无需新线程。
  - `show(tip)`：`Shell_NotifyIconW`（注意在 **shell32** 不在 user32）+ `NIM_ADD`，
    失败重试一次（任务栏刚重启场景）；图标优先 `LoadImageW(app.ico)`，退化
    `ExtractIconW(sys.executable)`（exe 内嵌图标）。
  - `set_tip(tip)`：`NIM_MODIFY` 改悬浮提示（未显示时为空操作）。
  - `_popup_menu()`：右键原生菜单，**标准三件套**：`SetForegroundWindow` →
    `TrackPopupMenu(TPM_RETURNCMD|TPM_NONOTIFY|TPM_BOTTOMALIGN)` →
    `PostMessageW(WM_NULL)`，少一步点外部不收起。菜单项每次弹出时经
    `get_menu()` 回调现取（语言切换立即生效）；项结构 `(key, label, enabled)`，
    `key=None` 表示分隔线。
  - `hide()` / `destroy()`：移除图标 / 彻底清理（窗口+图标句柄+回调引用）。
- 集成点（CalendarApp）：
  - `__init__`：`self.tray = None` **必须先于 `_build_ui()`**（render_title 会引用），
    之后创建 TrayIcon 并 `bind("<Unmap>", self._on_unmap)`。
  - `_on_unmap`：仅 `state()=="iconic"`（真实最小化）时 `tray.show()` + `withdraw()`；
    `withdraw` 自身也触发 Unmap，靠 state 检查防递归。
  - `show_from_tray`：`tray.hide()` + `deiconify()`（state 非 normal 才调）+ lift。
  - `render_title`：顺带 `tray.set_tip(self._tray_tip())` 同步「今日待办 N 条」。
  - `on_close`：第一步 `self.tray.destroy()`。
  - `tray_toast(text)`：主窗隐藏时的右下角置顶小气泡（独立 Toplevel，2.5s 自毁），
    托盘菜单动作的结果反馈都用它。

## 8. 双语文案 STR（628–1104）

- `STR = {"zh": {...}, "en": {...}}`，取词 `T("key", n=3)`，占位符 `{n}` 风格。
- **加任何用户可见文字**：zh/en 两个 dict 都要加同名 key，界面一律 `T(key)`。
- 排版：zh 区块在前（≈628–940），en 在后（≈941–1104）；托盘相关 key 在各 dict
  尾部 `tray_*` 段。

## 9. 常见修改指南（cookbook）

| 想做的事 | 怎么做 |
|---|---|
| 加一个设置项 | settings.json 键位 → `load_settings` 默认值 → `open_settings` 加控件（有 `var_traced` 即时保存机制可参考现有项）→ `persist_cfg` 存回 → zh/en 各加文案 key |
| 加托盘菜单项 | `_tray_menu_items` 列表加 `("key", T("tray_key"), True)` → `_tray_menu_action` 分发 → zh/en 加 key；若操作有结果，用 `self.tray_toast(...)` 反馈 |
| 新增/修改周期规则 | 只动 `expand_series` / `roll_pending_tasks`，务必维持墓碑语义（§5 前的警告） |
| 加数据库列 | 只在 `init_db` 追加 `try/except ALTER TABLE`，别动现有建表语句 |
| 改窗口样式/嵌入逻辑 | 先通读 CHANGELOG v1.4–v1.6.1 的 IME 三连修，改完必须真机验证中文输入法 |
| 重新发布 | §2 三步；打包前关掉正在运行的 exe |
| 排查「双击一闪就没」 | 读 `crash.log`；嵌入模式异常看 `guard.log` |
| 窗口开在屏幕外/多实例 | v1.7.1 已修：`_clamp_into_screen`（启动校验）+ `__main__` CreateMutexW 单实例保护，**别移除**；`__main__` 顶层不能 return，退出用 `sys.exit(0)` |
| 多屏下窗口半截在桌面外（顶部被截） | v1.7.3 已修：`_screen_rects`（物理矩形+工作区）+ `_window_rect`（GetWindowRect 取外框，含标题栏——winfo_rootx/y 是客户区原点，判断顶部出屏会漏）+ `_clamp_xy`（收进相交面积最大的屏）+ `_persist_geometry`（保存前钳制，正则要认 Tk 负偏移的 `-` 分隔）。**钳制基准是屏幕物理矩形，不是工作区**——压任务栏的摆放是故意的，别改回工作区 |
| 窗口缩放（v1.8.0） | 固定模式靠四边隐形把手 `_create_resize_grips/_grip_event`（place 覆盖 6px，松手钳制+保存），移动模式 `resizable(True,True)`；两者都要过 `minsize(640,420)`。**给固定模式加新东西时别用 fill 整窗的 Frame 盖住边缘**，会挡住把手热区 |
| 字体颜色（v1.8.0） | 框架文字=cal_fg（表头+日期数字），内容文字=task_fg（Treeview 样式+日面板行+格子预览常规态；重要红/完成灰特殊色不受控）。改颜色设置走 `set_color(attr,col)`→`apply_theme`+`refresh`；新增颜色设置项照抄 cal_fg 的色块行+pick_color 模式 |
| 托盘快速录入（v1.8.1） | `_tray_quick_add_dialog`：Toplevel 置顶小窗（标题+今天/明天/后天+HH:MM+重要，回车添加），只做**日任务**（repeat='day'，series_id=''）；同日同名拦截不弹系列确认（系列确认在主窗口 add_task 里）。控件挂 `self._qadd_win`。**别在这条路径上绕开同名拦截**（v1.7.2 教训） |
| 托盘线程模型（v1.8.2，红线） | TrayIcon 的消息窗口+GetMessage 泵在**独立守护线程**，WndProc 回调只 `queue.Queue` 入队，Tk 主线程 `_drain`（after 60ms 轮询）执行。**绝不允许改回让 Tcl 主循环泵托盘消息**——ctypes WndProc 在 Tcl 阻塞等待期间派发会 GIL 重入把进程打死（硬 abort，无 crash.log）。托盘线程不碰 Tk 对象；destroy 用 PostThreadMessage WM_QUIT。托盘图标启动常驻（show 在 `__init__`），`_raise_existing_instance` 靠 `DC_TrayMsgWnd` + `_WM_APP_RESTORE` 拉回缩在托盘的窗口 |
| 同一周期任务同日多条 | v1.7.2 已修四道闸：① init_db 迁移清历史重复 + 部分唯一索引 `uq_tasks_series_date(series_id, task_date) WHERE series_id != ''`；② `adopt_legacy_series` 按（标题,类型,星期几/几号,间隔）归并而非逐行编系列；③ `add_task` 同名同期命中弹 `dup_series_ask` 确认；④ `edit_task` 同系列同日冲突拦截 `edit_clash`。**动系列写入逻辑时别绕开这四道闸**；注意「删除整个系列」不留墓碑，排查历史问题要看备份 |
| 打字保护闩锁（v1.8.3，红线） | `_ime_plain` 闩锁=「打字中，跳过贴底校验」。**任何重建 UI 的代码路径（如 set_language）必须先清闩锁**（`_ime_plain=False`+停看门狗+还原分层）——重建销毁持焦点的输入框后 FocusOut 不再触发，闩锁会永久卡死，日历浮在最上层且点固定无效。所有跳过贴底校验的入口（`_bottom_tick`/`_on_win_activate`/`_ensure_desktop_bottom`）统一走 `_typing_guard_active()`（实时核对焦点真实性，失效就地自愈），**别改回盲信 `_ime_plain`** |
| 显示器热插拔（v1.8.4） | `WM_DISPLAYCHANGE` 由托盘消息窗口线程 `_proc` 捕获 → `_emit` 队列回主线程 → `_on_display_changed`（防抖 300ms）→ `_display_fix`：`_clamp_into_screen`+补贴底；`show_from_tray` 恢复时也必调 `_clamp_into_screen`（窗口可能停在幽灵屏坐标，只恢复状态等于没恢复），deiconify 失效时 withdraw+deiconify 组合拳（Unmap 有 state 检查不会误触发缩托盘）。**「显示/恢复/布局变化」三条路都必须带坐标钳制**，别只管 state |
| 日期选择控件 DateSpin（v1.8.5） | 三联 `tk.Spinbox`（年/月/日）替代手敲 YYYY-MM-DD，用在两日期相差/倒数日弹窗/编辑任务改期。**经典 tk.Spinbox 没有 `.set()`**，写值必须走 `_put()`（delete/insert）；天数随年月联动（`_sync_days` + `calendar.monthrange`，越界回落）；`get_date()` 残缺/非法返回 None 由调用方弹 `calc_bad_date`。新增日期输入一律用 DateSpin，别再开文本框 |

## 10. 已知约束与红线

1. **只允许标准库**（tkinter/sqlite3/ctypes/urllib/...）。加第三方依赖前先问一句值不值。
2. **settings.json 含企业微信凭据**，不得写入任何示例/文档/提交。
3. 所有用户可见文本必须过 `T()` 双语字典；hard-code 中文 = bug。
4. 主线程才有权碰 Tk 控件；工作线程一律 `self.after(0, lambda: ...)` 回主线程。
5. 改完跑：语法检查 → 源码启动 → 最小化/托盘路径 → 嵌入模式切换 → 再打包。
6. exe 是用户的日常入口，**发布前确认 CHANGELOG/版本号已更新**（程序内日志页直接展示）。

## 11. 验证记录（v1.7.0 托盘功能）

- 语法：`ast.parse` 通过。
- 托盘冒烟：真实 `NIM_ADD` 返回 TRUE、改 tip、`NIM_DELETE` 清理 → PASS。
- 端到端 ×2 轮（Python 3.12 源码运行）：`iconify()` 后 `state()=="withdrawn"` 且
  托盘已挂载；`show_from_tray()` 后 `state()=="normal"` 且托盘已移除；`on_close()`
  正常退出 → PASS。
- 注意：测试脚本曾出现「卡在 persist_cfg」假象，实为写 settings.json 被沙箱/杀软
  拦截后弹了**模态** messagebox 无人点——真实桌面环境无此问题，但写测试脚本时
  建议 patch 掉 `messagebox.showwarning`。
