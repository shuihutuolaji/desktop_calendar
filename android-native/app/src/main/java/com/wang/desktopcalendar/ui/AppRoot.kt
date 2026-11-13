package com.wang.desktopcalendar.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Calculate
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.FormatListBulleted
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 应用根：主题色联动设置、四个界面、底部导航 */
@Composable
fun AppRoot(state: AppState) {
    val accentColor = parseHex(state.accent, Color(0xFF2563EB))
    val bgColor = parseHex(state.bgColor, Color(0xFFF0F0F0))

    val scheme = MaterialTheme.colorScheme.copy(
        primary = accentColor,
        onPrimary = Color.White,
        background = bgColor,
        onBackground = parseHex(state.calFg, Color(0xFF1F2937)),
        surface = bgColor,
        onSurface = Color(0xFF1F2937),
        secondary = accentColor,
    )

    BackHandler(enabled = state.screen == Screen.SETTINGS) { state.screen = Screen.CALENDAR }

    ProvideAppState(state) {
        MaterialTheme(colorScheme = scheme) {
            Surface(Modifier.fillMaxSize(), color = bgColor) {
                Column(
                    Modifier
                        .fillMaxSize()
                        .background(bgColor)
                        .imePadding()
                ) {
                    Box(Modifier.weight(1f)) {
                        when (state.screen) {
                            Screen.CALENDAR -> CalendarTab(state)
                            Screen.LIST -> ListTab(state)
                            Screen.CALC -> CalcTab(state)
                            Screen.SETTINGS -> SettingsTab(state)
                        }
                    }
                    if (state.screen != Screen.SETTINGS) {
                        val items: List<Triple<Screen, String, ImageVector>> = listOf(
                            Triple(Screen.CALENDAR, T("tab_cal"), Icons.Filled.CalendarMonth),
                            Triple(Screen.LIST, T("tab_list"), Icons.Filled.FormatListBulleted),
                            Triple(Screen.CALC, T("tab_calc"), Icons.Filled.Calculate),
                        )
                        NavigationBar(containerColor = bgColor, tonalElevation = 0.dp) {
                            for ((scr, label, icon) in items) {
                                NavigationBarItem(
                                    selected = state.screen == scr,
                                    onClick = { state.screen = scr },
                                    icon = { Icon(icon, contentDescription = label) },
                                    label = { Text(label, fontSize = 11.sp) },
                                    colors = NavigationBarItemDefaults.colors(
                                        selectedIconColor = accentColor,
                                        selectedTextColor = accentColor,
                                        indicatorColor = mixHex(state.accent, 0.75f),
                                    ),
                                )
                            }
                        }
                    }
                }
                // 全局对话框：任务编辑 / 推送今日待办
                state.editingTask?.let { task ->
                    EditTaskDialog(state, task) { state.editingTask = null }
                }
                if (state.showPushToday) {
                    PushTodayDialog(state) { state.showPushToday = false }
                }
            }
        }
    }
}
