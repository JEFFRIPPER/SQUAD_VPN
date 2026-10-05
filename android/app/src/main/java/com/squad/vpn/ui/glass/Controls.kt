package com.squad.vpn.ui.glass

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

enum class GlassButtonStyle { Filled, Tonal }

/** MD3 button: Filled is the brand colour with a glass sheen, Tonal is a glass pill. */
@Composable
fun GlassButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    style: GlassButtonStyle = GlassButtonStyle.Tonal,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val interaction = remember { MutableInteractionSource() }
    val states = rememberGlassStates(interaction, enabled, selected = false)
    val height = GlassSize.minTouch
    val shape = RoundedCornerShape(height / 2)
    val click = Modifier.clickable(
        interactionSource = interaction,
        indication = ripple(color = GlassColors.onGlass),
        enabled = enabled && !loading,
        role = Role.Button,
        onClick = onClick,
    )
    val label: @Composable () -> Unit = {
        Row(
            Modifier
                .height(height)
                .padding(horizontal = GlassSpacing.lg),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            if (loading) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = LocalContentColor.current)
                Spacer(Modifier.width(GlassSpacing.xs))
            } else if (icon != null) {
                Icon(icon, null, Modifier.size(18.dp))
                Spacer(Modifier.width(GlassSpacing.xs))
            }
            Text(text, style = MaterialTheme.typography.labelLarge, maxLines = 1)
        }
    }
    when (style) {
        GlassButtonStyle.Tonal -> GlassSurface(
            modifier = modifier.glassStates(states, height / 2),
            shape = shape,
            level = GlassLevel.Raised,
            stateLayer = states.stateLayer,
            inner = click,
        ) { label() }

        GlassButtonStyle.Filled -> Box(
            modifier
                .glassStates(states, height / 2)
                .clip(shape)
                .background(Brush.verticalGradient(listOf(GlassColors.red, GlassColors.red3)))
                .drawBehind {
                    drawRect(
                        Brush.verticalGradient(
                            0f to Color.White.copy(alpha = GlassOpacity.highlight * 2),
                            0.5f to Color.Transparent,
                        ),
                    )
                    if (states.stateLayer > 0f) drawRect(GlassColors.onAccent.copy(alpha = states.stateLayer))
                }
                .border(GlassSize.border, Color.White.copy(alpha = GlassOpacity.borderTop), shape)
                .then(click),
        ) {
            CompositionLocalProvider(LocalContentColor provides GlassColors.onAccent) { label() }
        }
    }
}

/** A filter chip: glass pill that takes the brand tint when on. */
@Composable
fun GlassChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
) {
    val interaction = remember { MutableInteractionSource() }
    val states = rememberGlassStates(interaction, enabled = true, selected = selected)
    val height = 36.dp
    GlassSurface(
        modifier = modifier
            .glassStates(states, GlassRadius.sm)
            .semantics { this.selected = selected },
        shape = RoundedCornerShape(GlassRadius.sm),
        level = GlassLevel.Raised,
        accent = states.selected,
        stateLayer = states.stateLayer,
        inner = Modifier.clickable(
            interactionSource = interaction,
            indication = ripple(color = GlassColors.onGlass),
            role = Role.Checkbox,
            onClick = onClick,
        ),
    ) {
        Row(
            Modifier
                .height(height)
                .padding(horizontal = GlassSpacing.sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Icon(icon, null, Modifier.size(18.dp))
                Spacer(Modifier.width(GlassSpacing.xs))
            }
            Text(text, style = MaterialTheme.typography.labelLarge)
        }
    }
}

/**
 * Segmented choice: one glass track, and a tinted indicator that slides to
 * the chosen segment on a spring (the same moving piece, not a cross-fade).
 * [selected] = -1 shows no indicator.
 */
@Composable
fun GlassSegmented(
    options: List<String>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val height = GlassSize.minTouch
    GlassSurface(
        modifier = modifier
            .fillMaxWidth()
            .height(height),
        shape = RoundedCornerShape(height / 2),
        level = GlassLevel.Raised,
    ) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val itemWidth = maxWidth / options.size
            Indicator(index = selected, itemWidth = itemWidth, radius = height / 2, inset = GlassSpacing.xxs)
            Row(Modifier.fillMaxSize()) {
                options.forEachIndexed { i, label ->
                    Segment(
                        label = label,
                        selected = i == selected,
                        onClick = { onSelect(i) },
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight(),
                    )
                }
            }
        }
    }
}

