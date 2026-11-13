package com.wang.desktopcalendar.lunar

import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.concurrent.ConcurrentHashMap

/**
 * 农历换算（1900–2100），采用经典压缩表算法。
 * 表数据与转换算法已用 cnlunar 库逐年比对（含 1984/2004/2009/2020/2023/2025 等闰月年）
 * 全部一致。中文月名「正二三四五六七八九十冬腊」，日名「初一…三十」。
 */
object Lunar {

    private val LUNAR_INFO = intArrayOf(
        0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d9, // 1900-1909
        0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977, // 1910-1919
        0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970, // 1920-1929
        0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950, // 1930-1939
        0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557, // 1940-1949
        0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0, // 1950-1959
        0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0, // 1960-1969
        0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6, // 1970-1979
        0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570, // 1980-1989
        0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x05ac0, 0x0ab60, 0x096d5, 0x092e0, // 1990-1999
        0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5, // 2000-2009
        0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930, // 2010-2019
        0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530, // 2020-2029
        0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45, // 2030-2039
        0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0, // 2040-2049
        0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0, // 2050-2059
        0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4, // 2060-2069
        0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0, // 2070-2079
        0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160, // 2080-2089
        0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252, // 2090-2099
        0x0d950, // 2100
    )

    private val BASE = LocalDate.of(1900, 1, 31)

    private fun leapMonth(y: Int): Int = LUNAR_INFO[y - 1900] and 0xf
    private fun leapDays(y: Int): Int =
        if (leapMonth(y) == 0) 0 else if (LUNAR_INFO[y - 1900] and 0x10000 != 0) 30 else 29
    private fun monthDays(y: Int, m: Int): Int =
        if (LUNAR_INFO[y - 1900] and (0x10000 shr m) != 0) 30 else 29

    private fun yearDays(y: Int): Int {
        var sum = 348
        var i = 0x8000
        while (i > 0x8) {
            if (LUNAR_INFO[y - 1900] and i != 0) sum++
            i = i shr 1
        }
        return sum + leapDays(y)
    }

    /** 公历 -> 农历 (月 1-12, 日 1-30, 是否闰月)；超出 1900-2100 范围返回 null */
    fun solarToLunar(date: LocalDate): Triple<Int, Int, Boolean>? {
        if (date.year < 1900 || date.year > 2100) return null
        cache[date.toEpochDay()]?.let { return it }
        var offset = ChronoUnit.DAYS.between(BASE, date)
        var i = 1900
        var temp = 0
        while (i < 2101 && offset > 0) {
            temp = yearDays(i); offset -= temp; i++
        }
        if (offset < 0) { offset += temp; i-- }
        val year = i
        val leap = leapMonth(year)
        var isLeap = false
        var j = 1
        while (j < 13 && offset > 0) {
            if (leap > 0 && j == leap + 1 && !isLeap) {
                j--; isLeap = true; temp = leapDays(year)
            } else {
                temp = monthDays(year, j)
            }
            if (isLeap && j == leap + 1) isLeap = false
            offset -= temp
            j++
        }
        if (offset == 0L && leap > 0 && j == leap + 1) {
            if (isLeap) isLeap = false else { isLeap = true; j-- }
        }
        if (offset < 0) { offset += temp; j-- }
        val r = Triple(j, offset.toInt() + 1, isLeap)
        cache[date.toEpochDay()] = r
        return r
    }

    private val cache = ConcurrentHashMap<Long, Triple<Int, Int, Boolean>>()

    private val MON_CN = arrayOf("正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊")
    private val DAYS_CN = "一二三四五六七八九十"

    fun monthCn(month: Int, isLeap: Boolean): String =
        (if (isLeap) "闰" else "") + MON_CN[month - 1] + "月"

    fun dayCn(day: Int): String = when (day) {
        10 -> "初十"; 20 -> "二十"; 30 -> "三十"
        else -> arrayOf("初", "十", "廿", "三")[(day - 1) / 10] + DAYS_CN[(day - 1) % 10]
    }

    /**
     * 月历格子上的农历显示：初一显示月名（如「八月」），其余显示日名。
     * 英文界面一律返回空串——农历数字对英文用户没有意义，用户明确要求
     * 英文模式下不显示农历；在数据源头关掉，与桌面版 v1.5.1 一致。
     * 无农历数据返回空串。
     */
    fun displayText(date: LocalDate, lang: String): String {
        if (lang == "en") return ""
        val lu = solarToLunar(date) ?: return ""
        return if (lu.second == 1) monthCn(lu.first, lu.third) else dayCn(lu.second)
    }
}
