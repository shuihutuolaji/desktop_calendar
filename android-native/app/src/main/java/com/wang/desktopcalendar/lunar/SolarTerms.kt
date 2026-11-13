package com.wang.desktopcalendar.lunar

import java.time.LocalDate

/**
 * 24 节气。2024–2040 使用精确日期表（由 cnlunar 生成并逐日校验），
 * 范围外用寿星公式估算兜底（21 世纪 C 值；1/2 月节气按 (y-1)/4 修正闰年位移）。
 */
object SolarTerms {

    val NAMES = arrayOf(
        "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
        "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
        "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
    )

    // 每年 24 个值 = 各节气落在当月的「日」；节气 idx 对应公历月 = idx/2 + 1
    private val TABLE: Map<Int, IntArray> = mapOf(
        2024 to intArrayOf(6, 20, 4, 19, 5, 20, 4, 19, 5, 20, 5, 21, 6, 22, 7, 22, 7, 22, 8, 23, 7, 22, 6, 21),
        2025 to intArrayOf(5, 20, 3, 18, 5, 20, 4, 20, 5, 21, 5, 21, 7, 22, 7, 23, 7, 23, 8, 23, 7, 22, 7, 21),
        2026 to intArrayOf(5, 20, 4, 18, 5, 20, 5, 20, 5, 21, 5, 21, 7, 23, 7, 23, 7, 23, 8, 23, 7, 22, 7, 22),
        2027 to intArrayOf(5, 20, 4, 19, 6, 21, 5, 20, 6, 21, 6, 21, 7, 23, 8, 23, 8, 23, 8, 23, 7, 22, 7, 22),
        2028 to intArrayOf(6, 20, 4, 19, 5, 20, 4, 19, 5, 20, 5, 21, 6, 22, 7, 22, 7, 22, 8, 23, 7, 22, 6, 21),
        2029 to intArrayOf(5, 20, 3, 18, 5, 20, 4, 20, 5, 21, 5, 21, 7, 22, 7, 23, 7, 23, 8, 23, 7, 22, 7, 21),
        2030 to intArrayOf(5, 20, 4, 18, 5, 20, 5, 20, 5, 21, 5, 21, 7, 23, 7, 23, 7, 23, 8, 23, 7, 22, 7, 22),
        2031 to intArrayOf(5, 20, 4, 19, 6, 21, 5, 20, 6, 21, 6, 21, 7, 23, 8, 23, 8, 23, 8, 23, 7, 22, 7, 22),
        2032 to intArrayOf(6, 20, 4, 19, 5, 20, 4, 19, 5, 20, 5, 21, 6, 22, 7, 22, 7, 22, 8, 23, 7, 22, 6, 21),
        2033 to intArrayOf(5, 20, 3, 18, 5, 20, 4, 20, 5, 21, 5, 21, 7, 22, 7, 23, 7, 23, 8, 23, 7, 22, 7, 21),
        2034 to intArrayOf(5, 20, 4, 18, 5, 20, 5, 20, 5, 21, 5, 21, 7, 23, 7, 23, 7, 23, 8, 23, 7, 22, 7, 22),
        2035 to intArrayOf(5, 20, 4, 19, 6, 21, 5, 20, 5, 21, 6, 21, 7, 23, 7, 23, 8, 23, 8, 23, 7, 22, 7, 22),
        2036 to intArrayOf(6, 20, 4, 19, 5, 20, 4, 19, 5, 20, 5, 21, 6, 22, 7, 22, 7, 22, 8, 23, 7, 22, 6, 21),
        2037 to intArrayOf(5, 20, 3, 18, 5, 20, 4, 20, 5, 21, 5, 21, 7, 22, 7, 23, 7, 23, 8, 23, 7, 22, 7, 21),
        2038 to intArrayOf(5, 20, 4, 18, 5, 20, 5, 20, 5, 21, 5, 21, 7, 23, 7, 23, 7, 23, 8, 23, 7, 22, 7, 22),
        2039 to intArrayOf(5, 20, 4, 19, 6, 21, 5, 20, 5, 21, 6, 21, 7, 23, 7, 23, 8, 23, 8, 23, 7, 22, 7, 22),
        2040 to intArrayOf(6, 20, 4, 19, 5, 20, 4, 19, 5, 20, 5, 21, 6, 22, 7, 22, 7, 22, 8, 23, 7, 22, 6, 21),
    )

    private val C21 = doubleArrayOf(
        5.4055, 20.12, 3.87, 18.73, 5.63, 20.646, 4.81, 20.1,
        5.52, 21.04, 5.678, 21.37, 7.108, 22.83, 7.5, 23.13,
        7.646, 23.042, 8.318, 23.438, 7.438, 22.36, 7.18, 21.94,
    )

    /** 当天若是节气日，返回节气名，否则 null */
    fun termOfDay(date: LocalDate): String? {
        val arr = TABLE[date.year]
        if (arr != null) {
            val idx = (date.monthValue - 1) * 2
            return when (date.dayOfMonth) {
                arr[idx] -> NAMES[idx]
                arr[idx + 1] -> NAMES[idx + 1]
                else -> null
            }
        }
        return fallbackTermOfDay(date)
    }

    /** 某年某节气（如清明）的公历日期；表内精确，表外估算 */
    fun termDate(year: Int, name: String): LocalDate? {
        val idx = NAMES.indexOf(name)
        if (idx < 0) return null
        TABLE[year]?.let { return LocalDate.of(year, idx / 2 + 1, it[idx]) }
        val y = year % 100
        val c = C21[idx]
        // 1、2 月的节气发生在当年闰日（2/29）之前，闰年位移比平年少一天
        val l = if (idx < 4) (y - 1) / 4 else y / 4
        val day = (y * 0.2422 + c).toInt() - l
        return try { LocalDate.of(year, idx / 2 + 1, day) } catch (_: Exception) { null }
    }

    private fun fallbackTermOfDay(date: LocalDate): String? {
        val idx = (date.monthValue - 1) * 2
        val y = date.year % 100
        val c1 = C21[idx]; val c2 = C21[idx + 1]
        val l1 = if (idx < 4) (y - 1) / 4 else y / 4
        val l2 = if (idx + 1 < 4) (y - 1) / 4 else y / 4
        val d1 = (y * 0.2422 + c1).toInt() - l1
        val d2 = (y * 0.2422 + c2).toInt() - l2
        return when (date.dayOfMonth) {
            d1 -> NAMES[idx]
            d2 -> NAMES[idx + 1]
            else -> null
        }
    }
}
