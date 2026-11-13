package com.wang.desktopcalendar.ui

import android.app.DatePickerDialog
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wang.desktopcalendar.lunar.UpcomingHolidays
import java.time.LocalDate

/** 日期计算页：节日倒计时 / 两日期相差 / 今天±N 天（对应桌面版 tab_calc） */
@Composable
fun CalcTab(state: AppState) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val lang = LocalLang.current
    val today = state.today
    val holidays = remember(state.tick) { UpcomingHolidays.upcoming(today) }

    // ① 节日倒计时
    var holidayIdx by remember { mutableIntStateOf(0) }
    var res1 by remember { mutableStateOf("") }
    // ② 两日期相差
    var d1 by remember { mutableStateOf(today) }
    var d2 by remember { mutableStateOf(today.plusDays(30)) }
    var res2 by remember { mutableStateOf("") }
    // ③ 今天 ± N 天
    var daysText by remember { mutableStateOf("30") }
    var res3 by remember { mutableStateOf("") }

    val context = LocalContext.current

    fun pickDate(current: LocalDate, onPick: (LocalDate) -> Unit) {
        DatePickerDialog(
            context, { _, y, m, dd -> onPick(LocalDate.of(y, m + 1, dd)) },
            current.year, current.monthValue - 1, current.dayOfMonth,
        ).show()
    }

    fun calcCountdown() {
        if (holidays.isEmpty()) return
        val item = holidays[holidayIdx.coerceIn(0, holidays.lastIndex)]
        val disp = "${I18n.t(lang, item.key)} ${item.date}"
        res1 = if (item.date == today) {
            I18n.t(lang, "calc_target_today", "d" to disp)
        } else {
            val n = java.time.temporal.ChronoUnit.DAYS.between(today, item.date)
            I18n.t(lang, "calc_days_until", "d" to disp, "n" to n, "w" to n / 7, "r" to n % 7)
        }
    }

    fun calcBetween() {
        val n = kotlin.math.abs(java.time.temporal.ChronoUnit.DAYS.between(d1, d2))
        res2 = if (n == 0L) I18n.t(lang, "calc_same")
        else I18n.t(lang, "calc_diff", "n" to n, "w" to n / 7, "r" to n % 7)
    }

    fun calcOffset() {
        val n = daysText.trim().toIntOrNull()
        if (n == null) {
            res3 = I18n.t(lang, "calc_bad_days")
            return
        }
        val target = today.plusDays(n.toLong())
        val w = I18n.weekdayNames(lang)[target.dayOfWeek.value - 1]
        res3 = if (n >= 0) {
            I18n.t(lang, "calc_offset_result", "n" to n, "d" to target, "w" to w)
        } else {
            I18n.t(lang, "calc_offset_before", "a" to -n, "d" to target, "w" to w)
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp)
    ) {
        Spacer(Modifier.padding(top = 8.dp))

        // —— ① 节日倒计时 ——
        SectionLabel(T("calc_countdown"))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(T("calc_pick"), fontSize = 14.sp)
            Spacer(Modifier.width(8.dp))
            Box {
                var open by remember { mutableStateOf(false) }
                TextButton(onClick = { open = true }) {
                    Text(
                        if (holidays.isEmpty()) "—"
                        else I18n.t(lang, holidays[holidayIdx.coerceIn(0, holidays.lastIndex)].key),
                        fontSize = 14.sp,
                    )
                }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    holidays.forEachIndexed { i, item ->
                        DropdownMenuItem(
                            text = { Text("${I18n.t(lang, item.key)}  ${item.date}") },
                            onClick = { holidayIdx = i; open = false },
                        )
                    }
                }
            }
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = { calcCountdown() },
                colors = ButtonDefaults.buttonColors(containerColor = accent),
            ) { Text(T("calc_btn")) }
        }
        ResultText(res1, accent)

        HLine(color = Color(0xFFE5E7EB))

        // —— ② 两日期相差 ——
        SectionLabel(T("calc_between"))
        Row(verticalAlignment = Alignment.CenterVertically) {
            DateField(T("calc_date1"), d1) { d1 = it; calcBetween() }
            Spacer(Modifier.width(10.dp))
            Text("→", fontSize = 16.sp, color = Palette.TextSub)
            Spacer(Modifier.width(10.dp))
            DateField(T("calc_date2"), d2) { d2 = it; calcBetween() }
            Spacer(Modifier.width(10.dp))
            Button(
                onClick = { calcBetween() },
                colors = ButtonDefaults.buttonColors(containerColor = accent),
            ) { Text(T("calc_btn")) }
        }
        ResultText(res2, accent)

        HLine(color = Color(0xFFE5E7EB))

        // —— ③ 今天 ± N 天 ——
        SectionLabel(T("calc_offset"))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = daysText,
                onValueChange = { daysText = it },
                modifier = Modifier.width(120.dp),
                singleLine = true,
                label = { Text(T("calc_days"), fontSize = 11.sp) },
            )
            Spacer(Modifier.width(10.dp))
            Button(
                onClick = { calcOffset() },
                colors = ButtonDefaults.buttonColors(containerColor = accent),
            ) { Text(T("calc_btn")) }
        }
        ResultText(res3, accent)

        HLine(color = Color(0xFFE5E7EB))

        // —— ④ 倒数日 / 纪念日（农历条目每年自动换算公历，与桌面版 v1.6.0 一致）——
        SectionLabel(T("event_head"))
        var showEventDialog by remember { mutableStateOf(false) }
        Button(
            onClick = { showEventDialog = true },
            colors = ButtonDefaults.buttonColors(containerColor = accent),
        ) { Text(T("event_add")) }

        val events = remember(state.tick) { state.repo.eventsAll() }
        if (events.isEmpty()) {
            Text(
                T("event_none"), fontSize = 12.sp, color = Palette.TextOther,
                modifier = Modifier.padding(vertical = 6.dp),
            )
        }
        for (e in events) {
            var icon = "⏳"
            var desc = e.eventDate.toString()
            var stateTxt: String
            if (e.kind == "annual") {
                icon = "🎂"
                var nxt: LocalDate? = null
                if (e.lunar) {
                    desc = I18n.t(lang, "event_desc_lunar",
                        "m" to e.eventDate.monthValue, "d" to e.eventDate.dayOfMonth)
                    nxt = state.repo.lunarAnnualDate(e.eventDate, today.year)
                    if (nxt != null && nxt.isBefore(today)) {
                        nxt = state.repo.lunarAnnualDate(e.eventDate, today.year + 1) ?: nxt
                    }
                } else {
                    desc = I18n.t(lang, "event_desc_annual",
                        "m" to e.eventDate.monthValue, "d" to e.eventDate.dayOfMonth)
                    try { nxt = e.eventDate.withYear(today.year) } catch (_: Exception) { }
                    if (nxt != null && nxt.isBefore(today)) {
                        try { nxt = e.eventDate.withYear(today.year + 1) } catch (_: Exception) { }
                    }
                }
                stateTxt = if (nxt == null) e.eventDate.toString() else run {
                    val n = java.time.temporal.ChronoUnit.DAYS.between(today, nxt).toInt()
                    val left = I18n.t(lang, when {
                        n == 0 -> "event_today"; n > 0 -> "event_left"; else -> "event_past"
                    }, "n" to kotlin.math.abs(n))
                    "$nxt · $left"
                }
            } else {
                val n = java.time.temporal.ChronoUnit.DAYS.between(today, e.eventDate).toInt()
                stateTxt = I18n.t(lang, when {
                    n == 0 -> "event_today"; n > 0 -> "event_left"; else -> "event_past"
                }, "n" to kotlin.math.abs(n))
            }
            Row(
                Modifier.fillMaxWidth().padding(vertical = 3.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("$icon ${e.name}", fontSize = 14.sp)
                Spacer(Modifier.width(8.dp))
                Text("$desc · $stateTxt", fontSize = 11.sp, color = Palette.TextSub)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = {
                    state.repo.deleteEvent(e.id); state.refresh()
                }) { Text("✕", fontSize = 12.sp, color = Palette.TextSub) }
            }
        }
        if (showEventDialog) {
            EventDialog(state = state, onClose = { showEventDialog = false; state.refresh() })
        }

        Spacer(Modifier.padding(bottom = 24.dp))
        Text(
            T("signature"),
            Modifier.align(Alignment.CenterHorizontally).padding(vertical = 12.dp),
            fontSize = 12.sp, color = accent,
        )
    }
}

@Composable
private fun DateField(label: String, value: LocalDate, onPick: (LocalDate) -> Unit) {
    val context = LocalContext.current
    Column(Modifier.clickable {
        DatePickerDialog(
            context, { _, y, m, dd -> onPick(LocalDate.of(y, m + 1, dd)) },
            value.year, value.monthValue - 1, value.dayOfMonth,
        ).show()
    }) {
        Text(label, fontSize = 11.sp, color = Palette.TextSub)
        Text("$value", fontSize = 15.sp, color = MaterialTheme.colorScheme.onBackground)
    }
}

@Composable
private fun ResultText(text: String, accent: Color) {
    Text(
        text,
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        fontSize = 14.sp, fontWeight = FontWeight.Bold, color = accent,
    )
}
