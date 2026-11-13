# 桌面日历清单（Desktop Calendar）

个人任务跟进小工具：**桌面便签式月历 + 任务管理 + 周期提醒 + 农历节假日**，数据全部本地存储，无任何强制联网依赖。

一套功能、两个平台：

| 平台 | 技术 | 当前版本 | 位置 |
|---|---|---|---|
| **Windows 桌面版** | Python + Tkinter（单文件） | v1.8.5 | `calendar_app.py` |
| **Android 原生版** | Kotlin + Jetpack Compose | v1.6.0 | `android-native/` |

两端**数据格式互通**：导入/导出的 JSON / CSV 完全一致可互导，安卓版数据库与桌面版 `calendar.db` 同结构同列名，桌面版的库甚至可直接拷到手机上用。

> `android/` 目录是早期 Flet 原型，**已废弃**，仅留作对照，与现行安装包无关。

## ✨ 功能总览

### 日历与显示

- 月历视图：**周数 / 农历 / 24 节气 / 法定节假日与调休**（节假日整段标红、休息日「休」/ 补班日「班」角标）
- 月历格子直接显示每天的任务数量角标和前几条任务标题（桌面 3 条 / 手机 2 条）
- 显示项可逐项开关；每周起始周一/周日可切换；**中英双语即时切换**
- 日期计算页：两日期相差、今天 ±N 天、节日倒计时、倒数日 / 纪念日（支持按农历，每年自动换算公历）

### 任务管理

- **周期任务**：日 / 周 / 月 / 工作日任务（按节假日数据跳过周末与法定节假日，调休补班日照常），周任务支持每 N 周间隔
- **未完成自动顺延**：日任务顺延到次日、周任务顺延到下周同一天、月任务顺延到下月同一天（31 号在短月按月末截断），直到做完为止
- 重要 ⭐ / 置顶 📌、类型标签点击切换、全部清单页（逾期/今天/未来/已完成着色，双击切换完成，批量清理）
- 防重复四道防线：数据库唯一索引、系列归并、同名同期添加确认、编辑撞期拦截

### 提醒与推送

- 任务提醒：到点弹窗（桌面右下角置顶弹窗 + 提示音；手机系统闹钟 + 通知），支持提前提醒（5 分钟 ~ 1 天），错过补弹（同一周期只弹一次）
- **企业微信推送**：群机器人 Webhook 和自建应用两个通道，可同时启用；「推送今日待办」先弹任务勾选框，只推选中的任务
- Windows 系统托盘常驻：悬浮提示今日待办数，右键快捷菜单（新增任务 / 推送待办 / 清理已完成 / 设置）

### 桌面版专属

- 窗口透明度 / 置顶 / 贴桌面底层、**开机自启**、窗口位置大小记忆（像桌面便签一样常驻角落）
- 颜色与字体全面自定义：框架/内容文字颜色、主题色、背景色、背景图片、字体族与字号独立设置
- 多屏健壮性：屏幕外窗口自动拉回、显示器热插拔自动归位、单实例保护（重复双击只把窗口带到前台）

## 🚀 快速开始

### Windows

- **exe 方式**：双击 `DesktopCalendar.exe`（节假日/农历数据已内置，无需安装 Python）
- **源码方式**：Python 3.8+ 标准库即可运行；`pip install chinesecalendar cnlunar` 可选（节假日与农历/节气显示）、`Pillow` 可选（背景图片）

```bash
python calendar_app.py    # 调试运行
```

- **重新打包**（需带 tkinter 的 Python + PyInstaller）：

```bash
python -m PyInstaller DesktopCalendar.spec --noconfirm --distpath "."
```

### Android

用 **Android Studio（Ladybug 2024.2+）** 打开 `android-native/` 等 Gradle Sync 后 Run ▶；或命令行：

```bash
cd android-native
gradlew.bat assembleDebug
# 产物：app\build\outputs\apk\debug\app-debug.apk
```

需要 JDK 17 + Android SDK（`local.properties` / `gradlew.bat` 里配置路径）。

详细的功能说明、常见问题、排错指南：

- Windows 版 → [`docs/windows-guide.md`](docs/windows-guide.md)
- Android 版 → [`android-native/README.md`](android-native/README.md)（含功能对照表、提醒权限说明、节假日数据更新方法）

## 📁 仓库结构

```
desktop_calendar/
├── calendar_app.py        # Windows 桌面版主程序（单文件，标准库运行）
├── DesktopCalendar.spec   # PyInstaller 打包配置
├── run.bat                # 源码方式启动
├── app.ico                # 应用图标
├── CHANGELOG.md           # 桌面版修订日志（程序内「设置 → 修订日志」直接读它）
├── docs/
│   └── windows-guide.md   # Windows 版详细指南
├── android-native/        # Android 原生版（Kotlin + Compose，Gradle 工程）
│   ├── app/               #   应用源码（lunar / remind / ui / data / wecom 等模块）
│   ├── CHANGELOG.md       #   安卓版修订日志
│   └── README.md          #   安卓版说明（功能对照 / 构建安装 / 权限）
└── android/               # 早期 Flet 原型（已废弃，仅留对照）
```

## 💾 数据

- 桌面版：`data\calendar.db`（SQLite，程序自动创建）+ `settings.json`，跟着程序文件夹走；备份 = 复制整个文件夹
- 安卓版：应用私有目录 `databases/calendar.db`（与桌面版同结构）；卸载会清空，重要任务定期在「全部清单 → 导出」备份
- 两端通过导出/导入 JSON / CSV 互通

## 📜 修订日志

- 桌面版：[`CHANGELOG.md`](CHANGELOG.md)（最新在最上），当前 **v1.8.5**
- 安卓版：[`android-native/CHANGELOG.md`](android-native/CHANGELOG.md)，当前 **v1.6.0**
- 改代码流程：① 改版本号 → ② 在对应 CHANGELOG 顶部补一条（现象/根因/改法）→ ③ 重新打包

## 🔒 隐私

任务数据只存在本机（SQLite + JSON/CSV 导出）；企业微信推送为可选项，凭据仅保存在本机 `settings.json`，不上传任何第三方服务器。
