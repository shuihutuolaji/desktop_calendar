package com.wang.desktopcalendar.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import androidx.compose.ui.window.Dialog
import com.wang.desktopcalendar.data.Task
import com.wang.desktopcalendar.data.Types
import java.time.LocalDate
import java.time.LocalTime

/** 编辑任务对话框：标题 / 类型 / 日期 / 提醒 / 重要 / 置顶（对应桌面版 edit_task） */
@Composable
fun EditTaskDialog(state: AppState, task: Task, onClose: () -> Unit) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    var title by remember { mutableStateOf(task.title) }
    var rep by remember { mutableStateOf(task.repeat) }
    var date by remember { mutableStateOf(task.taskDate) }
    var remindOn by remember { mutableStateOf(task.remindTime.isNotBlank()) }
    var rtime by remember { mutableStateOf(task.remindTime.ifBlank { "09:00" }) }
    var imp by remember { mutableStateOf(task.important) }
    var pin by remember { mutableStateOf(task.pinned) }
    var err by remember { mutableStateOf("") }
    // 周期系列：默认「应用到整个系列」；「删除整个系列」要点两次确认，防误删整片期次
    val nSeries = remember(task.id) { state.repo.seriesCount(task.seriesId) }
    var applySeries by remember { mutableStateOf(true) }
    var confirmDel by remember { mutableStateOf(false) }

    fun pickTime() {
        val init = try { LocalTime.parse(rtime) } catch (_: Exception) { LocalTime.of(9, 0) }
        TimePickerDialog(
            context, { _, h, m -> rtime = String.format("%02d:%02d", h, m) },
            init.hour, init.minute, true,
        ).show()
    }

    fun save() {
        val t = title.trim()
        if (t.isEmpty()) {
            err = I18n.t(state.lang, "no_empty_title")
            return
        }
        state.repo.updateTask(
            Task(
                id = task.id, taskDate = date, title = t, done = task.done,
                repeat = rep, remindTime = if (remindOn) rtime else "",
                important = imp, pinned = pin, lastRemind = "",
                seriesId = task.seriesId,
            ),
            applySeries = applySeries && nSeries > 1,
        )
        state.selDate = date
        state.viewYear = date.year
        state.viewMonth = date.monthValue
        state.refresh()
        onClose()
    }

    Dialog(onDismissRequest = onClose) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
        ) {
            Column(
                Modifier
                    .padding(16.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                Text(T("edit_title"), fontWeight = FontWeight.Bold, fontSize = 16.sp)

                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    singleLine = true,
                    label = { Text(T("edit_task"), fontSize = 12.sp) },
                )
                if (err.isNotEmpty()) {
                    Text(err, color = Palette.Danger, fontSize = 12.sp)
                }

                Text(T("edit_type"), fontSize = 12.sp, color = Palette.TextSub,
                    modifier = Modifier.padding(top = 10.dp))
                Row(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(6.dp)) {
                    for (tp in Types.ALL) {
                        SelectChip(rep == tp, T("type_" + tp), accent) { rep = tp }
                    }
                }

                Row(
                    Modifier.padding(top = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(T("edit_date"), fontSize = 12.sp, color = Palette.TextSub)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "$date",
                        fontSize = 15.sp, color = accent,
                        modifier = Modifier.clickableText {
                            DatePickerDialog(
                                context, { _, y, m, dd -> date = LocalDate.of(y, m + 1, dd) },
                                date.year, date.monthValue - 1, date.dayOfMonth,
                            ).show()
                        },
                    )
                }

                Row(
                    Modifier.padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Switch(
                        checked = remindOn,
                        onCheckedChange = {
                            remindOn = it
                            if (it) pickTime()
                        },
                        colors = SwitchDefaults.colors(checkedTrackColor = accent),
                    )
                    Text(T("enable_remind"), fontSize = 13.sp,
                        modifier = Modifier.padding(start = 8.dp))
                    if (remindOn) {
                        Spacer(Modifier.weight(1f))
                        Text(
                            rtime, fontSize = 14.sp, color = accent,
                            modifier = Modifier.clickableText { pickTime() },
                        )
                    }
                }

                Row(
                    Modifier.padding(top = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Switch(
                        checked = imp,
                        onCheckedChange = { imp = it },
                        colors = SwitchDefaults.colors(checkedTrackColor = Palette.Danger),
                    )
                    Text(T("lbl_important"), fontSize = 13.sp,
                        modifier = Modifier.padding(start = 8.dp))
                    Spacer(Modifier.width(16.dp))
                    Switch(
                        checked = pin,
                        onCheckedChange = { pin = it },
                        colors = SwitchDefaults.colors(checkedTrackColor = accent),
                    )
                    Text(T("lbl_pinned"), fontSize = 13.sp,
                        modifier = Modifier.padding(start = 8.dp))
                }

                // —— 周期系列：整系列同步（仅周/月任务且多于 1 期时显示）——
                if (nSeries > 1) {
                    Row(
                        Modifier.padding(top = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = applySeries,
                            onCheckedChange = { applySeries = it },
                            colors = CheckboxDefaults.colors(checkedColor = accent),
                        )
                        Text(T("apply_series"), fontSize = 12.sp,
                            modifier = Modifier.padding(start = 4.dp))
                    }
                    Text(
                        T("series_count", "n" to nSeries),
                        fontSize = 11.sp, color = Palette.TextSub,
                    )
                    Text(
                        T("apply_series_note"), fontSize = 11.sp, color = Palette.TextSub,
                    )
                }

                Row(
                    Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = androidx.compose.foundation.layout.Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (nSeries > 1) {
                        TextButton(onClick = {
                            if (confirmDel) {
                                state.repo.deleteSeries(task.seriesId)
                                state.refresh()
                                onClose()
                            } else {
                                confirmDel = true
                            }
                        }) {
                            Text(
                                if (confirmDel) T("del_series_confirm") else T("del_series"),
                                color = if (confirmDel) Palette.Danger else Palette.TextSub,
                                fontSize = 12.sp,
                            )
                        }
                    }
                    TextButton(onClick = onClose) { Text(T("btn_cancel")) }
                    Button(
                        onClick = { save() },
                        colors = ButtonDefaults.buttonColors(containerColor = accent),
                    ) { Text(T("btn_save")) }
                }
            }
        }
    }
}

