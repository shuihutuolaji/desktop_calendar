package com.wang.desktopcalendar.ui

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.runtime.staticCompositionLocalOf
import com.wang.desktopcalendar.data.SettingsStore
import com.wang.desktopcalendar.data.Task
import com.wang.desktopcalendar.data.TaskRepo
import java.time.LocalDate

enum class Screen { CALENDAR, LIST, CALC, SETTINGS }

val LocalApp = staticCompositionLocalOf<AppState> { error("AppState not provided") }
val LocalLang = staticCompositionLocalOf<String> { "zh" }

/** 全局取词快捷函数（仅限组合内调用；回调里请用 I18n.t(lang, ...)） */
@Composable
fun T(key: String, vararg args: Pair<String, Any?>): String =
    I18n.t(LocalLang.current, key, *args)

/** 把 "#rrggbb" 转成 Compose Color；非法串回退默认色 */
fun parseHex(hex: String, fallback: Color): Color = try {
    Color(android.graphics.Color.parseColor(hex))
} catch (_: Exception) {
    fallback
}

/** 把颜色向白色混合（whiteRatio 为白色占比），生成主题色浅色底——与桌面版 mix_hex 一致 */
fun mixHex(hexColor: String, whiteRatio: Float = 0.85f): Color {
    val c = parseHex(hexColor, Color(0xFF2563EB))
    val r = c.red; val g = c.green; val b = c.blue
    fun mix(v: Float) = v + (1f - v) * whiteRatio
    return Color(mix(r), mix(g), mix(b))
}

/** 颜色预设（与桌面版一致） */
object Presets {
    val CAL_FG = listOf(
        "黑" to "#1f2937", "红" to "#dc2626", "蓝" to "#2563eb", "棕" to "#92400e", "紫" to "#7c3aed")
    val ACCENT = listOf(
        "蓝" to "#2563eb", "绿" to "#16a34a", "紫" to "#7c3aed",
        "橙" to "#ea580c", "红" to "#dc2626", "青" to "#0891b2")
    val BG = listOf(
        "bg_default" to "#f0f0f0", "bg_blue" to "#e3edf8", "bg_green" to "#e6f4ea",
        "bg_pink" to "#fbeef1", "bg_beige" to "#f7f3e3", "bg_gray" to "#3b4048")
}

/** 任务类型标签底色（与桌面版 TYPE_COLORS 一致） */
object TypeColors {
    val DAY = Color(0xFFDBEAFE)
    val WEEK = Color(0xFFDCFCE7)
    val MONTH = Color(0xFFFDE68A)
    val WORKDAY = Color(0xFFEDE9FE)

    fun of(repeat: String): Color = when (repeat) {
        "week" -> WEEK
        "month" -> MONTH
        "workday" -> WORKDAY
        else -> DAY
    }
}

object Palette {
    val Cell = Color.White
    val CellOther = Color(0xFFF3F4F6)
    val CellToday = Color(0xFFFEF9C3)
    val CellHolidayBg = Color(0xFFFEF2F2)
    val Danger = Color(0xFFDC2626)
    val TextSub = Color(0xFF6B7280)
    val TextOther = Color(0xFF9CA3AF)
    val Done = Color(0xFF9CA3AF)
    val GridLine = Color(0xFFE5E7EB)
    val TermGreen = Color(0xFF059669)
    val WorkMarkBg = Color(0xFFDBEAFE)
    val RestMarkBg = Color(0xFFFEE2E2)
}

/**
 * 全局应用状态：设置 + 数据仓库 + 选中日期/视图 + 刷新计数。
 * 数据变化后调 refresh()（tick 自增触发各页重组重查）。
 */
class AppState(context: Context) {

    val settings = SettingsStore(context)
    val repo: TaskRepo = TaskRepo.get(context)

    var lang by mutableStateOf(settings.language)
    var weekStartSun by mutableStateOf(settings.weekStart == "sun")
    var showWeekno by mutableStateOf(settings.showWeekno)
    var showLunar by mutableStateOf(settings.showLunar)
    var showTerms by mutableStateOf(settings.showTerms)
    var showRest by mutableStateOf(settings.showRest)
    var showHoliday by mutableStateOf(settings.showHoliday)
    var calFg by mutableStateOf(settings.calFg)
    var accent by mutableStateOf(settings.accent)
    var bgColor by mutableStateOf(settings.bgColor)

    var wecomWebhook by mutableStateOf(settings.wecomWebhook)
    var wecomPush by mutableStateOf(settings.wecomPush)
    var wecomCorpId by mutableStateOf(settings.wecomCorpId)
    var wecomAgentId by mutableStateOf(settings.wecomAgentId)
    var wecomCorpSecret by mutableStateOf(settings.wecomCorpSecret)

    var remindEarly by mutableIntStateOf(settings.remindEarly)
    var autoBackup by mutableStateOf(settings.autoBackup)
    var icsUrl by mutableStateOf(settings.icsUrl)

    var screen by mutableStateOf(Screen.CALENDAR)

    var today: LocalDate = LocalDate.now()
    var viewYear by mutableIntStateOf(today.year)
    var viewMonth by mutableIntStateOf(today.monthValue)
    var selDate by mutableStateOf(today)

    var tick by mutableIntStateOf(0)

    /** 当前编辑的任务（非空时弹出编辑对话框） */
    var editingTask by mutableStateOf<Task?>(null)
    var showPushToday by mutableStateOf(false)

    fun refresh() { tick++ }

    /** 设置项变化后写回存储 */
    fun persist() {
        settings.language = lang
        settings.weekStart = if (weekStartSun) "sun" else "mon"
        settings.showWeekno = showWeekno
        settings.showLunar = showLunar
        settings.showTerms = showTerms
        settings.showRest = showRest
        settings.showHoliday = showHoliday
        settings.calFg = calFg
        settings.accent = accent
        settings.bgColor = bgColor
        settings.wecomWebhook = wecomWebhook
        settings.wecomPush = wecomPush
        settings.wecomCorpId = wecomCorpId
        settings.wecomAgentId = wecomAgentId
        settings.wecomCorpSecret = wecomCorpSecret
        settings.remindEarly = remindEarly
        settings.autoBackup = autoBackup
        settings.icsUrl = icsUrl
    }

    fun goToday() {
        today = LocalDate.now()
        viewYear = today.year
        viewMonth = today.monthValue
        selDate = today
    }

    /**
     * 回到前台时检查跨天（对应桌面版 _tick）：
     * 原本停在当天就跟进到新的一天；正在翻看别的日期则不打断；月历同理跟月。
     */
    fun onForegroundUi() {
        val now = LocalDate.now()
        if (now != today) {
            val wasOnToday = selDate == today
            val wasOnTodayMonth = viewYear == today.year && viewMonth == today.monthValue
            today = now
            if (wasOnToday) selDate = now
            if (wasOnTodayMonth) { viewYear = now.year; viewMonth = now.monthValue }
        }
        refresh()
    }

    fun shiftMonth(delta: Int) {
        var y = viewYear
        var m = viewMonth + delta
        if (m == 0) { y--; m = 12 } else if (m == 13) { y++; m = 1 }
        viewYear = y
        viewMonth = m
    }
}

/** 组合根里提供 AppState 与语言，简化子组件取用 */
@Composable
fun ProvideAppState(state: AppState, content: @Composable () -> Unit) {
    CompositionLocalProvider(
        LocalApp provides state,
        LocalLang provides state.lang,
    ) { content() }
}
