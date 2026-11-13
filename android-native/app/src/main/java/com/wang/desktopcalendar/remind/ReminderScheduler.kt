package com.wang.desktopcalendar.remind

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import com.wang.desktopcalendar.data.SettingsStore
import com.wang.desktopcalendar.data.Task
import com.wang.desktopcalendar.data.TaskRepo
import com.wang.desktopcalendar.wecom.WeCom
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

/**
 * 提醒调度（对应桌面版 check_reminders 的常驻轮询，这里改为系统闹钟驱动）：
 * - 有到点且未提醒过的任务：立即弹通知；同时按设置推送企业微信；
 * - 到点超过 12 小时仍未提醒的（长期没打开应用）：静默标记，避免通知轰炸；
 * - 始终为最近的将来任务排一个精确闹钟；
 * - 未授予「闹钟和提醒」精确权限时退化为非精确闹钟（可能推迟，但不丢）。
 */
object ReminderScheduler {

    /** 超过这么久的到点任务不再弹窗，只静默标记 */
    private const val GRACE_HOURS = 12L

    private fun alarmPendingIntent(context: Context): PendingIntent =
        PendingIntent.getBroadcast(
            context, 0, Intent(context, AlarmReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    /**
     * 检查到点任务并排布下一次闹钟。任务数据变化、应用启动/回前台、
     * 闹钟触发、开机后都会调用。网络推送在 IO 协程执行。
     */
    fun reschedule(context: Context) {
        val app = context.applicationContext
        val repo = TaskRepo.get(app)
        val settings = SettingsStore(app)
        val now = LocalDateTime.now()
        val newlyDue = mutableListOf<Task>()
        val early = mutableListOf<Pair<Task, Int>>()
        val earlyMin = settings.remindEarly

        var next: LocalDateTime? = null
        for (t in repo.pendingWithReminder()) {
            val dueDt = try {
                LocalDateTime.of(t.taskDate, LocalTime.parse(t.remindTime))
            } catch (_: Exception) { continue }
            val key = "${t.taskDate} ${t.remindTime}"
            if (t.lastRemind == key) continue
            when {
                dueDt.isAfter(now) -> {
                    // 提前提醒：把提前窗口的起点也纳入闹钟排程（与桌面版 v1.6.0 一致）
                    if (earlyMin > 0) {
                        val eDt = dueDt.minusMinutes(earlyMin.toLong())
                        if (now.isBefore(eDt) && (next == null || eDt.isBefore(next))) next = eDt
                    }
                    if (next == null || dueDt.isBefore(next)) next = dueDt
                }
                dueDt.isAfter(now.minusHours(GRACE_HOURS)) -> newlyDue.add(t)
                else -> repo.markReminded(t.id, key) // 太久远的静默补记
            }
        }

        if (newlyDue.isNotEmpty()) {
            for (t in newlyDue) repo.markReminded(t.id, "${t.taskDate} ${t.remindTime}")
            Notify.fire(app, newlyDue)
            if (settings.wecomPush) {
                val content = formatReminder(newlyDue, settings.language)
                val webhook = settings.wecomWebhook
                val cid = settings.wecomCorpId
                val aid = settings.wecomAgentId
                val secret = settings.wecomCorpSecret
                CoroutineScope(Dispatchers.IO).launch {
                    if (webhook.isNotBlank()) WeCom.push(webhook, content)
                    if (cid.isNotBlank() && aid.isNotBlank() && secret.isNotBlank())
                        WeCom.appPush(cid, aid, secret, content)
                }
            }
        }

        // 提前提醒：进入提前窗口且尚未弹过——只弹本地通知，不推企业微信
        if (earlyMin > 0) {
            for (t in repo.pendingWithReminder()) {
                val dueDt = try {
                    LocalDateTime.of(t.taskDate, LocalTime.parse(t.remindTime))
                } catch (_: Exception) { continue }
                val key = "${t.taskDate} ${t.remindTime}"
                if (t.lastRemind == key || !dueDt.isAfter(now)) continue
                val eKey = "${key}#e${earlyMin}"
                if (t.lastRemind == eKey) continue
                if (now >= dueDt.minusMinutes(earlyMin.toLong())) early.add(t to earlyMin)
            }
        }
        if (early.isNotEmpty()) {
            for ((t, n) in early) repo.markReminded(t.id, "${t.taskDate} ${t.remindTime}#e${n}")
            Notify.fireEarly(app, early)
        }

        scheduleAlarm(app, next)
    }

    private fun scheduleAlarm(context: Context, next: LocalDateTime?) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = alarmPendingIntent(context)
        if (next == null) {
            am.cancel(pi)
            return
        }
        val at = next.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
        val exactAllowed = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms()
        if (exactAllowed) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
        } else {
            // 非精确兜底：系统可能在低电量时推迟十几分钟，但一定会触发
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
        }
    }

