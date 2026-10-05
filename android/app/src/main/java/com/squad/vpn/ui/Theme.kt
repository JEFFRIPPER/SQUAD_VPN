package com.squad.vpn.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.squad.vpn.ui.glass.GlassColors
import com.squad.vpn.ui.glass.GlassEasing
import com.squad.vpn.ui.glass.GlassSpring

// Short names for the brand ramp; the values live in the Glass MD3 tokens.
object Sq {
    val c1 = GlassColors.red
    val c2 = GlassColors.red2
    val c3 = GlassColors.red3
    val c4 = GlassColors.red4
    val c5 = GlassColors.red5
    val c6 = GlassColors.red6
    val c7 = GlassColors.red7
    val c8 = GlassColors.red8
    val c9 = GlassColors.black
    val onSurface = GlassColors.onGlass
    val onSurfaceVariant = GlassColors.onGlassVariant
    val good = GlassColors.good
    val warn = GlassColors.warn
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
    error = GlassColors.bad,
    errorContainer = Sq.c8,
    onErrorContainer = Color(0xFFFF8A93),
    inverseSurface = Sq.onSurface,
    inverseOnSurface = Sq.c8,
    inversePrimary = Sq.c1,
    scrim = Color(0xB3000000),
)

/** MD3 motion under the short name the screens use; the values are the Glass MD3 tokens. */
object Motion {
    val emphasized = GlassEasing.standard
    val emphasizedDecelerate = GlassEasing.emphasizedDecelerate
    fun <T> bouncy() = GlassSpring.bouncy<T>()
    fun <T> gentle() = GlassSpring.spatial<T>()
    fun <T> snappy() = GlassSpring.press<T>()
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
