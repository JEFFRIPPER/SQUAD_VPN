package com.squad.vpn.ui.glass

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/** Dims everything below an overlay; a tap on it dismisses. Must be called inside the root Box. */
@Composable
private fun BoxScope.Scrim(visible: Boolean, onDismiss: () -> Unit) {
    AnimatedVisibility(
        visible = visible,
        modifier = Modifier.matchParentSize(),
        enter = fadeIn(tween(GlassDuration.medium, easing = GlassEasing.standard)),
        exit = fadeOut(tween(GlassDuration.short, easing = GlassEasing.standard)),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(GlassColors.scrim.copy(alpha = GlassOpacity.scrim))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onDismiss),
        )
    }
}

/**
 * Bottom sheet of glass. Rises on a spring from the bottom edge, can be
 * dragged down to close (it follows the finger and springs back if let go
 * early), and closes with the back gesture.
 */
@Composable
fun BoxScope.GlassSheet(
    visible: Boolean,
    onDismiss: () -> Unit,
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    BackHandler(enabled = visible, onBack = onDismiss)
    Scrim(visible, onDismiss)
    val scope = rememberCoroutineScope()
    val drag = remember { Animatable(0f) }
    val closeAt = with(LocalDensity.current) { 120.dp.toPx() }
    LaunchedEffect(visible) { if (visible) drag.snapTo(0f) }
    AnimatedVisibility(
        visible = visible,
        modifier = Modifier.align(Alignment.BottomCenter),
        enter = slideInVertically(GlassSpring.spatial()) { it } + fadeIn(tween(GlassDuration.medium)),
        exit = slideOutVertically(tween(GlassDuration.medium, easing = GlassEasing.emphasizedAccelerate)) { it } +
            fadeOut(tween(GlassDuration.medium)),
    ) {
        GlassSurface(
            modifier = Modifier
                .fillMaxWidth()
                .offset { IntOffset(0, drag.value.roundToInt()) }
                .draggable(
                    orientation = Orientation.Vertical,
                    state = rememberDraggableState { delta ->
                        scope.launch { drag.snapTo((drag.value + delta).coerceAtLeast(0f)) }
                    },
                    onDragStopped = { velocity ->
                        if (drag.value > closeAt || velocity > 1800f) onDismiss()
                        else drag.animateTo(0f, GlassSpring.spatial())
                    },
                ),
            shape = RoundedCornerShape(topStart = GlassRadius.xxl, topEnd = GlassRadius.xxl),
            level = GlassLevel.Sheet,
        ) {
            Column(
                Modifier
                    .windowInsetsPadding(WindowInsets.navigationBars)
                    .padding(horizontal = GlassSpacing.lg)
                    .padding(bottom = GlassSpacing.lg),
            ) {
                // Drag handle.
                Box(
                    Modifier
                        .align(Alignment.CenterHorizontally)
                        .padding(vertical = GlassSpacing.sm)
                        .size(width = 32.dp, height = 4.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(GlassColors.onGlassVariant.copy(alpha = 0.5f)),
                )
                Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(bottom = GlassSpacing.sm))
                content()
            }
        }
    }
}

/** MD3 dialog of glass: grows in from slightly smaller on a spring, never pops. */
@Composable
fun BoxScope.GlassDialog(
    visible: Boolean,
    title: String,
    text: String,
    confirmText: String,
    onConfirm: () -> Unit,
    dismissText: String,
    onDismiss: () -> Unit,
) {
    BackHandler(enabled = visible, onBack = onDismiss)
    Scrim(visible, onDismiss)
    AnimatedVisibility(
        visible = visible,
        modifier = Modifier
            .align(Alignment.Center)
            .padding(GlassSpacing.lg),
        enter = scaleIn(GlassSpring.spatial(), initialScale = GlassScale.enter) + fadeIn(tween(GlassDuration.medium)),
        exit = scaleOut(tween(GlassDuration.short), targetScale = GlassScale.enter) + fadeOut(tween(GlassDuration.short)),
    ) {
        GlassSurface(
            modifier = Modifier.widthIn(max = 420.dp),
            shape = RoundedCornerShape(GlassRadius.xl),
            level = GlassLevel.Sheet,
        ) {
            Column(Modifier.padding(GlassSpacing.lg)) {
                Text(title, style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(GlassSpacing.md))
                Text(text, style = MaterialTheme.typography.bodyMedium, color = GlassColors.onGlassVariant)
                Spacer(Modifier.height(GlassSpacing.lg))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(GlassSpacing.xs, Alignment.End)) {
                    GlassButton(dismissText, onDismiss)
                    GlassButton(confirmText, onConfirm, style = GlassButtonStyle.Filled)
                }
            }
        }
    }
}

/** Snackbars as small glass panels. */
@Composable
fun GlassSnackbarHost(state: SnackbarHostState, modifier: Modifier = Modifier) {
    SnackbarHost(state, modifier) { data ->
        GlassSurface(
            modifier = Modifier
                .padding(horizontal = GlassSpacing.md)
                .fillMaxWidth(),
            shape = RoundedCornerShape(GlassRadius.md),
            level = GlassLevel.Sheet,
        ) {
            Text(
                data.visuals.message,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(GlassSpacing.md),
            )
        }
    }
}
