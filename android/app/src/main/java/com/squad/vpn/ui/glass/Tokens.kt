package com.squad.vpn.ui.glass

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.SpringSpec
import androidx.compose.animation.core.spring
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/*
 * Glass MD3 design tokens. Every colour, radius, blur, opacity, elevation,
 * spacing and motion value of the UI comes from here; components never
 * invent their own numbers.
 */

/** Colour roles. The SQUAD palette (#d00018 … #000000) plus the glass layers. */
object GlassColors {
    // Brand ramp, same as the Windows panel.
    val red = Color(0xFFD00018)
    val red2 = Color(0xFFB60015)
    val red3 = Color(0xFF9C0012)
    val red4 = Color(0xFF82000F)
    val red5 = Color(0xFF68000C)
    val red6 = Color(0xFF4E0009)
    val red7 = Color(0xFF330006)
    val red8 = Color(0xFF190003)
    val black = Color(0xFF000000)

    // The ambient backdrop the glass sits on.
    val backdropTop = Color(0xFF140306)
    val backdropBottom = Color(0xFF050102)
    val blobA = Color(0xFFD00018)
    val blobB = Color(0xFF82000F)
    val blobC = Color(0xFF4A0E2A)

    // Glass layers: a dark tint keeps text readable on any backdrop,
    // a faint white sheen gives the "material" its body.
    val glassTint = Color(0xFF0C0204)
    val glassSheen = Color.White
    val accentTint = red

    // Content on glass. Both pass WCAG AA on the darkest and brightest glass.
    val onGlass = Color(0xFFF6EAEA)
    val onGlassVariant = Color(0xFFCFB3B3)
    val onAccent = Color.White

    val focusRing = Color(0xFFFF8A93)
    val scrim = Color.Black
    val good = Color(0xFF7BD88F)
    val warn = Color(0xFFFFB86B)
    val bad = Color(0xFFFF6B76)
}

/** Corner radii (MD3 shape scale, one step rounder for the expressive look). */
object GlassRadius {
    val xs = 8.dp
    val sm = 12.dp
    val md = 16.dp
    val lg = 24.dp
    val xl = 28.dp
    val xxl = 36.dp
}

/** Backdrop blur. Kept moderate: glass, not frosted plastic. */
object GlassBlur {
    val soft = 16.dp
    val medium = 24.dp
    val strong = 32.dp
}

/** Alpha values of the glass layers and state overlays. */
object GlassOpacity {
    // Dark tint under the sheen, per surface level.
    const val tintCard = 0.42f
    const val tintRaised = 0.55f
    const val tintBar = 0.62f
    const val tintSheet = 0.74f
    const val tintSolid = 0.86f

    const val sheen = 0.05f
    const val highlight = 0.10f
    const val borderTop = 0.18f
    const val borderBottom = 0.04f
    const val accentFill = 0.20f
    const val accentBorder = 0.55f

    // MD3 state layers.
    const val hover = 0.06f
    const val focus = 0.10f
    const val pressed = 0.10f
    const val selected = 0.14f
    const val disabled = 0.38f

    const val scrim = 0.48f
}

/** Shadows and lifts. Shadows are faint; depth comes from blur and borders. */
object GlassElevation {
    val level0 = 0.dp
    val level1 = 2.dp
    val level2 = 6.dp
    val level3 = 12.dp
    val hoverLift = 2.dp
}

/** Spacing scale (4 dp grid). */
object GlassSpacing {
    val xxs = 4.dp
    val xs = 8.dp
    val sm = 12.dp
    val md = 16.dp
    val lg = 24.dp
    val xl = 32.dp
}

/** Fixed sizes of the chrome. */
object GlassSize {
    val topBar = 64.dp
    val navBar = 72.dp
    val navMargin = 12.dp
    val focusRing = 2.dp
    val border = 1.dp
    val minTouch = 48.dp
}

/** Scale factors for the interaction states. */
object GlassScale {
    const val pressed = 0.97f
    const val hovered = 1.01f
    const val enter = 0.92f
}

/** Durations (ms), MD3 short/medium/long. */
object GlassDuration {
    const val short = 120
    const val medium = 240
    const val long = 400
    const val extraLong = 600
    const val ambient = 26_000
}

/** MD3 easing curves. */
object GlassEasing {
    val standard = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    val emphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
    val emphasizedAccelerate = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)
}

/** Springs, as in Material Expressive motion: spatial ones may overshoot, effects never do. */
object GlassSpring {
    /** Press and release of anything tappable. */
    fun <T> press(): SpringSpec<T> = spring(dampingRatio = 0.6f, stiffness = Spring.StiffnessMedium)

    /** Panels, indicators, sheets: a soft landing with a hint of overshoot. */
    fun <T> spatial(): SpringSpec<T> = spring(dampingRatio = 0.8f, stiffness = Spring.StiffnessMediumLow)

    /** Playful moves (the power button, cards popping in). */
    fun <T> bouncy(): SpringSpec<T> = spring(dampingRatio = 0.45f, stiffness = Spring.StiffnessMediumLow)

    /** Colour, alpha and blur changes: no overshoot. */
    fun <T> effects(): SpringSpec<T> = spring(dampingRatio = 1f, stiffness = Spring.StiffnessMedium)
}
