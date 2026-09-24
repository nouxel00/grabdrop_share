package io.github.nouxel00.grabdrop.ui

import android.app.DownloadManager
import android.content.Intent
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import io.github.nouxel00.grabdrop.GrabDropRuntime
import io.github.nouxel00.grabdrop.HandReading
import io.github.nouxel00.grabdrop.HeldView
import io.github.nouxel00.grabdrop.Received
import io.github.nouxel00.grabdrop.bindGestureCamera
import io.github.nouxel00.grabdrop.copyTextToClipboard
import io.github.nouxel00.grabdrop.core.GestureEvent
import io.github.nouxel00.grabdrop.core.Posture
import io.github.nouxel00.grabdrop.openUri

private val Orange = Color(0xFFF59E0B)

@Composable
fun HomeScreen(
    runtime: GrabDropRuntime,
    hasCameraPermission: Boolean,
    onRequestCamera: () -> Unit,
    onScanQr: () -> Unit,
    onPickPhotos: () -> Unit,
    onPickFiles: () -> Unit,
) {
    val paired by runtime.paired.collectAsState()
    val peers by runtime.peers.collectAsState()
    val held by runtime.heldView.collectAsState()
    val busy by runtime.busy.collectAsState()
    val received by runtime.received.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    var playing by remember { mutableStateOf<PlayingAnimation?>(null) }

    LaunchedEffect(Unit) { runtime.messages.collect { snackbar.showSnackbar(it) } }
    LaunchedEffect(Unit) { runtime.animations.collect { playing = PlayingAnimation(System.nanoTime(), it) } }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Header(runtime.config.deviceName, paired, peers.size)
                if (!paired) {
                    PairCard(onScanQr)
                } else {
                    GestureCard(runtime, hasCameraPermission, onRequestCamera)
                    AnimatedVisibility(held != null, enter = scaleIn() + fadeIn(), exit = shrinkVertically() + fadeOut()) {
                        held?.let { HeldCard(it, runtime::cancelHeld) }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton(onClick = onPickPhotos, modifier = Modifier.weight(1f)) { Text("Photos") }
                        OutlinedButton(onClick = onPickFiles, modifier = Modifier.weight(1f)) { Text("Fichiers") }
                        Button(onClick = { runtime.receive() }, modifier = Modifier.weight(1.2f)) { Text("Recevoir") }
                    }
                    Text(
                        // Pas de flèche « → » : certaines polices de téléphone ne l'ont pas.
                        "Envoyer : Photos / Fichiers, ou « Partager » puis « GrabDrop » depuis n'importe quelle app, " +
                            "puis DROP devant un PC.\nRecevoir : GRAB devant un PC, puis DROP devant le téléphone (ou « Recevoir »).",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (received.isNotEmpty()) ReceivedSection(received)
                    Row {
                        TextButton(onClick = onScanQr) { Text("Appairer à nouveau") }
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = runtime::forgetGroup) { Text("Oublier le groupe") }
                    }
                }
            }
            busy?.let { BusyBanner(it) }
            AnimationOverlay(playing) { playing = null }
        }
    }
}