/** Modifier.clickableText 小工具（可点击文字） */
private fun Modifier.clickableText(onClick: () -> Unit): Modifier =
    this.clickable(onClick = onClick)

/** 添加倒数日/纪念日：名称 + 日期 + 类型 + 是否农历（对应桌面版 add_event_dialog） */
@Composable
fun EventDialog(state: AppState, onClose: () -> Unit) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    var name by remember { mutableStateOf("") }
    var date by remember { mutableStateOf(state.today) }
    var annual by remember { mutableStateOf(true) }
    var lunar by remember { mutableStateOf(false) }

    Dialog(onDismissRequest = onClose) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.padding(16.dp)) {
                Text(T("event_win_title"), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    singleLine = true,
                    label = { Text(T("event_name"), fontSize = 12.sp) },
                )
                Row(
                    Modifier.padding(top = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(T("event_date"), fontSize = 12.sp, color = Palette.TextSub)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "$date",
                        fontSize = 15.sp, color = accent,
                        modifier = Modifier.clickableText {
                            DatePickerDialog(
                                context, { _, y, m, dd -> date = LocalDate.of(y, m + 1, dd) },
                                date.year, date.monthValue - 1, date.dayOfMonth,
                            ).show()
                        },
                    )
                }
                Row(
                    Modifier.padding(top = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    SelectChip(annual, T("event_annual"), accent) { annual = true }
                    Spacer(Modifier.width(6.dp))
                    SelectChip(!annual, T("event_countdown"), accent) { annual = false }
                }
                Row(
                    Modifier.padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(
                        checked = lunar,
                        onCheckedChange = { lunar = it },
                        colors = CheckboxDefaults.colors(checkedColor = accent),
                    )
                    Text(T("event_lunar"), fontSize = 13.sp,
                        modifier = Modifier.padding(start = 4.dp))
                }
                Row(
                    Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = androidx.compose.foundation.layout.Arrangement.End,
                ) {
                    TextButton(onClick = onClose) { Text(T("btn_cancel")) }
                    Button(
                        onClick = {
                            val n = name.trim()
                            if (n.isEmpty()) return@Button
                            state.repo.addEvent(
                                n, date, if (annual) "annual" else "countdown", lunar)
                            state.refresh()
                            onClose()
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = accent),
                    ) { Text(T("btn_ok")) }
                }
            }
        }
    }
}
