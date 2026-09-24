package io.github.nouxel00.grabdrop.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.nouxel00.grabdrop.Animation
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

    val (emoji, title, subtitle) = when (val a = playing.animation) {
        is Animation.Grabbed -> Triple("✊", "Attrapé", a.description)
        is Animation.Dropped -> Triple("✋", "Reçu de ${a.received.from}", a.received.description)
        is Animation.Sent -> Triple("🚀", "Déposé sur le PC", a.description)
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Card(
            modifier = Modifier
                .widthIn(max = 300.dp)
                .graphicsLayer {
                    scaleX = scale.value; scaleY = scale.value
                    translationY = offsetY.value
                    this.alpha = alpha.value
                },
            shape = RoundedCornerShape(24.dp),
            elevation = CardDefaults.cardElevation(defaultElevation = 12.dp),
        ) {
            Column(
                Modifier.padding(horizontal = 28.dp, vertical = 22.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(emoji, fontSize = 48.sp)
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(subtitle, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
        }
    }
}