    /** 提醒的企业微信 markdown 正文（标题随界面语言，与桌面版一致） */
    fun formatReminder(dueItems: List<Task>, lang: String = "zh"): String {
        val head = com.wang.desktopcalendar.ui.I18n.t(lang, "wecom_remind_head")
        val lines = mutableListOf(head)
        for (t in dueItems) {
            lines.add("> ${t.taskDate.toString().substring(5)} ${t.remindTime}　${t.title}")
        }
        return lines.joinToString("\n")
    }

    /** 应用启动/回到前台时调用：跨天顺延 + 补期 + 自动备份 + 重排提醒 + 事件日检查 + 订阅同步 */
    fun onAppForeground(context: Context) {
        val app = context.applicationContext
        val repo = TaskRepo.get(app)
        val settings = SettingsStore(app)
        repo.rollPending(LocalDate.now())
        repo.expandSeries(LocalDate.now())   // 周/月/工作日任务：补齐未来各期
        if (settings.autoBackup) repo.backupDaily()
        reschedule(app)
        checkEventDay(app)
        icsAutoSync(app, settings)
    }

    /** 当天有生日/纪念日（农历自动换算）或倒数日到点：每天弹一次祝贺通知 */
    private fun checkEventDay(context: Context) {
        val app = context.applicationContext
        val settings = SettingsStore(app)
        val today = LocalDate.now()
        if (settings.lastEventToast == today.toString()) return
        val lines = mutableListOf<String>()
        for (e in TaskRepo.get(app).eventsAll()) {
            val hit = if (e.kind == "annual") {
                val tgt = if (e.lunar) TaskRepo.get(app).lunarAnnualDate(e.eventDate, today.year)
                else try { e.eventDate.withYear(today.year) } catch (_: Exception) { null }
                tgt == today
            } else e.eventDate == today
            if (hit) lines.add("${if (e.kind == "annual") "🎂" else "⏳"} ${e.name}")
        }
        if (lines.isNotEmpty()) {
            settings.lastEventToast = today.toString()
            Notify.fireEvents(app, lines)
        }
    }

    /** ICS 订阅每日静默同步：距上次超过 24 小时才拉取，失败不打扰 */
    private fun icsAutoSync(context: Context, settings: SettingsStore) {
        val app = context.applicationContext
        val url = settings.icsUrl
        if (url.isBlank()) return
        val stale = try {
            settings.icsLastSync.isBlank() || java.time.Duration.between(
                LocalDateTime.parse(settings.icsLastSync), LocalDateTime.now(),
            ).toHours() >= 24
        } catch (_: Exception) { true }
        if (!stale) return
        CoroutineScope(Dispatchers.IO).launch {
            try {
                TaskRepo.get(app).icsSync(url)
                settings.icsLastSync = LocalDateTime.now().toString()
            } catch (_: Exception) { }
        }
    }
}

/** 闹钟到点：重新走一遍检查（此时会有新到点任务弹通知） */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pr = goAsync()
        Thread {
            try { ReminderScheduler.reschedule(context.applicationContext) }
            finally { pr.finish() }
        }.start()
    }
}

/** 通知按钮：全部完成 / 知道了 */
class ReminderActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Notify.ACTION_MARK_DONE -> {
                val ids = intent.getLongArrayExtra(Notify.EXTRA_IDS) ?: LongArray(0)
                TaskRepo.get(context).setDoneIds(ids.toList(), true)
            }
        }
        Notify.cancel(context)
        val pr = goAsync()
        Thread {
            try { ReminderScheduler.reschedule(context.applicationContext) }
            finally { pr.finish() }
        }.start()
    }
}

/** 开机 / 时间或时区变化：顺延任务并重排闹钟 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in setOf(
                Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_TIME_CHANGED,
                Intent.ACTION_TIMEZONE_CHANGED)
        ) return
        val pr = goAsync()
        Thread {
            try { ReminderScheduler.onAppForeground(context.applicationContext) }
            finally { pr.finish() }
        }.start()
    }
}
