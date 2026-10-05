package com.squad.vpn.ui.glass

import android.os.Build
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlurEffect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** How much glass a surface is: tint strength, blur and shadow per level of the hierarchy. */
enum class GlassLevel(val tint: Float, val blur: Dp, val elevation: Dp) {
    /** List rows and other main content: translucent tonal surface, no blur. */
    Flat(GlassOpacity.tintRaised, 0.dp, GlassElevation.level0),

    /** Cards floating over the backdrop. */
    Card(GlassOpacity.tintCard, GlassBlur.medium, GlassElevation.level1),

    /** Raised controls: buttons, segmented tracks, snackbars. */
    Raised(GlassOpacity.tintRaised, GlassBlur.soft, GlassElevation.level2),

    /** Navigation and app bars. */
    Bar(GlassOpacity.tintBar, GlassBlur.strong, GlassElevation.level2),

    /** Sheets and dialogs. */
    Sheet(GlassOpacity.tintSheet, GlassBlur.strong, GlassElevation.level3),
}

/**
 * The glass material: the backdrop behind the surface, blurred (Android 12+;
 * older phones get the soft unblurred light, which is already diffuse), a dark
 * tint for contrast, a faint sheen, an inner highlight from the top edge and a
 * hairline border that is brighter on top, as if lit from above.
 *
 * [visibility] fades the whole material in and out (the top bar appears as
 * content scrolls under it); [accent] tints it with the brand colour
 * (selected); [stateLayer] is the MD3 hover/pressed overlay.
 */
@Composable
fun GlassSurface(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(GlassRadius.lg),
    level: GlassLevel = GlassLevel.Card,
    visibility: Float = 1f,
    accent: Float = 0f,
    stateLayer: Float = 0f,
    inner: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val backdrop = LocalBackdrop.current
    // Read only while drawing, so moving the surface redraws it without recomposing.
    val origin = remember { mutableStateOf(Offset.Zero) }
    val border = Brush.verticalGradient(
        listOf(
            lerp(Color.White.copy(alpha = GlassOpacity.borderTop * visibility), GlassColors.accentTint.copy(alpha = GlassOpacity.accentBorder), accent),
            lerp(Color.White.copy(alpha = GlassOpacity.borderBottom * visibility), GlassColors.accentTint.copy(alpha = GlassOpacity.accentBorder * 0.4f), accent),
        ),
    )
    Box(
        modifier
            .shadow(level.elevation * visibility, shape, clip = false)
            .onGloballyPositioned { origin.value = it.positionInRoot() }
            .clip(shape)
            .then(inner),
    ) {
        Box(
            Modifier
                .matchParentSize()
                .graphicsLayer {
                    val radius = level.blur.toPx() * visibility
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && radius >= 1f) {
                        renderEffect = BlurEffect(radius, radius, TileMode.Clamp)
                    }
                }
                .drawBehind { drawAmbient(backdrop, origin.value) },
        )
        Box(
            Modifier
                .matchParentSize()
                .drawBehind {
                    drawRect(GlassColors.glassTint.copy(alpha = level.tint * visibility))
                    drawRect(GlassColors.glassSheen.copy(alpha = GlassOpacity.sheen * visibility))
                    if (accent > 0f) drawRect(GlassColors.accentTint.copy(alpha = GlassOpacity.accentFill * accent))
                    if (stateLayer > 0f) drawRect(GlassColors.onGlass.copy(alpha = stateLayer))
                    drawRect(
                        Brush.verticalGradient(
                            0f to Color.White.copy(alpha = GlassOpacity.highlight * visibility),
                            0.4f to Color.Transparent,
                        ),
                    )
                }
                .border(GlassSize.border, border, shape),
        )
        CompositionLocalProvider(LocalContentColor provides GlassColors.onGlass) {
            content()
        }
    }
}

/** Animated values of the MD3 interaction states of one component. */
@Immutable
data class GlassStates(
    val scale: Float,
    val lift: Dp,
    val stateLayer: Float,
    val focus: Float,
    val selected: Float,
    val alpha: Float,
)

/** default / hover / pressed / focused / selected / disabled, as springs. */
@Composable
fun rememberGlassStates(interaction: MutableInteractionSource, enabled: Boolean, selected: Boolean): GlassStates {
    val hovered by interaction.collectIsHoveredAsState()
    val pressed by interaction.collectIsPressedAsState()
    val focused by interaction.collectIsFocusedAsState()
    val active = enabled
    val scale by animateFloatAsState(
        when {
            active && pressed -> GlassScale.pressed
            active && hovered -> GlassScale.hovered
            else -> 1f
        },
        GlassSpring.press(),
        label = "scale",
    )
    val lift by animateFloatAsState(if (active && hovered && !pressed) 1f else 0f, GlassSpring.press(), label = "lift")
    val layer by animateFloatAsState(
        when {
            !active -> 0f
            pressed -> GlassOpacity.pressed
            focused -> GlassOpacity.focus
            hovered -> GlassOpacity.hover
            else -> 0f
        },
        tween(GlassDuration.short, easing = GlassEasing.standard),
        label = "layer",
    )
    val focus by animateFloatAsState(if (active && focused) 1f else 0f, GlassSpring.effects(), label = "focus")
    val sel by animateFloatAsState(if (selected) 1f else 0f, GlassSpring.effects(), label = "selected")
    val alpha by animateFloatAsState(if (enabled) 1f else GlassOpacity.disabled, tween(GlassDuration.medium), label = "alpha")
    return GlassStates(scale, GlassElevation.hoverLift * lift, layer, focus, sel, alpha)
}

/** Lift, press scale, disabled alpha and the focus ring (drawn outside the shape). */
fun Modifier.glassStates(states: GlassStates, cornerRadius: Dp): Modifier =
    this
        .graphicsLayer {
            scaleX = states.scale
            scaleY = states.scale
            translationY = -states.lift.toPx()
        }
        .alpha(states.alpha)
        .drawWithContent {
            drawContent()
            if (states.focus > 0f) {
                val gap = 3.dp.toPx()
                drawRoundRect(
                    color = GlassColors.focusRing.copy(alpha = states.focus),
                    topLeft = Offset(-gap, -gap),
                    size = Size(size.width + gap * 2, size.height + gap * 2),
                    cornerRadius = CornerRadius(cornerRadius.toPx() + gap),
                    style = Stroke(GlassSize.focusRing.toPx()),
                )
            }
        }

/**
 * A glass card. With [onClick] it is interactive and shows every state:
 * hover lifts it, a press shrinks it, focus draws a ring, selection tints it
 * with the brand colour, disabled dims it.
 */
@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    selected: Boolean = false,
    enabled: Boolean = true,
    radius: Dp = GlassRadius.lg,
    level: GlassLevel = GlassLevel.Card,
    contentPadding: PaddingValues = PaddingValues(GlassSpacing.md),
    role: Role = Role.Button,
    content: @Composable ColumnScope.() -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val states = rememberGlassStates(interaction, enabled, selected)
    GlassSurface(
        modifier = modifier.glassStates(states, radius),
        shape = RoundedCornerShape(radius),
        level = level,
        accent = states.selected,
        stateLayer = states.stateLayer,
        inner = if (onClick != null) {
            Modifier.clickable(
                interactionSource = interaction,
                indication = ripple(color = GlassColors.onGlass),
                enabled = enabled,
                role = role,
                onClick = onClick,
            )
        } else {
            Modifier
        },
    ) {
        Column(Modifier.padding(contentPadding), content = content)
    }
}
