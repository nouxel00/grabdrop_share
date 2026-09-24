package io.github.nouxel00.grabdrop.ui

import android.app.DownloadManager
import android.content.Intent
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import io.github.nouxel00.grabdrop.BlePeer
import io.github.nouxel00.grabdrop.GrabDropRuntime
import io.github.nouxel00.grabdrop.HandReading
import io.github.nouxel00.grabdrop.HeldView
import io.github.nouxel00.grabdrop.Received
import io.github.nouxel00.grabdrop.bindGestureCamera
import io.github.nouxel00.grabdrop.copyTextToClipboard
import io.github.nouxel00.grabdrop.core.Ble
import io.github.nouxel00.grabdrop.core.GestureEvent
import io.github.nouxel00.grabdrop.core.Kind
import io.github.nouxel00.grabdrop.core.Peer
import io.github.nouxel00.grabdrop.core.Posture
import io.github.nouxel00.grabdrop.openUri
import io.github.nouxel00.grabdrop.ui.theme.Brand
import io.github.nouxel00.grabdrop.ui.theme.GdIcons
import io.github.nouxel00.grabdrop.ui.theme.GrabDropTheme
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

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
    val nearby by runtime.nearby.collectAsState()
    val bleStatus by runtime.bleStatus.collectAsState()
    val deviceNames by runtime.deviceNames.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    var playing by remember { mutableStateOf<PlayingAnimation?>(null) }
    var confirmForget by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { runtime.messages.collect { snackbar.showSnackbar(it) } }
    LaunchedEffect(Unit) { runtime.animations.collect { playing = PlayingAnimation(System.nanoTime(), it) } }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                TopBar(runtime.config.deviceName, paired)
                if (!paired) {
                    PairingHero(onScanQr)
                } else {
                    AnimatedVisibility(
                        held != null,
                        enter = expandVertically() + fadeIn(),
                        exit = shrinkVertically() + fadeOut(),
                    ) { held?.let { HeldCard(it, runtime::cancelHeld) } }
                    GestureCard(runtime, hasCameraPermission, onRequestCamera)
                    ActionRow(onPickPhotos, onPickFiles, onReceive = { runtime.receive() })
                    NearbySection(deviceRows(peers, nearby, deviceNames), bleStatus)
                    if (received.isNotEmpty()) ReceivedSection(received)
                    TipCard()
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        TextButton(onClick = onScanQr) { Text("Appairer à nouveau") }
                        TextButton(onClick = { confirmForget = true }) {
                            Text("Oublier le groupe", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
            BusyBanner(busy)
            AnimationOverlay(playing) { playing = null }
        }
    }

    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text("Oublier le groupe ?") },
            text = { Text("Le téléphone ne pourra plus échanger avec vos PC tant qu'il n'est pas appairé à nouveau.") },
            confirmButton = {
                TextButton(onClick = { confirmForget = false; runtime.forgetGroup() }) { Text("Oublier") }
            },
            dismissButton = { TextButton(onClick = { confirmForget = false }) { Text("Annuler") } },
        )
    }
}

// --- En-tête ------------------------------------------------------------------------------

@Composable
fun LogoMark(size: Dp, modifier: Modifier = Modifier) {
    Box(
        modifier
            .size(size)
            .clip(RoundedCornerShape(size * 0.3f))
            .background(Brush.linearGradient(listOf(Brand.Sky, Brand.Blue, Brand.BlueDeep))),
        contentAlignment = Alignment.Center,
    ) {
        Icon(GdIcons.HandOpen, null, tint = Color.White, modifier = Modifier.size(size * 0.58f))
    }
}

@Composable
private fun TopBar(deviceName: String, paired: Boolean) {
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        LogoMark(44.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text("GrabDrop", style = MaterialTheme.typography.titleLarge)
            Text(
                deviceName, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        StatusPill(paired)
    }
}

@Composable
private fun StatusPill(paired: Boolean) {
    val color = if (paired) GrabDropTheme.colors.success else MaterialTheme.colorScheme.onSurfaceVariant
    Surface(shape = CircleShape, color = color.copy(alpha = 0.12f)) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(color))
            Spacer(Modifier.width(6.dp))
            Text(if (paired) "Appairé" else "Non appairé", style = MaterialTheme.typography.labelMedium, color = color)
        }
    }
}

// --- Appairage (premier lancement) -------------------------------------------------------

