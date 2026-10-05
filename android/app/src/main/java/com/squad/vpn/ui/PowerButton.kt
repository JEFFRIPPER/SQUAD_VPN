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
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
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
import com.squad.vpn.R
import com.squad.vpn.core.Status
import com.squad.vpn.ui.glass.GlassColors
import kotlinx.coroutines.launch
import kotlin.math.sqrt

/**
 * The big connect button: the SQUAD emblem in a circle. While connected the
 * emblem comes alive (a looping video plays inside the circle) and red waves
 * ripple out; while connecting it slowly turns inside a spinning arc. It has
 * a springy press and can be tugged around; it springs back when let go.
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
    val emblemScale by animateFloatAsState(
        when {
            busy -> 0.92f
            connected -> 1.04f
            else -> 1f
        },
        Motion.bouncy(),
        label = "emblemScale",
    )
    // Idle the emblem is a little dimmed, so "on" reads clearly brighter.
    val shade by animateColorAsState(
        when {
            connected -> Color.Transparent
            busy -> Color.Black.copy(alpha = 0.15f)
            failed -> Color.Black.copy(alpha = 0.45f)
            else -> Color.Black.copy(alpha = 0.3f)
        },
        tween(400, easing = Motion.emphasized),
        label = "shade",
    )
    val ring by animateColorAsState(
        when {
            connected -> GlassColors.red
            failed -> Sq.c1
            busy -> GlassColors.red5.copy(alpha = 0.75f)
            else -> GlassColors.red7.copy(alpha = 0.6f)
        },
        tween(400, easing = Motion.emphasized),
        label = "ring",
    )
    val glow by animateFloatAsState(if (connected) 1f else 0f, tween(500, easing = Motion.emphasized), label = "glow")

    val loop = rememberInfiniteTransition(label = "loop")
    val wave by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2600, easing = Motion.emphasizedDecelerate)), label = "wave")
    val spin by loop.animateFloat(0f, 360f, infiniteRepeatable(tween(1000, easing = LinearEasing)), label = "spin")
    val turn by loop.animateFloat(0f, 360f, infiniteRepeatable(tween(6000, easing = LinearEasing)), label = "turn")
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
                    drawCircle(
                        color = Sq.c1.copy(alpha = 0.7f * (1f - phase) * glow),
                        radius = side / 2 * (1f + 0.65f * phase),
                        center = center,
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

        Box(
            Modifier
                .graphicsLayer {
                    translationX = offsetX.value
                    translationY = offsetY.value
                    scaleX = pressScale
                    scaleY = pressScale
                }
                .size(size)
                .clip(CircleShape)
                .background(Color.Black)
                .border(2.dp, ring, CircleShape)
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
        ) {
            Image(
                painterResource(R.drawable.connect_button),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        rotationZ = if (busy) turn else 0f
                        scaleX = emblemScale
                        scaleY = emblemScale
                    },
            )
            // Connected: the emblem comes alive. Until the first frame is
            // decoded the video view is transparent, so the still shows through.
            AnimatedVisibility(
                visible = connected,
                modifier = Modifier.matchParentSize(),
                enter = fadeIn(tween(500, easing = Motion.emphasized)),
                exit = fadeOut(tween(250)),
            ) {
                LoopVideo(R.raw.connected_loop, Modifier.fillMaxSize())
            }
            Box(Modifier.matchParentSize().background(shade))
        }
    }
}