@Composable
private fun Segment(label: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val interaction = remember { MutableInteractionSource() }
    val states = rememberGlassStates(interaction, enabled = true, selected = selected)
    Box(
        modifier
            .glassStates(states, GlassRadius.xl)
            .clip(RoundedCornerShape(GlassRadius.xl))
            .clickable(
                interactionSource = interaction,
                indication = ripple(color = GlassColors.onGlass),
                role = Role.Tab,
                onClick = onClick,
            )
            .semantics { this.selected = selected },
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            color = if (selected) GlassColors.onGlass else GlassColors.onGlassVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = GlassSpacing.xs),
        )
    }
}

/** The sliding selection pill shared by the segmented control and the navigation bar. */
@Composable
private fun Indicator(index: Int, itemWidth: Dp, radius: Dp, inset: Dp) {
    val x by animateDpAsState(itemWidth * index.coerceAtLeast(0), GlassSpring.spatial(), label = "indicatorX")
    val shown by animateFloatAsState(if (index >= 0) 1f else 0f, GlassSpring.effects(), label = "indicatorAlpha")
    val shape = RoundedCornerShape(radius - inset)
    Box(
        Modifier
            .offset(x = x)
            .width(itemWidth)
            .fillMaxHeight()
            .padding(inset)
            .graphicsLayer {
                alpha = shown
                val s = 0.9f + 0.1f * shown
                scaleX = s
                scaleY = s
            }
            .clip(shape)
            .background(GlassColors.accentTint.copy(alpha = GlassOpacity.accentFill + 0.06f))
            .border(GlassSize.border, GlassColors.accentTint.copy(alpha = GlassOpacity.accentBorder), shape),
    )
}

data class GlassNavItem(val label: String, val icon: ImageVector, val badge: Boolean = false)

/** Floating glass navigation bar with a sliding indicator and a springy icon pop. */
@Composable
fun GlassNavBar(
    items: List<GlassNavItem>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    GlassSurface(
        modifier = modifier
            .windowInsetsPadding(WindowInsets.navigationBars)
            .padding(horizontal = GlassSpacing.md, vertical = GlassSize.navMargin)
            .fillMaxWidth()
            .height(GlassSize.navBar),
        shape = RoundedCornerShape(GlassRadius.xxl),
        level = GlassLevel.Bar,
    ) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val itemWidth = maxWidth / items.size
            Indicator(index = selected, itemWidth = itemWidth, radius = GlassRadius.xxl, inset = GlassSpacing.xs)
            Row(Modifier.fillMaxSize()) {
                items.forEachIndexed { i, item ->
                    NavButton(
                        item = item,
                        selected = i == selected,
                        onClick = { onSelect(i) },
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight(),
                    )
                }
            }
        }
    }
}

@Composable
private fun NavButton(item: GlassNavItem, selected: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val interaction = remember { MutableInteractionSource() }
    val states = rememberGlassStates(interaction, enabled = true, selected = selected)
    val pop by animateFloatAsState(if (selected) 1.12f else 1f, GlassSpring.bouncy(), label = "pop")
    val tint = if (selected) GlassColors.onGlass else GlassColors.onGlassVariant
    Column(
        modifier
            .glassStates(states, GlassRadius.xl)
            .clip(RoundedCornerShape(GlassRadius.xl))
            .clickable(
                interactionSource = interaction,
                indication = ripple(color = GlassColors.onGlass),
                role = Role.Tab,
                onClick = onClick,
            )
            .semantics { this.selected = selected },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box {
            Icon(
                item.icon,
                contentDescription = null,
                tint = tint,
                modifier = Modifier.graphicsLayer {
                    scaleX = pop
                    scaleY = pop
                },
            )
            if (item.badge) {
                Box(
                    Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 3.dp, y = (-2).dp)
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(GlassColors.red),
                )
            }
        }
        Spacer(Modifier.height(GlassSpacing.xxs))
        Text(
            item.label,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            color = tint,
        )
    }
}

/**
 * Top app bar. Transparent over the top of a page; as content scrolls under
 * it the glass fades and blurs in.
 */
@Composable
fun GlassTopBar(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val backdrop = LocalBackdrop.current
    val threshold = with(LocalDensity.current) { GlassSpacing.lg.toPx() }
    val glass by animateFloatAsState((backdrop.scroll / threshold).coerceIn(0f, 1f), GlassSpring.effects(), label = "topBarGlass")
    GlassSurface(
        modifier = modifier.fillMaxWidth(),
        shape = RectangleShape,
        level = GlassLevel.Bar,
        visibility = glass,
    ) {
        Box(
            Modifier
                .windowInsetsPadding(WindowInsets.statusBars)
                .fillMaxWidth()
                .heightIn(min = GlassSize.topBar)
                .padding(horizontal = GlassSpacing.md),
            contentAlignment = Alignment.Center,
        ) {
            content()
        }
    }
}
