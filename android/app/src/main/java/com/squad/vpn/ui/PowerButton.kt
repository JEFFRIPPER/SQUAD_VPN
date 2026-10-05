package com.squad.vpn.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import com.squad.vpn.core.Status
import kotlinx.coroutines.launch
import kotlin.math.sqrt

/**
 * The big connect button, as on the Windows panel: a circle that morphs into
 * a rounded square when connected (bouncy spring), waves rippling out while
 * connected, a spinning arc while connecting, a springy press, and it can be
 * tugged around — it springs back when let go.
 */
@Composable
fun PowerButton(status: Status, onClick: () -> Unit, modifier: Modifier = Modifier, size: Dp = 176.dp) {
    val connected = status == Status.Connected
    val busy = status == Status.Connecting || status == Status.Disconnecting
    val failed = status == Status.Failed
    val haptics = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()

    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val pressScale by animateFloatAsState(if (pressed) 0.9f else 1f, Motion.bouncy(), label = "press")
    val corner by animateFloatAsState(if (connected) 30f else 50f, Motion.bouncy(), label = "corner")
    val iconTurn by animateFloatAsState(if (connected) 360f else 0f, Motion.bouncy(), label = "turn")
    val iconScale by animateFloatAsState(
        when {
            busy -> 0.85f
            connected -> 1.06f
            else -> 1f
        },
        Motion.bouncy(),
        label = "iconScale",
    )
    val fill by animateColorAsState(
        when {
            connected -> Sq.c1
            busy -> Sq.c5
            failed -> Sq.c8
            else -> Sq.c7
        },
        tween(400, easing = Motion.emphasized),
        label = "fill",
    )
    val tint by animateColorAsState(
        when {
            connected -> Color.White
            busy -> Color(0xFFFFE3E3)
            failed -> Color(0xFFFF8A93)
            else -> Sq.onSurfaceVariant
        },
        tween(300),
        label = "tint",
    )
    val glow by animateFloatAsState(if (connected) 1f else 0f, tween(500, easing = Motion.emphasized), label = "glow")

    val loop = rememberInfiniteTransition(label = "loop")
    val wave by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2600, easing = Motion.emphasizedDecelerate)), label = "wave")
    val spin by loop.animateFloat(0f, 360f, infiniteRepeatable(tween(1000, easing = LinearEasing)), label = "spin")
    val pulse by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(1200), RepeatMode.Reverse), label = "pulse")

    // Rubber-band drag: offset follows the finger with resistance and springs home.
    val offsetX = remember { Animatable(0f) }
    val offsetY = remember { Animatable(0f) }

    val buttonSize = size
    Box(modifier.size(buttonSize * 1.8f), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(buttonSize * 1.8f)) {
            val side = buttonSize.toPx()
            val center = Offset(this.size.width / 2 + offsetX.value, this.size.height / 2 + offsetY.value)
            if (glow > 0f) {
                drawCircle(
                    Brush.radialGradient(
                        listOf(Sq.c1.copy(alpha = 0.55f * glow), Color.Transparent),
                        center = center,
                        radius = side * 0.95f,
                    ),
                    radius = side * 0.95f,
                    center = center,
                )
                // Two ripples, half a period apart, like the panel's ::before/::after.
                for (phase in listOf(wave, (wave + 0.5f) % 1f)) {
                    val scale = 1f + 0.65f * phase
                    val s = side * scale
                    drawRoundRect(
                        color = Sq.c1.copy(alpha = 0.7f * (1f - phase) * glow),
                        topLeft = Offset(center.x - s / 2, center.y - s / 2),
                        size = Size(s, s),
                        cornerRadius = CornerRadius(s * corner / 100f),
                        style = Stroke(width = 2.dp.toPx()),
                    )
                }
            }
            if (busy) {
                val s = side + 20.dp.toPx() + 8.dp.toPx() * pulse
                rotate(spin, center) {
                    drawArc(
                        brush = Brush.sweepGradient(
                            0f to Color.Transparent,
                            0.55f to Color.Transparent,
                            0.9f to Sq.c1,
                            1f to Color.Transparent,
                            center = center,
                        ),
                        startAngle = 0f,
                        sweepAngle = 360f,
                        useCenter = false,
                        topLeft = Offset(center.x - s / 2, center.y - s / 2),
                        size = Size(s, s),
                        style = Stroke(width = 4.dp.toPx()),
                    )
                }
            }
        }

        val shape = RoundedCornerShape(percent = corner.toInt())
        Box(
            Modifier
                .graphicsLayer {
                    translationX = offsetX.value
                    translationY = offsetY.value
                    scaleX = pressScale
                    scaleY = pressScale
                }
                .size(size)
                .drawBehind {
                    if (failed) {
                        drawRoundRect(
                            color = Sq.c1,
                            cornerRadius = CornerRadius(this.size.minDimension * corner / 100f),
                            style = Stroke(width = 2.dp.toPx()),
                        )
                    }
                }
                .clip(shape)
                .background(fill)
                .pointerInput(Unit) {
                    detectDragGestures(
                        onDragEnd = {
                            scope.launch { offsetX.animateTo(0f, Motion.bouncy()) }
                            scope.launch { offsetY.animateTo(0f, Motion.bouncy()) }
                        },
                        onDragCancel = {
                            scope.launch { offsetX.animateTo(0f, Motion.bouncy()) }
                            scope.launch { offsetY.animateTo(0f, Motion.bouncy()) }
                        },
                    ) { change, drag ->
                        change.consume()
                        val distance = sqrt(offsetX.value * offsetX.value + offsetY.value * offsetY.value)
                        val resistance = 1f / (1f + distance / 60f)
                        scope.launch { offsetX.snapTo(offsetX.value + drag.x * resistance) }
                        scope.launch { offsetY.snapTo(offsetY.value + drag.y * resistance) }
                    }
                }
                .clickable(interactionSource = interaction, indication = null, enabled = status != Status.Disconnecting) {
                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    onClick()
                }
                .semantics { contentDescription = if (connected) "Отключиться" else "Подключиться" },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Rounded.PowerSettingsNew,
                contentDescription = null,
                tint = tint,
                modifier = Modifier
                    .size(size * 0.42f)
                    .graphicsLayer {
                        rotationZ = iconTurn
                        scaleX = iconScale
                        scaleY = iconScale
                    },
            )
        }
    }
}
