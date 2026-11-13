package com.wang.desktopcalendar.ui

import android.widget.Toast
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import com.wang.desktopcalendar.wecom.WeCom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 推送今日待办：勾选任务后发送企业微信（对应桌面版 push_today_to_wecom） */
@Composable
fun PushTodayDialog(state: AppState, onClose: () -> Unit) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val tasks = state.repo.tasksOn(state.today)
    val checked = remember(tasks) {
        mutableStateOf(tasks.associate { it.id to !it.done }.toMutableMap())
    }

    fun buildContent(sel: List<Task>): String {
        val lang = state.lang
        val day = state.today
        val lines = mutableListOf(
            I18n.t(lang, "push_lines", "m" to day.monthValue, "d" to day.dayOfMonth, "n" to sel.size)
        )
        for (t in sel) {
            val mark = if (t.done) "✅" else if (t.important) "🔴" else "▫️"
            var text = (if (t.pinned) "📌 " else "") + t.title
            if (t.remindTime.isNotBlank()) text += "（⏰${t.remindTime}）"
            lines.add("$mark $text")
        }
        return lines.joinToString("\n")
    }

    fun push() {
        val sel = tasks.filter { checked.value[it.id] == true }
        if (sel.isEmpty()) {
            Toast.makeText(
                context, I18n.t(state.lang, "push_need_one"), Toast.LENGTH_SHORT,
            ).show()
            return
        }
        val webhook = state.wecomWebhook.trim()
        val cid = state.wecomCorpId.trim()
        val aid = state.wecomAgentId.trim()
        val sec = state.wecomCorpSecret.trim()
        if (webhook.isBlank() && (cid.isBlank() || aid.isBlank() || sec.isBlank())) {
            Toast.makeText(
                context, I18n.t(state.lang, "no_wecom_cfg2"), Toast.LENGTH_SHORT,
            ).show()
            return
        }
        val content = buildContent(sel)
        scope.launch {
            val raw = withContext(Dispatchers.IO) {
                buildList {
                    if (webhook.isNotBlank()) add("群机器人" to WeCom.push(webhook, content).first)
                    if (cid.isNotBlank() && aid.isNotBlank() && sec.isNotBlank())
                        add("企业微信应用" to WeCom.appPush(cid, aid, sec, content).first)
                }
            }
            val ok = raw.filter { it.second }.map { it.first }
            val msg = if (ok.isNotEmpty()) {
                I18n.t(state.lang, "wecom_result_ok", "names" to ok.joinToString("、"))
            } else I18n.t(state.lang, "wecom_result_sent")
            Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
            onClose()
        }
    }

    Dialog(onDismissRequest = onClose) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.padding(16.dp)) {
                Text(
                    I18n.t(
                        state.lang, "push_pick",
                        "m" to state.today.monthValue, "d" to state.today.dayOfMonth,
                    ),
                    fontWeight = FontWeight.Bold, fontSize = 15.sp,
                )
                if (tasks.isEmpty()) {
                    Text(
                        I18n.t(state.lang, "no_tasks_today"),
                        Modifier.padding(vertical = 16.dp),
                        color = Palette.TextSub, fontSize = 13.sp,
                    )
                } else {
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(vertical = 6.dp)) {
                        for (t in tasks) {
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    // 整体替换 map 触发重组，勾选框才会刷新
                                    checked.value = checked.value.toMutableMap().apply {
                                        put(t.id, !(checked.value[t.id] ?: true))
                                    }
                                },
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(
                                    checked = checked.value[t.id] ?: true,
                                    onCheckedChange = { on ->
                                        checked.value = checked.value.toMutableMap()
                                            .apply { put(t.id, on) }
                                    },
                                    colors = androidx.compose.material3.CheckboxDefaults.colors(
                                        checkedColor = accent,
                                    ),
                                )
                                Text(
                                    (if (t.done) "✅" else if (t.important) "🔴" else "▫️") + " " +
                                        (if (t.pinned) "📌 " else "") + t.title +
                                        (if (t.remindTime.isNotBlank()) "（⏰${t.remindTime}）" else ""),
                                    fontSize = 13.sp, modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                    Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
                        TextButton(onClick = {
                            checked.value = tasks.associate { it.id to true }.toMutableMap()
                        }) { Text(I18n.t(state.lang, "select_all"), fontSize = 12.sp) }
                        Spacer(Modifier.width(4.dp))
                        TextButton(onClick = {
                            checked.value = tasks.associate { it.id to false }.toMutableMap()
                        }) { Text(I18n.t(state.lang, "select_none"), fontSize = 12.sp) }
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = onClose) {
                            Text(I18n.t(state.lang, "btn_cancel"), fontSize = 13.sp)
                        }
                        Button(
                            onClick = { push() },
                            colors = ButtonDefaults.buttonColors(containerColor = accent),
                        ) { Text(I18n.t(state.lang, "push")) }
                    }
                }
            }
        }
    }
}
