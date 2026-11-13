package com.wang.desktopcalendar.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wang.desktopcalendar.data.Task
import com.wang.desktopcalendar.data.Types
import com.wang.desktopcalendar.lunar.Holidays
import com.wang.desktopcalendar.lunar.Lunar
import com.wang.desktopcalendar.lunar.SolarTerms
import java.time.LocalDate
import java.time.LocalTime
import java.time.YearMonth
import java.time.temporal.IsoFields
import java.time.temporal.ChronoUnit

/** 日历页：月份导航 + 月历网格 + 当日任务面板（对应桌面版 tab_month） */
@Composable
fun CalendarTab(state: AppState) {
    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        // ---- 月份导航 ----
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = { state.shiftMonth(-1) }) {
                Icon(Icons.Filled.ChevronLeft, contentDescription = "prev")
            }
            Text(
                T("month_label", "y" to state.viewYear, "m" to state.viewMonth),
                Modifier.weight(1f),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                fontSize = 17.sp, fontWeight = FontWeight.Bold,
            )
            IconButton(onClick = { state.shiftMonth(1) }) {
                Icon(Icons.Filled.ChevronRight, contentDescription = "next")
            }
            TextButton(onClick = { state.goToday(); state.refresh() }) {
                Text(T("btn_today"), color = parseHex(state.accent, Color(0xFF2563EB)))
            }
            IconButton(onClick = { state.screen = Screen.SETTINGS }) {
                Icon(Icons.Filled.Settings, contentDescription = T("btn_settings"))
            }
        }

        // ---- 月历网格 ----
        MonthGrid(state, Modifier.fillMaxWidth().weight(1.15f))

        HLine()

        // ---- 当日任务面板 ----
        DayPanel(state, Modifier.fillMaxWidth().weight(1f))
    }
}

// ---------------------------------------------------------------------------
// 月历网格
// ---------------------------------------------------------------------------

