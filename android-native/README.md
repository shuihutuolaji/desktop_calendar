# 桌面日历清单 · 安卓版（android-native）

基于 Windows 桌面版 `calendar_app.py` 用 **Kotlin + Jetpack Compose** 重写的原生安卓应用，
功能与桌面版对齐，数据格式互通。

> 本目录（`android-native`）是原生版；旁边旧的 `android` 目录是之前 Flet 原型，
> 未删除可对照，但与本工程无关。

## 功能对照（桌面版 → 安卓版）

| 桌面版功能 | 安卓版 | 说明 |
|---|---|---|
| 月历（周数/农历/24节气/法定节假日/调休） | ✅ | 农历表与桌面版 cnlunar 同源校验一致；节气内嵌 2024–2040 精确表 |
| 月历任务角标 + 前 3 条预览 | ✅ | 手机屏幕窄，改为角标 + 前 2 条预览 |
| 当日任务面板（完成/删除/编辑/重要/置顶） | ✅ | 点任务标题编辑；类型标签点击弹下拉切换；✕ 删除 |
| 周期任务（日/周/月）+ 自动顺延 | ✅ | 顺延逻辑逐行移植，启动与回前台时执行 |
| 任务提醒（补弹、周期重复） | ✅ | 桌面是常驻轮询，安卓改为系统闹钟 + 通知；开机/改时间自动重排；错过 12 小时内补提醒 |
| 企业微信推送（群机器人 + 自建应用） | ✅ | 逻辑与桌面版一致；提醒时和手动「推送今日待办」都支持 |
| 全部清单（状态着色、清理已完成） | ✅ | 点行编辑，勾选框切完成 |
| 导入 / 导出 JSON、CSV | ✅ | 格式与桌面版完全一致，可互导；桌面版 calendar.db 甚至可直接拷来用 |
| 日期计算（节日倒计时/两日期相差/今天±N） | ✅ | |
| 中英双语（即时切换） | ✅ | 设置里切换，立即生效 |
| 显示项 / 周起始日 / 三处颜色设置 | ✅ | 与桌面版同名预设色 |
| 窗口透明度 / 贴桌面底层 / 置顶 / 开机自启 / 背景图片 / 自定义字体 | ❌ | 桌面窗口特性，手机上不适用 |

## 构建与安装

**本机已打好安装包：`android-native\桌面日历清单.apk`**（debug 签名，约 16MB，
直接传到手机点击安装即可；安装时如提示"未知来源"允许一次即可）。

自行构建 / 改代码后重新打包：

1. 用 **Android Studio（Ladybug 2024.2 或更新）** 打开本目录（`android-native`），
   等待 Gradle Sync 完成后点 **Run ▶**；
2. 或命令行（工具链已装在 D 盘，`gradlew` 脚本已写好默认路径，直接运行即可）：
   ```
   gradlew.bat assembleDebug
   ```
   - JDK 17：`D:\02 software\jdk-17`
   - Android SDK：`D:\02 software\android-sdk`（工程的 local.properties 已指向这里）
   - Gradle 缓存：`D:\02 software\gradle-home`（1.4GB，依赖齐全，**可离线构建**）
   产物在 `app\build\outputs\apk\debug\app-debug.apk`，
   复制成根目录的 `desktop_calendar.apk` 即交付包。
   在其他机器上构建时，装好 JDK 17 与 Android SDK 后，把上述两个默认路径
   改成实际位置（gradlew.bat / gradlew 开头几行），或用环境变量覆盖。

> **本机不需要再下载任何东西**（2026-09-29 实测：离线 `gradlew.bat assembleDebug --offline`
> 直接 BUILD SUCCESSFUL）。若某些终端里报 `JAVA_HOME is not set`（脚本里的自动探测偶发失效），
> 显式指定即可：
> ```
> set JAVA_HOME=D:\02 software\jdk-17
> set GRADLE_USER_HOME=D:\02 software\gradle-home
> gradlew.bat assembleDebug
> ```

## 修订日志

`CHANGELOG.md`（本目录）。当前 **v1.1（versionCode 2）**：周/月任务自动生成后续各期
（原来是"顺延一行"）、编辑弹窗保存按钮 + 整系列同步、新增修订日志。

> 若你的 Android Studio 版本较老，打开时提示 AGP 版本不支持，可把
> `build.gradle.kts` 里的 `com.android.application` 版本降到 8.5.x，
> 并确认 `gradle/wrapper/gradle-wrapper.properties` 的 Gradle ≥ 8.7。

## 提醒相关权限

- **通知权限**：Android 13+ 首次启动会弹窗询问，拒绝则收不到提醒；
- **闹钟和提醒**（Android 12+）：默认已声明。若手机厂商限制了精确闹钟导致提醒延迟，
  到 系统设置 → 应用 → 桌面日历清单 → 特殊权限 → 闹钟和提醒 里允许。

## 数据位置

- 数据库：应用私有目录 `databases/calendar.db`（与桌面版同结构同列名）；
- 设置：`SharedPreferences`（键名与桌面版 settings.json 一致）；
- 卸载应用会清空数据，重要任务请定期在「全部清单 → 导出」备份。

## 节假日数据更新

2025、2026 年法定节假日与调休补班已按国务院办公厅 2025-11-04 公布的安排内置。
以后每年公布新安排后，编辑
`app/src/main/java/com/wang/desktopcalendar/lunar/Holidays.kt`
里的 `HOLIDAYS`（放假日）与 `MAKEUP`（补班日）两个集合即可。
