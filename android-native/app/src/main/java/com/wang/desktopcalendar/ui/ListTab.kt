package com.wang.desktopcalendar.ui

import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import com.wang.desktopcalendar.data.Transfer
import java.time.LocalDate

/** 全部清单页：全量任务列表 + 清理/导出/导入（对应桌面版 tab_list） */
@Composable
fun ListTab(state: AppState) {
    val accent = parseHex(state.accent, Color(0xFF2563EB))
    val context = LocalContext.current
    val tasks = state.repo.tasksAll()
    val today = state.today

    var importCandidates by remember { mutableStateOf<List<Task>?>(null) }
    var showExportPick by remember { mutableStateOf(false) }

    val exportJsonLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri -> uri?.let { doExport(context, state, it, false) } }

    val exportCsvLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("text/csv")
    ) { uri -> uri?.let { doExport(context, state, it, true) } }

    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            val items = doReadImport(context, uri)
            if (items == null) {
                Toast.makeText(
                    context, I18n.t(state.lang, "import_read_fail", "e" to "?"),
                    Toast.LENGTH_SHORT,
                ).show()
            } else if (items.isEmpty()) {
                Toast.makeText(
                    context, I18n.t(state.lang, "import_none"), Toast.LENGTH_SHORT,
                ).show()
            } else {
                importCandidates = items
            }
        }
    }

    fun toast(msg: String) = Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()

    // 导出格式选择
    if (showExportPick) {
        androidx.compose.ui.window.Dialog(onDismissRequest = { showExportPick = false }) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.surface,
            ) {
                Column(Modifier.padding(20.dp)) {
                    Text(T("export_title"), fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    Spacer(Modifier.width(0.dp))
                    TextButton(onClick = {
                        showExportPick = false
                        exportJsonLauncher.launch(
                            "calendar_tasks_${LocalDate.now().toString().replace("-", "")}.json"
                        )
                    }) { Text("JSON 备份（完整）", fontSize = 14.sp) }
                    TextButton(onClick = {
                        showExportPick = false
                        exportCsvLauncher.launch(
                            "calendar_tasks_${LocalDate.now().toString().replace("-", "")}.csv"
                        )
                    }) { Text("CSV 表格（Excel）", fontSize = 14.sp) }
                    TextButton(onClick = { showExportPick = false }) {
                        Text(T("btn_cancel"), fontSize = 14.sp, color = Palette.TextSub)
                    }
                }
            }
        }
    }

    // 导入确认（清空恢复 / 合并）
    importCandidates?.let { items ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { importCandidates = null }) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.surface,
            ) {
                Column(Modifier.padding(20.dp)) {
                    Text(T("import_title"), fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    Text(
                        T("import_ask", "n" to items.size),
                        fontSize = 13.sp, color = Palette.TextSub,
                        modifier = Modifier.padding(vertical = 10.dp),
                    )
                    Row {
                        TextButton(onClick = {
                            val n = state.repo.replaceAll(items)
                            state.repo.rollPending(LocalDate.now())
                            importCandidates = null
                            state.refresh()
                            toast(I18n.t(state.lang, "import_done_msg", "a" to n, "s" to 0))
                        }) { Text("清空后导入", color = Palette.Danger) }
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = {
                            val (a, s) = state.repo.mergeImport(items)
                            state.repo.rollPending(LocalDate.now())
                            importCandidates = null
                            state.refresh()
                            toast(I18n.t(state.lang, "import_done_msg", "a" to a, "s" to s))
                        }) { Text("合并导入", color = accent) }
                        TextButton(onClick = { importCandidates = null }) {
                            Text(T("btn_cancel"), color = Palette.TextSub)
                        }
                    }
                }
            }
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        // 工具栏
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp)
                .horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                T("list_hint"), fontSize = 11.sp, color = Palette.TextSub,
                modifier = Modifier.padding(end = 8.dp),
            )
            TextButton(onClick = {
                state.repo.clearDone(); state.refresh()
            }) { Text(T("btn_clear"), fontSize = 12.sp) }
            TextButton(onClick = { showExportPick = true }) {
                Text(T("btn_export"), fontSize = 12.sp)
            }
            TextButton(onClick = { importLauncher.launch(arrayOf("*/*")) }) {
                Text(T("btn_import"), fontSize = 12.sp)
            }
        }
        HLine()
        // 任务列表
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            items(tasks, key = { it.id }) { t ->
                ListRow(state, t, today, accent)
                HLine(color = Color(0xFFF3F4F6))
            }
        }
    }
}

