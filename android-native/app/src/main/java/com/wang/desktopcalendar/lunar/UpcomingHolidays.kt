package com.wang.desktopcalendar.lunar

import java.time.LocalDate

/**
 * 未来约 13 个月的节日列表（日期计算页的倒计时用）。
 * 元旦/劳动节/国庆按公历直接推算；春节/端午/中秋用农历表逐日扫；
 * 清明查节气表。任一来源失败就跳过该项，绝不抛错——与桌面版逻辑一致。
 */
object UpcomingHolidays {

    /** key 对应 I18n 中的 h_* 文案 */
    data class Item(val key: String, val date: LocalDate)

    private val LUNAR_MATCH = mapOf(
        "h_spring" to (1 to 1),   // 正月初一
        "h_dragon" to (5 to 5),   // 五月初五
        "h_midaut" to (8 to 15),  // 八月十五
    )

    fun upcoming(today: LocalDate): List<Item> {
        val out = linkedMapOf<String, LocalDate>()
        // 1) 公历固定日期：今年已过则取明年
        val fixed = mapOf("h_newyear" to (1 to 1), "h_labour" to (5 to 1), "h_national" to (10 to 1))
        for ((key, md) in fixed) {
            var cand = LocalDate.of(today.year, md.first, md.second)
            if (cand < today) cand = LocalDate.of(today.year + 1, md.first, md.second)
            out[key] = cand
        }
        // 2) 农历节日 + 清明：向未来扫 400 天
        var d = today
        for (i in 0 until 400) {
            val lu = Lunar.solarToLunar(d)
            if (lu != null) {
                val (m, day, leap) = lu
                if (!leap) {
                    for ((key, md) in LUNAR_MATCH) {
                        if (key !in out && m == md.first && day == md.second) out[key] = d
                    }
                }
            }
            if ("h_qingming" !in out) {
                SolarTerms.termOfDay(d)?.let { if (it == "清明") out["h_qingming"] = d }
            }
            if (out.size >= 7) break
            d = d.plusDays(1)
        }
        return out.entries.sortedBy { it.value }.map { Item(it.key, it.value) }
    }
}
