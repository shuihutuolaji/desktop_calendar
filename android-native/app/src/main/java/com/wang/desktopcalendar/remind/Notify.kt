package com.wang.desktopcalendar.remind

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.wang.desktopcalendar.MainActivity
import com.wang.desktopcalendar.R
import com.wang.desktopcalendar.data.Task

/** 提醒通知：渠道创建、到点弹通知（含「全部完成/知道了」两个按钮） */
object Notify {

    const val CHANNEL_ID = "reminders"
    const val NOTIF_ID = 1001
    const val ACTION_MARK_DONE = "com.wang.desktopcalendar.action.MARK_DONE"
    const val ACTION_DISMISS = "com.wang.desktopcalendar.action.DISMISS"
    const val EXTRA_IDS = "ids"

    fun ensureChannel(context: Context) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val ch = NotificationChannel(
            CHANNEL_ID, "任务提醒", NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "到点的任务提醒通知"
            enableVibration(true)
        }
        nm.createNotificationChannel(ch)
    }

    private fun canNotify(context: Context): Boolean =
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        } else true

    private fun actionIntent(context: Context, action: String, ids: LongArray?): PendingIntent {
        val intent = Intent(context, ReminderActionReceiver::class.java)
            .setAction(action)
        if (ids != null) intent.putExtra(EXTRA_IDS, ids)
        return PendingIntent.getBroadcast(
            context, action.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    /** 弹到点提醒通知（多条任务合并成一条），返回是否成功弹出 */
    fun fire(context: Context, due: List<Task>): Boolean {
        if (due.isEmpty()) return false
        val lang = com.wang.desktopcalendar.data.SettingsStore(context).language
        val lines = due.map { "${it.taskDate.toString().substring(5)} ${it.remindTime}　${it.title}" }
        return fireText(context, com.wang.desktopcalendar.ui.I18n.t(lang, "toast_title"), lines,
            allowDone = true, doneIds = due.map { it.id }.toLongArray())
    }

    /** 提前提醒通知：标题「即将开始」，行尾带剩余提前量，无「全部完成」按钮 */
    fun fireEarly(context: Context, items: List<Pair<Task, Int>>): Boolean {
        if (items.isEmpty()) return false
        val lang = com.wang.desktopcalendar.data.SettingsStore(context).language
        val lines = items.map { (t, n) ->
            "${t.remindTime}　${t.title}　（${com.wang.desktopcalendar.ui.I18n.t(lang, "early_in", "n" to com.wang.desktopcalendar.ui.I18n.humanSpan(lang, n))}）"
        }
        return fireText(context, com.wang.desktopcalendar.ui.I18n.t(lang, "toast_early"), lines, allowDone = false)
    }

    /** 事件祝贺通知（生日/纪念日/倒数日到点，与桌面版 v1.6.0 一致） */
    fun fireEvents(context: Context, lines: List<String>): Boolean {
        if (lines.isEmpty()) return false
        val lang = com.wang.desktopcalendar.data.SettingsStore(context).language
        return fireText(context, com.wang.desktopcalendar.ui.I18n.t(lang, "toast_event"), lines, allowDone = false)
    }

    private fun fireText(
        context: Context, notifTitle: String, lines: List<String>,
        allowDone: Boolean, doneIds: LongArray? = null,
    ): Boolean {
        if (lines.isEmpty() || !canNotify(context)) return false
        ensureChannel(context)
        val titleDone = com.wang.desktopcalendar.ui.I18n.t(
            com.wang.desktopcalendar.data.SettingsStore(context).language, "toast_all_done")
        val titleGot = com.wang.desktopcalendar.ui.I18n.t(
            com.wang.desktopcalendar.data.SettingsStore(context).language, "toast_got")
        val text = lines.joinToString("\n")
        val contentIntent = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_reminder)
            .setContentTitle(notifTitle)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(contentIntent)
        if (allowDone && doneIds != null) {
            builder.addAction(0, titleDone, actionIntent(context, ACTION_MARK_DONE, doneIds))
        }
        builder.addAction(0, titleGot, actionIntent(context, ACTION_DISMISS, null))
        val notif: Notification = builder.build()
        return try {
            NotificationManagerCompat.from(context).notify(NOTIF_ID, notif)
            true
        } catch (_: SecurityException) {
            false
        }
    }

    fun cancel(context: Context) {
        NotificationManagerCompat.from(context).cancel(NOTIF_ID)
    }
}
