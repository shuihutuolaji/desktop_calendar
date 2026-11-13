package com.wang.desktopcalendar.lunar

import java.time.LocalDate

/**
 * 法定节假日与调休补班。
 * 2025 / 2026 数据来自《国务院办公厅关于2026年部分节假日安排的通知》
 * （国办发明电〔2025〕**，2025-11-04 发布），与桌面版使用的 chinese_calendar
 * 库数据一致。2027 年及以后公布新安排后，往 HOLIDAYS / MAKEUP 里补即可；
 * 未覆盖的年份自动退化为：周末=休、按农历/公历推算节日名，不显示调休。
 */
object Holidays {

    private fun d(s: String): LocalDate = LocalDate.parse(s)

    private val HOLIDAYS: Map<LocalDate, String> = buildMap {
        // ---- 2025 ----
        put(d("2025-01-01"), "元旦")
        for (i in 0..7) put(d("2025-01-28").plusDays(i.toLong()), "春节")
        for (i in 0..2) put(d("2025-04-04").plusDays(i.toLong()), "清明")
        for (i in 0..4) put(d("2025-05-01").plusDays(i.toLong()), "劳动节")
        for (i in 0..2) put(d("2025-05-31").plusDays(i.toLong()), "端午")
        put(d("2025-10-01"), "国庆"); put(d("2025-10-02"), "国庆"); put(d("2025-10-03"), "国庆")
        put(d("2025-10-04"), "国庆"); put(d("2025-10-05"), "国庆")
        put(d("2025-10-06"), "中秋")
        put(d("2025-10-07"), "国庆"); put(d("2025-10-08"), "国庆")
        // ---- 2026 ----
        for (i in 0..2) put(d("2026-01-01").plusDays(i.toLong()), "元旦")
        for (i in 0..8) put(d("2026-02-15").plusDays(i.toLong()), "春节")
        for (i in 0..2) put(d("2026-04-04").plusDays(i.toLong()), "清明")
        for (i in 0..4) put(d("2026-05-01").plusDays(i.toLong()), "劳动节")
        for (i in 0..2) put(d("2026-06-19").plusDays(i.toLong()), "端午")
        for (i in 0..2) put(d("2026-09-25").plusDays(i.toLong()), "中秋")
        for (i in 0..6) put(d("2026-10-01").plusDays(i.toLong()), "国庆")
    }

    /** 调休补班日（周末但需要上班） */
    private val MAKEUP: Set<LocalDate> = setOf(
        d("2025-01-26"), d("2025-02-08"), d("2025-04-27"), d("2025-09-28"), d("2025-10-11"),
        d("2026-01-04"), d("2026-02-14"), d("2026-02-28"), d("2026-05-09"),
        d("2026-09-20"), d("2026-10-10"),
    )

    private val COVERED_YEARS = HOLIDAYS.keys.map { it.year }.toSet()

    /** 节假日英文名（英文界面月历格子用，短小不挤破格子） */
    private val EN_NAMES = mapOf(
        "元旦" to "New Year", "春节" to "Spring F.", "清明" to "Qingming",
        "劳动节" to "Labour", "端午" to "Dragon Boat", "中秋" to "Mid-Autumn",
        "国庆" to "National",
    )

    data class Marks(val holiday: String?, val isRest: Boolean, val makeup: Boolean)

    /**
     * 返回 (法定节日名, 是否休息日, 是否调休补班)。
     * 已覆盖年份：休息日 = 法定节假日或未补班的周末；
     * 未覆盖年份：退化为周末休息 + 农历/公历推算的节日名（仅正日子）。
     */
    fun marks(date: LocalDate): Marks {
        val zhName = HOLIDAYS[date]
        if (date.year in COVERED_YEARS) {
            val weekend = date.dayOfWeek.value >= 6
            val makeup = date in MAKEUP
            val isRest = zhName != null || (weekend && !makeup)
            return Marks(zhName, isRest, makeup)
        }
        // 未覆盖年份的兜底
        val fallback = fallbackHolidayName(date)
        return Marks(fallback, date.dayOfWeek.value >= 6, false)
    }

    /** 节日显示名（按界面语言） */
    fun displayName(zhName: String, lang: String): String =
        if (lang == "en") EN_NAMES[zhName] ?: zhName else zhName

    /** 未覆盖年份的节日名推算：公历固定 + 农历节日 + 清明节气 */
    private fun fallbackHolidayName(date: LocalDate): String? {
        SolarTerms.termOfDay(date)?.let { if (it == "清明") return "清明" }
        when (date.monthValue to date.dayOfMonth) {
            1 to 1 -> return "元旦"
            5 to 1 -> return "劳动节"
            10 to 1 -> return "国庆"
        }
        val lu = Lunar.solarToLunar(date) ?: return null
        val (m, day, leap) = lu
        if (leap) return null
        return when {
            m == 1 && day == 1 -> "春节"
            m == 5 && day == 5 -> "端午"
            m == 8 && day == 15 -> "中秋"
            else -> null
        }
    }
}