@Composable
private fun PairingHero(onScanQr: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
        Spacer(Modifier.height(20.dp))
        Box(contentAlignment = Alignment.Center) {
            Box(Modifier.size(168.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.08f)))
            Box(Modifier.size(128.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)))
            LogoMark(88.dp)
        }
        Spacer(Modifier.height(24.dp))
        Text("Transférez d'un geste", style = MaterialTheme.typography.headlineMedium, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        Text(
            "Attrapez sur un écran, ouvrez la main devant l'autre. Commencez par relier ce téléphone à votre PC.",
            style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
        SectionCard {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                StepRow(1, "Sur le PC, clic droit sur l'icône GrabDrop, puis « Appairer un nouvel appareil… »")
                StepRow(2, "Scannez le QR code qui s'affiche (valable 2 minutes)")
                StepRow(3, "Gardez le Wi-Fi ou le Bluetooth activé : vos PC seront trouvés tout seuls")
            }
        }
        Spacer(Modifier.height(20.dp))
        Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(18.dp)) {
            Icon(GdIcons.Qr, null, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(10.dp))
            Text("Scanner le QR code")
        }
    }
}

@Composable
private fun StepRow(number: Int, text: String) {
    Row(verticalAlignment = Alignment.Top) {
        Box(
            Modifier.size(28.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Text("$number", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onPrimaryContainer)
        }
        Spacer(Modifier.width(14.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 3.dp))
    }
}

// --- Objet en main ------------------------------------------------------------------------

@Composable
private fun HeldCard(held: HeldView, onCancel: () -> Unit) {
    val colors = GrabDropTheme.colors
    Surface(
        shape = MaterialTheme.shapes.large, color = colors.heldContainer,
        border = BorderStroke(1.5.dp, colors.held.copy(alpha = 0.55f)), modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            CountdownRing(held.remainingS, held.totalS, colors.held)
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("EN MAIN", style = MaterialTheme.typography.labelSmall, color = colors.held, modifier = Modifier.weight(1f))
                    Surface(onClick = onCancel, shape = CircleShape, color = colors.held.copy(alpha = 0.14f)) {
                        Text("Relâcher", style = MaterialTheme.typography.labelMedium, color = colors.held,
                             modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp))
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(held.description, style = MaterialTheme.typography.titleMedium, color = colors.onHeldContainer,
                     maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text("Ouvrez la main devant un PC pour le déposer", style = MaterialTheme.typography.bodySmall,
                     color = colors.onHeldContainer.copy(alpha = 0.8f))
            }
        }
    }
}

@Composable
private fun CountdownRing(remaining: Int, total: Int, color: Color) {
    val progress by animateFloatAsState(remaining / total.toFloat().coerceAtLeast(1f), tween(450), label = "compte à rebours")
    Box(Modifier.size(58.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = Stroke(width = 5.dp.toPx(), cap = StrokeCap.Round)
            drawArc(color.copy(alpha = 0.18f), 0f, 360f, false, style = stroke)
            drawArc(color, -90f, 360f * progress, false, style = stroke)
        }
        Text("$remaining", style = MaterialTheme.typography.titleMedium, color = color)
    }
}

// --- Gestes ---------------------------------------------------------------------------------

