package io.github.nouxel00.grabdrop.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.nouxel00.grabdrop.Animation
import io.github.nouxel00.grabdrop.ui.theme.GdIcons
import io.github.nouxel00.grabdrop.ui.theme.GrabDropTheme
import kotlinx.coroutines.launch

/** Une animation à jouer, avec un numéro pour rejouer deux fois la même. */
data class PlayingAnimation(val id: Long, val animation: Animation)

/**
 * Animations plein écran :
 * - GRAB : la carte de l'objet rétrécit et descend vers « la main » ;
 * - DROP : l'objet reçu tombe du haut avec un rebond, puis s'efface ;
 * - envoyé : l'objet s'envole vers le haut (vers le PC).
 */
@Composable
fun AnimationOverlay(playing: PlayingAnimation?, onFinished: () -> Unit) {
    if (playing == null) return
    val density = LocalDensity.current
    val scale = remember(playing.id) { Animatable(1f) }
    val offsetY = remember(playing.id) { Animatable(0f) }
    val alpha = remember(playing.id) { Animatable(0f) }
    val far = with(density) { 520.dp.toPx() }

    LaunchedEffect(playing.id) {
        when (playing.animation) {
            is Animation.Grabbed -> {
                alpha.snapTo(1f); scale.snapTo(1.05f)
                scale.animateTo(1f, tween(120))
                launch { scale.animateTo(0.15f, tween(650, easing = FastOutSlowInEasing)) }
                launch { offsetY.animateTo(far * 0.6f, tween(650, easing = FastOutSlowInEasing)) }
                alpha.animateTo(0f, tween(650, easing = LinearEasing))
            }
            is Animation.Dropped -> {
                offsetY.snapTo(-far); scale.snapTo(0.6f)
                launch { alpha.animateTo(1f, tween(200)) }
                launch { scale.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy)) }
                offsetY.animateTo(0f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessLow))
                kotlinx.coroutines.delay(1100)
                alpha.animateTo(0f, tween(300))
            }
            is Animation.Sent -> {
                alpha.snapTo(1f)
                launch { scale.animateTo(0.4f, tween(700, easing = FastOutSlowInEasing)) }
                launch { offsetY.animateTo(-far, tween(700, easing = FastOutSlowInEasing)) }
                kotlinx.coroutines.delay(350)
                alpha.animateTo(0f, tween(350))
            }
        }
        onFinished()
    }

    val extra = GrabDropTheme.colors
    val scheme = MaterialTheme.colorScheme
    val (icon, accent, title, subtitle) = when (val a = playing.animation) {
        is Animation.Grabbed -> Look(GdIcons.Fist, extra.held, "En main", a.description)
        is Animation.Dropped -> Look(GdIcons.Receive, scheme.primary, "Reçu de ${a.received.from}", a.received.description)
        is Animation.Sent -> Look(GdIcons.Check, extra.success, "Déposé sur le PC", a.description)
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Surface(
            modifier = Modifier
                .widthIn(max = 300.dp)
                .graphicsLayer {
                    scaleX = scale.value; scaleY = scale.value
                    translationY = offsetY.value
                    this.alpha = alpha.value
                },
            shape = RoundedCornerShape(28.dp),
            color = scheme.surfaceContainerHigh,
            shadowElevation = 16.dp,
        ) {
            Column(
                Modifier.padding(horizontal = 32.dp, vertical = 26.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(
                    Modifier.size(72.dp).clip(CircleShape).background(accent.copy(alpha = 0.16f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(icon, null, tint = accent, modifier = Modifier.size(38.dp))
                }
                Spacer(Modifier.height(4.dp))
                Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
                Text(subtitle, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center,
                     color = scheme.onSurfaceVariant)
            }
        }
    }
}

private data class Look(val icon: ImageVector, val accent: Color, val title: String, val subtitle: String)
