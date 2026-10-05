package com.squad.vpn.ui.glass

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.toSize
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * The ambient layer every glass surface sits on: a dark gradient with three
 * soft, slowly drifting brand-coloured light blobs. Glass surfaces redraw the
 * part of it that lies behind them, blurred, so the blur is a real backdrop
 * blur of what the eye sees around the panel.
 */
@Stable
class Backdrop {
    var size by mutableStateOf(Size.Zero)
        internal set

    /** 0..1 position of the slow drift. */
    var phase by mutableFloatStateOf(0f)
        internal set

    /** Scroll of the visible page in px: drives the parallax and the top bar's glass. */
    var scroll by mutableFloatStateOf(0f)
}

val LocalBackdrop = staticCompositionLocalOf { Backdrop() }

@Composable
fun rememberBackdrop(): Backdrop = remember { Backdrop() }

/** How far the light moves for each px of scroll: the backdrop lags behind the content. */
private const val PARALLAX = 0.12f

/** Draws the backdrop as seen from [origin], the top-left of the drawing area in root coordinates. */
fun DrawScope.drawAmbient(backdrop: Backdrop, origin: Offset) {
    val full = backdrop.size
    if (full.width <= 0f || full.height <= 0f) return
    translate(-origin.x, -origin.y) {
        drawRect(
            Brush.verticalGradient(listOf(GlassColors.backdropTop, GlassColors.backdropBottom), startY = 0f, endY = full.height),
            size = full,
        )
        val t = backdrop.phase * 2 * PI
        val shift = -(backdrop.scroll * PARALLAX).coerceAtMost(full.height * 0.25f)
        val w = full.width
        val h = full.height
        blob(GlassColors.blobA, 0.30f, Offset(w * (0.18f + 0.10f * cos(t).toFloat()), h * (0.16f + 0.04f * sin(t).toFloat()) + shift), w * 0.80f)
        blob(GlassColors.blobB, 0.45f, Offset(w * (0.90f - 0.08f * sin(t).toFloat()), h * (0.48f + 0.06f * cos(t).toFloat()) + shift * 1.6f), w * 0.85f)
        blob(GlassColors.blobC, 0.50f, Offset(w * (0.30f + 0.12f * sin(t + 1.3).toFloat()), h * (0.86f - 0.04f * cos(t).toFloat()) + shift * 0.6f), w * 0.90f)
    }
}

private fun DrawScope.blob(color: Color, alpha: Float, center: Offset, radius: Float) {
    drawCircle(
        Brush.radialGradient(listOf(color.copy(alpha = alpha), Color.Transparent), center = center, radius = radius),
        radius = radius,
        center = center,
    )
}

/** Full-screen backdrop; also keeps [backdrop] informed of its size and drift. */
@Composable
fun GlassBackground(backdrop: Backdrop, modifier: Modifier = Modifier) {
    LaunchedEffect(backdrop) {
        val start = System.nanoTime()
        while (true) {
            // withFrameNanos pauses while the app is not on screen.
            withFrameNanos { now ->
                backdrop.phase = (((now - start) / 1_000_000.0 / GlassDuration.ambient) % 1.0).toFloat()
            }
            // The drift is slow: ~20 updates a second are smooth and spare the battery.
            delay(48)
        }
    }
    Canvas(
        modifier
            .fillMaxSize()
            .onSizeChanged { backdrop.size = it.toSize() },
    ) {
        drawAmbient(backdrop, Offset.Zero)
    }
}