@Composable
private fun ListRow(state: AppState, task: Task, today: LocalDate, accent: Color) {
    val d = task.taskDate
    // 状态：已完成(灰)/逾期(红)/今天(蓝)/未来(默认)，重要未完成标红——与桌面版一致
    val (statusText, statusColor) = when {
        task.done -> T("st_done") to Palette.Done
        d.isBefore(today) -> T("st_overdue") to Palette.Danger
        d == today -> T("st_today") to accent
        else -> T("st_future") to Palette.TextSub
    }
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = task.done,
            onCheckedChange = { state.repo.setDone(task.id, it); state.refresh() },
            colors = CheckboxDefaults.colors(checkedColor = accent),
        )
        Text(
            T("tag_" + task.repeat),
            Modifier
                .clip(RoundedCornerShape(4.dp))
                .background(TypeColors.of(task.repeat))
                .padding(horizontal = 5.dp, vertical = 3.dp),
            fontSize = 11.sp,
        )
        Column(
            Modifier
                .weight(1f)
                .clickable { state.editingTask = task }
                .padding(horizontal = 8.dp, vertical = 8.dp),
        ) {
            Text(
                text = (if (task.pinned) "📌 " else "") + task.title,
                fontSize = 14.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
                color = if (task.important && !task.done) Palette.Danger
                else MaterialTheme.colorScheme.onBackground,
                textDecoration = if (task.done) TextDecoration.LineThrough else null,
            )
            Text(
                "$d　$statusText${if (task.remindTime.isNotBlank()) "　⏰" + task.remindTime else ""}",
                fontSize = 11.sp, color = statusColor,
            )
        }
        IconButton(onClick = { state.repo.delete(task.id); state.refresh() }) {
            Icon(
                Icons.Filled.Delete, contentDescription = T("btn_del"),
                tint = Palette.TextSub,
                modifier = Modifier.width(16.dp),
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 导入 / 导出实现
// ---------------------------------------------------------------------------

private fun doExport(context: android.content.Context, state: AppState, uri: Uri, csv: Boolean) {
    val text = try {
        val tasks = state.repo.tasksAll()
        if (csv) Transfer.exportCsv(tasks) else Transfer.exportJson(tasks)
    } catch (e: Exception) {
        Toast.makeText(
            context, I18n.t(state.lang, "export_fail_msg", "e" to e.message),
            Toast.LENGTH_SHORT,
        ).show()
        return
    }
    try {
        context.contentResolver.openOutputStream(uri)?.use { os ->
            if (csv) os.write(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()))
            os.write(text.toByteArray(Charsets.UTF_8))
        }
        val n = state.repo.tasksAll().size
        Toast.makeText(
            context, I18n.t(state.lang, "export_done_msg", "n" to n), Toast.LENGTH_SHORT,
        ).show()
    } catch (e: Exception) {
        Toast.makeText(
            context, I18n.t(state.lang, "export_fail_msg", "e" to e.message),
            Toast.LENGTH_SHORT,
        ).show()
    }
}

private fun doReadImport(context: android.content.Context, uri: Uri): List<Task>? = try {
    val text = context.contentResolver.openInputStream(uri)?.use { ins ->
        ins.readBytes().toString(Charsets.UTF_8)
    } ?: ""
    Transfer.parseImport(text)
} catch (e: Exception) {
    null
}
