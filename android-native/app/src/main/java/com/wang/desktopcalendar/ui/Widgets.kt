package com.wang.desktopcalendar.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 小节标题 */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier = modifier.padding(top = 18.dp, bottom = 6.dp),
        fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onBackground,
    )
}

/** 可选中文字胶囊（自定义实现，避开实验性 SegmentedButton/FilterChip API）。
 * onClick 故意放最后，方便调用方用尾随 lambda。 */
@Composable
fun SelectChip(
    selected: Boolean,
    label: String,
    accent: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Surface(
        modifier = modifier
            .clip(RoundedCornerShape(50))
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(50),
        color = if (selected) accent else Color.White,
        border = BorderStroke(1.dp, if (selected) accent else Color(0xFFD1D5DB)),
    ) {
        Text(
            label,
            Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            color = if (selected) Color.White else Color(0xFF374151),
            fontSize = 13.sp,
        )
    }
}

/** 圆形颜色选择块 */
@Composable
fun ColorSwatch(hex: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .size(32.dp)
            .clip(CircleShape)
            .background(parseHex(hex, Color.Gray))
            .border(
                if (selected) 3.dp else 1.dp,
                if (selected) Color(0xFF111827) else Color(0xFFD1D5DB),
                CircleShape,
            )
            .clickable(onClick = onClick),
    )
}

/** 细分隔线 */
@Composable
fun HLine(color: Color = Palette.GridLine) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(color))
}