@Composable
private fun MonthGrid(state: AppState, modifier: Modifier = Modifier) {
    val lang = LocalLang.current
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val calFg = parseHex(state.calFg, Color(0xFF1F2937))
    val y = state.viewYear
    val m = state.viewMonth
    val first = LocalDate.of(y, m, 1)
    val last = first.withDayOfMonth(first.lengthOfMonth())

    val counts = state.repo.countsByDate(first, last)
    val monthTasks = state.repo.tasksBetween(first, last)
        .groupBy { it.taskDate }
    val emarks = remember(state.tick, y, m) { state.repo.eventMarks(y, m) }

    val sunFirst = state.weekStartSun
    val order = if (sunFirst) listOf(6, 0, 1, 2, 3, 4, 5) else (0..6).toList()
    val offset = if (sunFirst) first.dayOfWeek.value % 7 else first.dayOfWeek.value - 1
    val start = first.minusDays(offset.toLong())
    val sel = state.selDate
    val today = state.today

    Column(modifier) {
        // 表头：周数列 + 7 个星期
        Row(Modifier.fillMaxWidth().height(28.dp)) {
            if (state.showWeekno) {
                Box(Modifier.width(24.dp), contentAlignment = Alignment.Center) {
                    Text(T("week_head"), fontSize = 10.sp, color = Palette.TextSub)
                }
            }
            for (wd in order) {
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    Text(
                        I18n.gridWeekday(lang, wd), fontSize = 12.sp,
                        color = Palette.TextSub, fontWeight = FontWeight.Medium,
                    )
                }
            }
        }
        // 6 行日期
        for (r in 0 until 6) {
            Row(Modifier.fillMaxWidth().weight(1f)) {
                if (state.showWeekno) {
                    Box(Modifier.width(24.dp), contentAlignment = Alignment.Center) {
                        val rowFirst = start.plusDays((r * 7).toLong())
                        val weekRef = if (sunFirst) rowFirst.plusDays(1) else rowFirst
                        Text(
                            "${weekRef.get(IsoFields.WEEK_OF_WEEK_BASED_YEAR)}",
                            fontSize = 9.sp, color = Palette.TextOther,
                        )
                    }
                }
                for (c in 0 until 7) {
                    val d = start.plusDays((r * 7 + c).toLong())
                    val inMonth = d.monthValue == m && d.year == y
                    Box(Modifier.weight(1f).fillMaxSize().padding(0.5.dp)) {
                        DayCell(
                            state = state,
                            date = d,
                            inMonth = inMonth,
                            count = if (inMonth) counts[d.toString()] ?: 0 else 0,
                            tasks = if (inMonth) monthTasks[d].orEmpty() else emptyList(),
                            selected = d == sel,
                            today = d == today,
                            accent = accent,
                            calFg = calFg,
                            lang = lang,
                            eventMark = if (inMonth) emarks[d.dayOfMonth] else null,
                            onClick = {
                                state.selDate = d
                                state.viewYear = d.year
                                state.viewMonth = d.monthValue
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun DayCell(
    state: AppState,
    date: LocalDate,
    inMonth: Boolean,
    count: Int,
    tasks: List<Task>,
    selected: Boolean,
    today: Boolean,
    accent: Color,
    calFg: Color,
    lang: String,
    eventMark: String? = null,
    onClick: () -> Unit,
) {
    var bg = Palette.Cell
    var fg = calFg
    val marks = if (inMonth) Holidays.marks(date) else null
    val hname = marks?.holiday
    if (hname != null && state.showHoliday) { bg = Palette.CellHolidayBg; fg = Palette.Danger }
    if (!inMonth) { bg = Palette.CellOther; fg = Palette.TextOther }
    if (today) bg = Palette.CellToday
    if (selected) bg = mixHex(state.accent, 0.85f)

    // 信息槽优先级：节日名(红) > 节气(绿) > 农历(灰)——与桌面版一致
    var slot = ""
    var slotColor = Palette.TextSub
    if (hname != null && state.showHoliday) {
        slot = Holidays.displayName(hname, lang); slotColor = Palette.Danger
    } else if (inMonth && state.showTerms && lang != "en") {
        // 英文界面不显示节气（没有通用英文译名，与桌面版 v1.5.1 一致）
        SolarTerms.termOfDay(date)?.let { slot = it; slotColor = Palette.TermGreen }
    }
    if (slot.isEmpty() && inMonth && state.showLunar) {
        slot = Lunar.displayText(date, lang); slotColor = Palette.TextOther
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(bg)
            .border(0.5.dp, Palette.GridLine)
            .clickable(onClick = onClick)
            .padding(horizontal = 3.dp, vertical = 2.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${date.dayOfMonth}", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = fg,
            )
            Spacer(Modifier.weight(1f))
            if (!eventMark.isNullOrEmpty()) {
                // 🎂 生日/纪念日、⏳ 倒数日到点（与桌面版 v1.6.0 一致）
                Text(eventMark, fontSize = 10.sp)
                Spacer(Modifier.width(2.dp))
            }
            if (count > 0) {
                Text("$count", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = accent)
            }
        }
        if (inMonth && slot.isNotEmpty()) {
            Text(slot, fontSize = 8.sp, color = slotColor, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (inMonth && state.showRest) {
            val mk = marks
            if (mk != null && mk.makeup) {
                RestMark(T("mark_work"), Palette.WorkMarkBg, Color(0xFF2563EB))
            } else if (mk != null && mk.isRest) {
                RestMark(T("mark_rest"), Palette.RestMarkBg, Palette.Danger)
            }
        }
        for (t in tasks.take(2)) {
            Text(
                text = (if (t.pinned) "📌 " else "") + t.title,
                fontSize = 9.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                color = when {
                    t.important && !t.done -> Palette.Danger
                    t.done -> Palette.Done
                    else -> Palette.TextSub
                },
                textDecoration = if (t.done) TextDecoration.LineThrough else null,
            )
        }
        if (count > 2) {
            Text(T("more_tasks", "n" to count), fontSize = 8.sp, color = accent)
        }
    }
}

@Composable
private fun RestMark(text: String, bg: Color, fg: Color) {
    Text(
        text,
        Modifier
            .clip(RoundedCornerShape(3.dp))
            .background(bg)
            .padding(horizontal = 3.dp),
        fontSize = 8.sp, color = fg,
    )
}

// ---------------------------------------------------------------------------
// 当日任务面板
// ---------------------------------------------------------------------------

@Composable
private fun DayPanel(state: AppState, modifier: Modifier = Modifier) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val d = state.selDate
    val tasks = state.repo.tasksOn(d)
    val pending = tasks.count { !it.done }

    Column(modifier) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val weekName = I18n.weekdayNames(LocalLang.current)[d.dayOfWeek.value - 1]
            Text(
                T(
                    "day_header", "m" to d.monthValue, "d" to d.dayOfMonth,
                    "week" to weekName,
                    "mark" to if (d == state.today) T("today_mark") else "",
                ),
                fontWeight = FontWeight.Bold, fontSize = 15.sp,
            )
            Spacer(Modifier.weight(1f))
            Text(
                T("day_stat", "p" to pending, "n" to tasks.size),
                fontSize = 12.sp, color = Palette.TextSub,
            )
        }
        if (tasks.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    T("empty_hint"),
                    color = Palette.TextOther, fontSize = 13.sp,
                    modifier = Modifier.padding(16.dp),
                )
            }
        } else {
            LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
                items(tasks, key = { it.id }) { t ->
                    TaskRow(state, t, accent)
                    HLine(color = Color(0xFFF3F4F6))
                }
            }
        }
        AddBar(state)
    }
}

@Composable
private fun TaskRow(state: AppState, task: Task, accent: Color) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = task.done,
            onCheckedChange = {
                state.repo.setDone(task.id, it)
                state.refresh()
            },
            colors = CheckboxDefaults.colors(checkedColor = accent),
        )
        Box {
            var open by remember { mutableStateOf(false) }
            Text(
                T("tag_" + task.repeat),
                Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(TypeColors.of(task.repeat))
                    .clickable { open = true }
                    .padding(horizontal = 5.dp, vertical = 3.dp),
                fontSize = 11.sp,
            )
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                Types.ALL.forEach { tp ->
                    DropdownMenuItem(
                        text = { Text(T("type_" + tp), fontSize = 13.sp) },
                        onClick = {
                            state.repo.updateTask(
                                task.copy(repeat = tp, lastRemind = task.lastRemind)
                            )
                            open = false
                            state.refresh()
                        },
                    )
                }
            }
        }
        Column(
            Modifier
                .weight(1f)
                .clickable { state.editingTask = task }
                .padding(horizontal = 6.dp, vertical = 8.dp),
        ) {
            Text(
                text = (if (task.pinned) "📌 " else "") + task.title,
                fontSize = 14.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
                color = when {
                    task.important && !task.done -> Palette.Danger
                    task.done -> Palette.Done
                    else -> MaterialTheme.colorScheme.onBackground
                },
                textDecoration = if (task.done) TextDecoration.LineThrough else null,
            )
        }
        if (task.remindTime.isNotBlank()) {
            Icon(
                Icons.Filled.Schedule, contentDescription = task.remindTime,
                Modifier.width(14.dp).height(14.dp), tint = accent,
            )
            Spacer(Modifier.width(2.dp))
            Text(task.remindTime, fontSize = 11.sp, color = accent)
        }
        IconButton(
            onClick = { state.repo.delete(task.id); state.refresh() },
            modifier = Modifier.width(32.dp).height(32.dp),
        ) {
            Icon(
                Icons.Filled.Delete, contentDescription = T("btn_del"),
                tint = Palette.TextSub,
                modifier = Modifier.width(16.dp).height(16.dp),
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 添加栏
// ---------------------------------------------------------------------------

@Composable
private fun AddBar(state: AppState) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    var title by remember { mutableStateOf("") }
    var type by remember { mutableStateOf(Types.DAY) }
    var remindOn by remember { mutableStateOf(false) }
    var remindTime by remember { mutableStateOf("") }
    var weekdayIdx by remember(state.selDate, state.tick) { mutableIntStateOf(state.selDate.dayOfWeek.value - 1) }
    var weekIntervalIdx by remember { mutableIntStateOf(0) }
    var monthDay by remember(state.selDate, state.tick) { mutableIntStateOf(state.selDate.dayOfMonth) }
    val weekNames = I18n.weekdayNames(LocalLang.current)
    val ivWeeks = I18n.list(LocalLang.current, "iv_weeks")
    val ivVals = listOf(1, 2, 3, 4, 6)

    fun pickTime() {
        val init = if (remindTime.matches(Regex("([01]?\\d|2[0-3]):[0-5]\\d"))) {
            LocalTime.parse(remindTime)
        } else {
            // 预填下一个 5 分钟整点（与桌面版一致）
            val now = LocalTime.now().truncatedTo(ChronoUnit.MINUTES)
            now.plusMinutes((5 - now.minute % 5).toLong())
        }
        android.app.TimePickerDialog(
            context, { _, h, m ->
                remindTime = String.format("%02d:%02d", h, m)
                remindOn = true
            }, init.hour, init.minute, true,
        ).show()
    }

    fun addTask() {
        val t = title.trim()
        if (t.isEmpty()) return
        var d = state.selDate
        when (type) {
            Types.WEEK -> {
                d = d.minusDays((d.dayOfWeek.value - 1).toLong()).plusDays(weekdayIdx.toLong())
                if (d.isBefore(state.today)) d = d.plusWeeks(1)
            }
            Types.MONTH -> {
                val ym = YearMonth.from(d)
                d = ym.atDay(minOf(monthDay, ym.lengthOfMonth()))
                if (d.isBefore(state.today)) {
                    val nm = ym.plusMonths(1)
                    d = nm.atDay(minOf(monthDay, nm.lengthOfMonth()))
                }
            }
            Types.WORKDAY -> {
                // 锚点落在周末/节假日时顺延到下一个工作日（与桌面版 v1.6.0 一致）
                var nd = if (d.isBefore(state.today)) state.today else d
                while (!state.repo.isWorkday(nd)) nd = nd.plusDays(1)
                d = nd
            }
        }
        // 周/月/工作日任务：一次性生成未来各期（同 series_id，每期各自可勾选、各自提醒）
        val draft = Task(
            taskDate = d, title = t, repeat = type,
            remindTime = if (remindOn) remindTime else "",
            interval = if (type == Types.WEEK) ivVals.getOrElse(weekIntervalIdx) { 1 } else 1,
        )
        val (n, lastDate) = state.repo.insertSeries(draft)
        title = ""
        state.selDate = d
        state.viewYear = d.year
        state.viewMonth = d.monthValue
        state.refresh()
        if (n > 1) {   // 周期任务给个明确反馈，免得以为只加了一条
            android.widget.Toast.makeText(
                context,
                I18n.t(state.lang, "series_tip", "n" to n, "d" to lastDate.toString()),
                android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }

    Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                placeholder = { Text(T("edit_task"), fontSize = 13.sp, color = Palette.TextOther) },
                keyboardActions = KeyboardActions(onSend = { addTask() }, onDone = { addTask() }),
            )
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = { addTask() },
                colors = ButtonDefaults.buttonColors(containerColor = accent),
                enabled = title.isNotBlank(),
            ) { Text(T("btn_add")) }
        }
        Row(
            Modifier.fillMaxWidth().padding(top = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            SelectChip(type == Types.DAY, T("tag_day"), accent) { type = Types.DAY }
            SelectChip(type == Types.WEEK, T("tag_week"), accent) { type = Types.WEEK }
            SelectChip(type == Types.MONTH, T("tag_month"), accent) { type = Types.MONTH }
            SelectChip(type == Types.WORKDAY, T("tag_workday"), accent) { type = Types.WORKDAY }
            if (type == Types.WEEK) {
                Box {
                    var open by remember { mutableStateOf(false) }
                    TextButton(onClick = { open = true }) {
                        Text(
                            ivWeeks.getOrElse(weekIntervalIdx) { "" },
                            fontSize = 13.sp,
                        )
                    }
                    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                        ivWeeks.forEachIndexed { i, n ->
                            DropdownMenuItem(
                                text = { Text(n) },
                                onClick = { weekIntervalIdx = i; open = false },
                            )
                        }
                    }
                }
            }
            if (type == Types.WEEK) {
                Box {
                    var open by remember { mutableStateOf(false) }
                    TextButton(onClick = { open = true }) {
                        Text(weekNames.getOrElse(weekdayIdx) { "" }, fontSize = 13.sp)
                    }
                    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                        weekNames.forEachIndexed { i, n ->
                            DropdownMenuItem(
                                text = { Text(n) },
                                onClick = { weekdayIdx = i; open = false },
                            )
                        }
                    }
                }
            }
            if (type == Types.MONTH) {
                Box {
                    var open by remember { mutableStateOf(false) }
                    TextButton(onClick = { open = true }) { Text("$monthDay", fontSize = 13.sp) }
                    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                        for (i in 1..31) {
                            DropdownMenuItem(
                                text = { Text("$i") },
                                onClick = { monthDay = i; open = false },
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.weight(1f))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clickable { if (remindOn) remindOn = false else pickTime() },
            ) {
                Checkbox(
                    checked = remindOn,
                    onCheckedChange = { on -> if (on) pickTime() else remindOn = false },
                    colors = CheckboxDefaults.colors(checkedColor = accent),
                )
                Text(T("lbl_remind"), fontSize = 12.sp)
                if (remindOn && remindTime.isNotBlank()) {
                    Spacer(Modifier.width(4.dp))
                    Text(
                        remindTime, fontSize = 12.sp, color = accent,
                        modifier = Modifier.clickable { pickTime() },
                    )
                }
            }
        }
    }
}
