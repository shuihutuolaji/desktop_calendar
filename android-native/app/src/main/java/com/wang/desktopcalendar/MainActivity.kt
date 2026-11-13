package com.wang.desktopcalendar

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.wang.desktopcalendar.remind.Notify
import com.wang.desktopcalendar.remind.ReminderScheduler
import com.wang.desktopcalendar.ui.AppRoot
import com.wang.desktopcalendar.ui.AppState

class MainActivity : ComponentActivity() {

    private lateinit var state: AppState

    private val notifPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        state = AppState(applicationContext)

        // 通知权限（Android 13+ 首次运行询问）
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        Notify.ensureChannel(this)

        // 回到前台：跨天顺延 + 重排提醒（与桌面版 _tick / check_reminders 对应）
        Thread { ReminderScheduler.onAppForeground(applicationContext) }.start()

        setContent { AppRoot(state) }
    }

    override fun onResume() {
        super.onResume()
        Thread { ReminderScheduler.onAppForeground(applicationContext) }.start()
        state.onForegroundUi()
    }
}