@Composable
private fun Header(deviceName: String, paired: Boolean, peerCount: Int) {
    Column {
        Text("GrabDrop", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        val status = when {
            !paired -> "Pas encore appairé"
            peerCount == 0 -> "Appairé · recherche des PC sur le Wi-Fi…"
            else -> "Appairé · $peerCount PC trouvé(s)"
        }
        Text("$deviceName · $status", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun PairCard(onScanQr: () -> Unit) {
    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Appairer avec un PC", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(
                "1. Sur le PC : clic droit sur l'icône GrabDrop, puis « Appairer un nouvel appareil… »\n" +
                    "2. Ici : scannez le QR code affiché (valable 2 minutes, une seule fois).\n" +
                    "Le téléphone et le PC doivent être sur le même Wi-Fi.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth()) { Text("Scanner le QR code") }
        }
    }
}

@Composable
private fun GestureCard(runtime: GrabDropRuntime, hasPermission: Boolean, onRequestCamera: () -> Unit) {
    var enabled by remember { mutableStateOf(runtime.config.gesturesEnabled) }
    var reading by remember { mutableStateOf<HandReading?>(null) }
    Card(shape = RoundedCornerShape(20.dp)) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Gestes", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    Switch(checked = enabled, onCheckedChange = {
                        enabled = it; runtime.config.gesturesEnabled = it
                        if (it && !hasPermission) onRequestCamera()
                    })
                }
                Text(
                    "✋ puis ✊ : attraper · ✊ puis ✋ : recevoir",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (enabled && hasPermission) {
                    val r = reading
                    val label = when (r?.posture) {
                        Posture.OPEN -> "Main ouverte ✋"
                        Posture.FIST -> "Poing ✊"
                        else -> if (r == null) "Aucune main" else "Main détectée"
                    }
                    Text(label, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                    if (r != null) Text(
                        "${r.extended}/4 doigts · ${if (r.palmFacing) "paume" else "dos"} · taille ${"%.2f".format(r.size)}",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else if (enabled) {
                    TextButton(onClick = onRequestCamera) { Text("Autoriser la caméra") }
                }
            }
            if (enabled && hasPermission) {
                Spacer(Modifier.width(12.dp))
                CameraPreview(runtime) { reading = it }
            }
        }
    }
}

@Composable
private fun CameraPreview(runtime: GrabDropRuntime, onReading: (HandReading?) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    DisposableEffect(lifecycleOwner) {
        val release = bindGestureCamera(
            context, lifecycleOwner, previewView,
            onEvent = { event ->
                context.mainExecutor.execute {
                    if (event == GestureEvent.GRAB) runtime.grabFromGesture() else runtime.receive()
                }
            },
            onReading = { r -> context.mainExecutor.execute { onReading(r) } },
        )
        onDispose { release() }
    }
    AndroidView({ previewView }, Modifier.size(width = 96.dp, height = 128.dp).clip(RoundedCornerShape(16.dp)))
}

@Composable
private fun HeldCard(held: HeldView, onCancel: () -> Unit) {
    val pulse by rememberInfiniteTransition(label = "pulse").animateFloat(
        initialValue = 1f, targetValue = 1.02f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "pulse",
    )
    Card(
        modifier = Modifier.fillMaxWidth().scale(pulse),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(2.dp, Orange),
        colors = CardDefaults.cardColors(containerColor = Orange.copy(alpha = 0.10f)),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("✊", style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text("En main", style = MaterialTheme.typography.labelLarge, color = Orange)
                    Text(held.description, style = MaterialTheme.typography.titleMedium)
                }
                TextButton(onClick = onCancel) { Text("Relâcher") }
            }
            LinearProgressIndicator(
                progress = { held.remainingS / held.totalS.toFloat() },
                modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
                color = Orange,
            )
            Text("Faites DROP devant un PC · encore ${held.remainingS} s", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun ReceivedSection(items: List<Received>) {
    val context = LocalContext.current
    Text("Reçus", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
    items.forEach { r ->
        Card(shape = RoundedCornerShape(16.dp)) {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(r.description, style = MaterialTheme.typography.bodyLarge)
                    Text("de ${r.from}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                when {
                    r.text != null -> TextButton(onClick = { copyTextToClipboard(context, r.text) }) { Text("Copier") }
                    r.uris.size == 1 -> TextButton(onClick = { openUri(context, r.uris[0].first, r.uris[0].second) }) { Text("Ouvrir") }
                    r.uris.isNotEmpty() -> TextButton(onClick = {
                        runCatching { context.startActivity(Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    }) { Text("Voir") }
                }
            }
        }
    }
}

@Composable
private fun BusyBanner(text: String) {
    Column(Modifier.fillMaxWidth()) {
        LinearProgressIndicator(Modifier.fillMaxWidth())
        Card(
            Modifier.align(Alignment.CenterHorizontally).padding(top = 8.dp),
            shape = RoundedCornerShape(50),
            elevation = CardDefaults.cardElevation(defaultElevation = 6.dp),
        ) {
            Text(text, Modifier.padding(horizontal = 16.dp, vertical = 8.dp), style = MaterialTheme.typography.bodyMedium)
        }
    }
}
