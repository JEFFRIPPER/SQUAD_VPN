package com.squad.vpn.ui

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// SQUAD palette, the same as the Windows panel: #d00018 … #000000.
object Sq {
    val c1 = Color(0xFFD00018)
    val c2 = Color(0xFFB60015)
    val c3 = Color(0xFF9C0012)
    val c4 = Color(0xFF82000F)
    val c5 = Color(0xFF68000C)
    val c6 = Color(0xFF4E0009)
    val c7 = Color(0xFF330006)
    val c8 = Color(0xFF190003)
    val c9 = Color(0xFF000000)
    val onSurface = Color(0xFFF6EAEA)
    val onSurfaceVariant = Color(0xFFC7A5A5)
    val good = Color(0xFF7BD88F)
    val warn = Color(0xFFFFB86B)
}

private val colors = darkColorScheme(
    primary = Sq.c1,
    onPrimary = Color.White,
    primaryContainer = Sq.c5,
    onPrimaryContainer = Color(0xFFFFE3E3),
    secondary = Sq.c2,
    onSecondary = Color.White,
    secondaryContainer = Sq.c6,
    onSecondaryContainer = Color(0xFFFFE3E3),
    tertiary = Sq.c3,
    tertiaryContainer = Sq.c7,
    onTertiaryContainer = Color(0xFFFFB8B8),
    background = Sq.c9,
    onBackground = Sq.onSurface,
    surface = Sq.c9,
    onSurface = Sq.onSurface,
    surfaceVariant = Sq.c7,
    onSurfaceVariant = Sq.onSurfaceVariant,
    surfaceContainerLowest = Sq.c9,
    surfaceContainerLow = Sq.c8,
    surfaceContainer = Sq.c8,
    surfaceContainerHigh = Sq.c7,
    surfaceContainerHighest = Sq.c7,
    surfaceBright = Sq.c6,
    outline = Sq.c3,
    outlineVariant = Sq.c6,
    error = Color(0xFFFF4D5B),
    errorContainer = Sq.c8,
    onErrorContainer = Color(0xFFFF8A93),
    inverseSurface = Sq.onSurface,
    inverseOnSurface = Sq.c8,
    inversePrimary = Sq.c1,
    scrim = Color(0xB3000000),
)

/** MD3 motion: emphasized easing and springs (the panel's --md-spring*). */
object Motion {
    val emphasized = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    val emphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
    fun <T> bouncy() = spring<T>(dampingRatio = 0.45f, stiffness = Spring.StiffnessMediumLow)
    fun <T> gentle() = spring<T>(dampingRatio = 0.8f, stiffness = Spring.StiffnessMediumLow)
    fun <T> snappy() = spring<T>(dampingRatio = 0.6f, stiffness = Spring.StiffnessMedium)
}

private val base = Typography()
private val typography = base.copy(
    displaySmall = base.displaySmall.copy(fontWeight = FontWeight.Medium),
    headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.Medium),
    labelMedium = base.labelMedium.copy(letterSpacing = 0.6.sp),
)

val numberStyle = TextStyle(fontWeight = FontWeight.Medium, fontSize = 28.sp, lineHeight = 36.sp)

@Composable
fun SquadTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, typography = typography, content = content)
}