@Composable
private fun GestureCard(runtime: GrabDropRuntime, hasPermission: Boolean, onRequestCamera: () -> Unit) {
    var enabled by remember { mutableStateOf(runtime.config.gesturesEnabled) }
    var reading by remember { mutableStateOf<HandReading?>(null) }
    SectionCard {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(width = 104.dp, height = 138.dp).clip(RoundedCornerShape(18.dp))
                    .background(MaterialTheme.colorScheme.surfaceContainerHighest),
                contentAlignment = Alignment.Center,
            ) {
                if (enabled && hasPermission) {
                    CameraPreview(runtime) { reading = it }
                    reading?.let { PostureChip(it, Modifier.align(Alignment.BottomCenter).padding(8.dp)) }
                } else {
                    Icon(GdIcons.HandOpen, null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                         modifier = Modifier.size(40.dp))
                }
            }
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Gestes", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    Switch(checked = enabled, onCheckedChange = {
                        enabled = it; runtime.config.gesturesEnabled = it
                        if (it && !hasPermission) onRequestCamera()
                    })
                }
                GestureLegend(GdIcons.HandOpen, GdIcons.Fist, "Attraper")
                GestureLegend(GdIcons.Fist, GdIcons.HandOpen, "Recevoir")
                when {
                    enabled && !hasPermission -> TextButton(onClick = onRequestCamera, contentPadding = ButtonDefaults.TextButtonWithIconContentPadding) {
                        Text("Autoriser la caméra")
                    }
                    !enabled -> Text("Caméra coupée", style = MaterialTheme.typography.bodySmall,
                                     color = MaterialTheme.colorScheme.onSurfaceVariant)
                    reading != null -> reading?.let {
                        Text("${it.extended}/4 doigts · ${if (it.palmFacing) "paume" else "dos"}",
                             style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun GestureLegend(from: ImageVector, to: ImageVector, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        val tint = MaterialTheme.colorScheme.primary
        Icon(from, null, tint = tint, modifier = Modifier.size(20.dp))
        Icon(GdIcons.Chevron, null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(14.dp))
        Icon(to, null, tint = tint, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun PostureChip(reading: HandReading, modifier: Modifier) {
    val (icon, label) = when (reading.posture) {
        Posture.OPEN -> GdIcons.HandOpen to "Ouverte"
        Posture.FIST -> GdIcons.Fist to "Poing"
        else -> null to "Main"
    }
    Surface(modifier, shape = CircleShape, color = Color.Black.copy(alpha = 0.55f)) {
        Row(Modifier.padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            icon?.let { Icon(it, null, tint = Color.White, modifier = Modifier.size(14.dp)); Spacer(Modifier.width(4.dp)) }
            Text(label, style = MaterialTheme.typography.labelSmall, color = Color.White, maxLines = 1)
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
    AndroidView({ previewView }, Modifier.fillMaxSize())
}

// --- Actions --------------------------------------------------------------------------------

@Composable
private fun ActionRow(onPhotos: () -> Unit, onFiles: () -> Unit, onReceive: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        ActionTile(GdIcons.Photo, "Photos", false, onPhotos, Modifier.weight(1f))
        ActionTile(GdIcons.Folder, "Fichiers", false, onFiles, Modifier.weight(1f))
        ActionTile(GdIcons.Receive, "Recevoir", true, onReceive, Modifier.weight(1f))
    }
}

@Composable
private fun ActionTile(icon: ImageVector, label: String, primary: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val scheme = MaterialTheme.colorScheme
    Surface(
        onClick = onClick, modifier = modifier.height(100.dp), shape = MaterialTheme.shapes.large,
        color = if (primary) scheme.primary else scheme.surfaceContainer,
        border = if (primary) null else BorderStroke(1.dp, scheme.outlineVariant),
    ) {
        Column(
            Modifier.fillMaxSize().padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Box(
                Modifier.size(42.dp).clip(CircleShape)
                    .background(if (primary) Color.White.copy(alpha = 0.18f) else scheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, null, tint = if (primary) scheme.onPrimary else scheme.onPrimaryContainer, modifier = Modifier.size(22.dp))
            }
            Spacer(Modifier.height(8.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, color = if (primary) scheme.onPrimary else scheme.onSurface,
                 maxLines = 1, softWrap = false)
        }
    }
}

// --- Appareils à proximité ------------------------------------------------------------------

private data class DeviceRow(val name: String, val detail: String, val rssi: Int?, val holding: Boolean)

private fun deviceRows(peers: List<Peer>, nearby: List<BlePeer>, names: Map<String, String>): List<DeviceRow> {
    val wifiHosts = peers.map { it.host }.toSet()
    val byHost = peers.associateBy { it.host }
    val rows = nearby.map { b ->
        val a = b.announcement
        val name = names[a.tagHex] ?: byHost[a.host]?.name ?: "PC (${a.host})"
        val detail = "Bluetooth · ${Ble.proximity(b.rssi)}" + if (a.host in wifiHosts) " · Wi-Fi" else ""
        DeviceRow(name, detail, b.rssi, a.holding)
    }
    val bleHosts = nearby.map { it.announcement.host }.toSet()
    return rows + peers.filter { it.host !in bleHosts }.map { DeviceRow(it.name, "Wi-Fi", null, false) }
}

@Composable
private fun NearbySection(rows: List<DeviceRow>, bleStatus: String) {
    SectionTitle("À proximité")
    SectionCard(Modifier.animateContentSize()) {
        if (rows.isEmpty()) {
            val hint = when (bleStatus) {
                "autorisation manquante" -> "Autorisez « Appareils à proximité » pour trouver vos PC en Bluetooth."
                "Bluetooth désactivé" -> "Activez le Bluetooth, ou restez sur le même Wi-Fi que vos PC."
                else -> "Lancez GrabDrop sur un PC du même Wi-Fi, ou gardez le Bluetooth activé."
            }
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                IconBadge(GdIcons.Bluetooth, MaterialTheme.colorScheme.onSurfaceVariant, MaterialTheme.colorScheme.surfaceContainerHighest)
                Spacer(Modifier.width(14.dp))
                Column {
                    Text("Aucun PC trouvé pour l'instant", style = MaterialTheme.typography.titleSmall)
                    Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            Column(Modifier.padding(vertical = 6.dp)) { rows.forEach { DeviceItem(it) } }
        }
    }
}

@Composable
private fun DeviceItem(row: DeviceRow) {
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        IconBadge(GdIcons.Laptop, scheme.onPrimaryContainer, scheme.primaryContainer)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(row.name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(row.detail, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            if (row.holding) {
                Spacer(Modifier.height(6.dp))
                Surface(shape = CircleShape, color = GrabDropTheme.colors.heldContainer) {
                    Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(GdIcons.Fist, null, tint = GrabDropTheme.colors.held, modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Tient un objet", style = MaterialTheme.typography.labelMedium,
                             color = GrabDropTheme.colors.onHeldContainer)
                    }
                }
            }
        }
        row.rssi?.let { SignalBars(it) }
    }
}

@Composable
private fun SignalBars(rssi: Int) {
    val level = when {
        rssi >= -55 -> 4
        rssi >= -65 -> 3
        rssi >= -75 -> 2
        else -> 1
    }
    val on = MaterialTheme.colorScheme.primary
    val off = MaterialTheme.colorScheme.outlineVariant
    Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        listOf(6, 10, 14, 18).forEachIndexed { i, h ->
            Box(Modifier.width(4.dp).height(h.dp).clip(RoundedCornerShape(2.dp)).background(if (i < level) on else off))
        }
    }
}

// --- Reçus -----------------------------------------------------------------------------------

private val hourFormat = SimpleDateFormat("HH:mm", Locale.FRANCE)

@Composable
private fun ReceivedSection(items: List<Received>) {
    val context = LocalContext.current
    SectionTitle("Reçus")
    SectionCard {
        Column(Modifier.padding(vertical = 6.dp)) {
            items.forEach { r ->
                val icon = when (r.kind) {
                    Kind.TEXT -> GdIcons.Text
                    Kind.IMAGE, Kind.SCREENSHOT -> GdIcons.Photo
                    else -> GdIcons.Folder
                }
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconBadge(icon, MaterialTheme.colorScheme.onPrimaryContainer, MaterialTheme.colorScheme.primaryContainer)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(r.description, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        val where = if (r.text != null) "Dans le presse-papiers · " else ""
                        Text("${where}de ${r.from} · ${hourFormat.format(Date(r.timeMs))}", style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    when {
                        r.text != null -> TextButton(onClick = { copyTextToClipboard(context, r.text) }) { Text("Copier") }
                        r.uris.size == 1 -> TextButton(onClick = { openUri(context, r.uris[0].first, r.uris[0].second) }) { Text("Ouvrir") }
                        r.uris.isNotEmpty() -> TextButton(onClick = {
                            runCatching {
                                context.startActivity(Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                            }
                        }) { Text("Voir") }
                    }
                }
            }
        }
    }
}

// --- Petits éléments communs ---------------------------------------------------------------

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 4.dp, start = 4.dp))
}

@Composable
private fun SectionCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Surface(
        modifier = modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainer,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        content = content,
    )
}

@Composable
private fun IconBadge(icon: ImageVector, tint: Color, background: Color) {
    Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(background), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = tint, modifier = Modifier.size(22.dp))
    }
}

@Composable
private fun TipCard() {
    Surface(shape = MaterialTheme.shapes.medium, color = GrabDropTheme.colors.subtle, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(GdIcons.Send, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(12.dp))
            Text(
                "Depuis n'importe quelle app : « Partager » puis « GrabDrop », et ouvrez la main devant un PC.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun BusyBanner(text: String?) {
    AnimatedVisibility(
        text != null, enter = slideInVertically { -it } + fadeIn(), exit = slideOutVertically { -it } + fadeOut(),
        modifier = Modifier.fillMaxWidth().statusBarsPadding(),
    ) {
        Box(Modifier.fillMaxWidth().padding(top = 8.dp), contentAlignment = Alignment.TopCenter) {
            Surface(shape = CircleShape, color = MaterialTheme.colorScheme.inverseSurface, shadowElevation = 6.dp) {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(16.dp), color = MaterialTheme.colorScheme.inverseOnSurface, strokeWidth = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text(text ?: "", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.inverseOnSurface)
                }
            }
        }
    }
}
