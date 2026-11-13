package com.wang.desktopcalendar.ui

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import com.wang.desktopcalendar.wecom.WeCom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate

/** 设置页：语言 / 显示项 / 颜色 / 企业微信（对应桌面版 open_settings） */
@Composable
fun SettingsTab(state: AppState) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    fun toast(msg: String) = Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()

    fun persist() = state.persist()

    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
    ) {
        // 顶部返回 + 标题
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { state.persist(); state.screen = Screen.CALENDAR }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = T("btn_done"))
            }
            Text(T("settings"), fontSize = 18.sp, fontWeight = FontWeight.Bold)
        }

        // —— 界面语言 ——
        SectionLabel(T("language"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SelectChip(state.lang == "zh", "中文", accent) {
                state.lang = "zh"; persist(); state.refresh()
            }
            SelectChip(state.lang == "en", "English", accent) {
                state.lang = "en"; persist(); state.refresh()
            }
        }

        // —— 每周开始于 ——
        SectionLabel(T("week_start"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SelectChip(!state.weekStartSun, T("monday"), accent) {
                state.weekStartSun = false; persist()
            }
            SelectChip(state.weekStartSun, T("sunday"), accent) {
                state.weekStartSun = true; persist()
            }
        }

        // —— 日历显示 ——
        SectionLabel(T("disp_label"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SelectChip(state.showWeekno, T("disp_weekno"), accent) {
                state.showWeekno = !state.showWeekno; persist()
            }
            SelectChip(state.showLunar, T("disp_lunar"), accent) {
                state.showLunar = !state.showLunar; persist()
            }
            SelectChip(state.showTerms, T("disp_terms"), accent) {
                state.showTerms = !state.showTerms; persist()
            }
            SelectChip(state.showRest, T("disp_rest"), accent) {
                state.showRest = !state.showRest; persist()
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = state.showHoliday,
                onCheckedChange = { state.showHoliday = it; persist() },
                colors = SwitchDefaults.colors(checkedTrackColor = accent),
            )
            Text(T("show_holiday"), fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp))
        }

        // —— 颜色 ——
        SectionLabel(T("cal_fg"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((name, hex) in Presets.CAL_FG) {
                ColorSwatch(hex, state.calFg == hex) { state.calFg = hex; persist(); state.refresh() }
            }
        }
        SectionLabel(T("accent_color"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((name, hex) in Presets.ACCENT) {
                ColorSwatch(hex, state.accent == hex) { state.accent = hex; persist(); state.refresh() }
            }
        }
        SectionLabel(T("bg_color"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((name, hex) in Presets.BG) {
                ColorSwatch(hex, state.bgColor == hex) { state.bgColor = hex; persist(); state.refresh() }
            }
        }
        Row(Modifier.padding(top = 4.dp)) {
            Text(
                Presets.BG.joinToString("　") { "${I18n.t(state.lang, it.first)} ${it.second}" },
                fontSize = 10.sp, color = Palette.TextSub,
            )
        }

        // —— 提醒说明 ——
        SectionLabel(T("toast_title"))
        Text(T("notif_hint"), fontSize = 12.sp, color = Palette.TextSub)
        Text(T("exact_alarm_hint"), fontSize = 12.sp, color = Palette.TextSub)

        // —— 提前提醒（与桌面版 v1.6.0 一致：到期前提前弹一次本地通知）——
        SectionLabel(T("remind_early"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val vals = listOf(0, 5, 10, 30, 60, 1440)
            val labels = I18n.list(state.lang, "early_vals")
            vals.forEachIndexed { i, v ->
                SelectChip(state.remindEarly == v, labels.getOrElse(i) { "$v" }, accent) {
                    state.remindEarly = v; persist()
                }
            }
        }

        // —— 每日自动备份 ——
        Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = state.autoBackup,
                onCheckedChange = { state.autoBackup = it; persist() },
                colors = SwitchDefaults.colors(checkedTrackColor = accent),
            )
            Text(T("auto_backup"), fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp))
        }

        // —— ICS 日历订阅 ——
        SectionLabel(T("ics_head"))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = state.icsUrl,
                onValueChange = { state.icsUrl = it; persist() },
                modifier = Modifier.weight(1f),
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                placeholder = { Text("https://…/calendar.ics", fontSize = 11.sp) },
            )
            TextButton(onClick = {
                val url = state.icsUrl.trim()
                if (url.isBlank()) {
                    toast(I18n.t(state.lang, "ics_no_url")); return@TextButton
                }
                state.icsUrl = url; persist()
                scope.launch {
                    val msg = withContext(Dispatchers.IO) {
                        try {
                            val (a, s) = state.repo.icsSync(url)
                            state.settings.icsLastSync =
                                java.time.LocalDateTime.now().toString()
                            I18n.t(state.lang, "ics_ok", "n" to a, "s" to s)
                        } catch (e: Exception) {
                            I18n.t(state.lang, "ics_fail", "e" to (e.message ?: e.toString()))
                        }
                    }
                    toast(msg)
                    state.refresh()
                }
            }) { Text(T("ics_sync"), fontSize = 13.sp, color = accent) }
        }
        Text(T("ics_hint"), fontSize = 11.sp, color = Palette.TextSub)

        // —— 企业微信推送 ——
        SectionLabel(T("wecom_hook"))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = state.wecomWebhook,
                onValueChange = { state.wecomWebhook = it; persist() },
                modifier = Modifier.weight(1f),
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                placeholder = { Text("https://qyapi.weixin.qq.com/...", fontSize = 11.sp) },
            )
            TextButton(onClick = {
                val hook = state.wecomWebhook.trim()
                if (hook.isBlank()) {
                    toast(I18n.t(state.lang, "no_wecom_cfg")); return@TextButton
                }
                state.wecomWebhook = hook; persist()
                scope.launch {
                    val (ok, err) = withContext(Dispatchers.IO) {
                        WeCom.push(hook, I18n.t(state.lang, "wecom_test_msg"))
                    }
                    toast(
                        when {
                            ok -> I18n.t(state.lang, "wecom_test_sent")
                            "93000" in err -> I18n.t(state.lang, "wecom_bad_hook")
                            else -> I18n.t(state.lang, "wecom_send_fail", "e" to err)
                        }
                    )
                }
            }) { Text(T("btn_test"), fontSize = 13.sp) }
        }
        Text(T("wecom_hook_hint"), fontSize = 11.sp, color = Palette.TextSub)

        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = state.wecomPush,
                onCheckedChange = { state.wecomPush = it; persist() },
                colors = SwitchDefaults.colors(checkedTrackColor = accent),
            )
            Text(T("wecom_also_push"), fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp))
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { state.showPushToday = true }) {
                Text(T("btn_push_today"), fontSize = 13.sp, color = accent)
            }
        }

        SectionLabel(T("wecom_app"))
        OutlinedTextField(
            value = state.wecomCorpId,
            onValueChange = { state.wecomCorpId = it; persist() },
            modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                label = { Text("CorpID", fontSize = 11.sp) },
        )
        OutlinedTextField(
            value = state.wecomAgentId,
            onValueChange = { state.wecomAgentId = it; persist() },
            modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                label = { Text("AgentID", fontSize = 11.sp) },
        )
        OutlinedTextField(
            value = state.wecomCorpSecret,
            onValueChange = { state.wecomCorpSecret = it; persist() },
            modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                label = { Text("Secret", fontSize = 11.sp) },
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = {
                val cid = state.wecomCorpId.trim()
                val aid = state.wecomAgentId.trim()
                val sec = state.wecomCorpSecret.trim()
                if (cid.isBlank() || aid.isBlank() || sec.isBlank()) {
                    toast(I18n.t(state.lang, "wecom_fill")); return@TextButton
                }
                state.wecomCorpId = cid; state.wecomAgentId = aid; state.wecomCorpSecret = sec
                persist()
                scope.launch {
                    val (ok, err) = withContext(Dispatchers.IO) {
                        WeCom.appPush(cid, aid, sec, I18n.t(state.lang, "wecom_app_test_msg"))
                    }
                    toast(
                        if (ok) I18n.t(state.lang, "wecom_test_ok")
                        else I18n.t(state.lang, "wecom_ip_hint", "e" to err)
                    )
                }
            }) { Text(T("btn_test_app"), fontSize = 13.sp) }
            Text(T("wecom_app_hint"), fontSize = 11.sp, color = Palette.TextSub)
        }

        // —— 底部签名 ——
        Text(
            T("signature"),
            Modifier.fillMaxWidth().padding(vertical = 24.dp),
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            fontSize = 12.sp, color = accent,
        )
    }
}
