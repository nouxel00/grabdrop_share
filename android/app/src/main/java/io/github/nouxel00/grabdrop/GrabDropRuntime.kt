package io.github.nouxel00.grabdrop

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import io.github.nouxel00.grabdrop.core.Channel
import io.github.nouxel00.grabdrop.core.DEFAULT_PORT
import io.github.nouxel00.grabdrop.core.FileEntry
import io.github.nouxel00.grabdrop.core.HeldItem
import io.github.nouxel00.grabdrop.core.Item
import io.github.nouxel00.grabdrop.core.Kind
import io.github.nouxel00.grabdrop.core.Node
import io.github.nouxel00.grabdrop.core.PairingException
import io.github.nouxel00.grabdrop.core.Peer
import io.github.nouxel00.grabdrop.core.joinWithQr
import io.github.nouxel00.grabdrop.core.parseGroupCode
import io.github.nouxel00.grabdrop.core.parsePairingQr
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.io.File

/** Ce qui est en main, pour l'affichage. */
data class HeldView(val description: String, val remainingS: Int, val totalS: Int)

/** Objet reçu, pour la liste « Reçus ». */
data class Received(val description: String, val from: String, val uris: List<Pair<Uri, String>>, val text: String? = null)

sealed interface Animation {
    data class Grabbed(val description: String) : Animation
    data class Dropped(val received: Received) : Animation
    data class Sent(val description: String) : Animation
}

/**
 * Cœur de l'app : état partagé par l'interface, l'icône de notification et le réseau.
 * Le réseau tourne quand l'app est visible ou qu'un objet est en main.
 */
class GrabDropRuntime(private val app: Context) {
    val config = DeviceConfig(app)
    val held = HeldItem(ttlMs = HOLD_MS)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val paired = MutableStateFlow(config.groupCode != null)
    val peers = MutableStateFlow<List<Peer>>(emptyList())
    val heldView = MutableStateFlow<HeldView?>(null)
    val busy = MutableStateFlow<String?>(null)
    val received = MutableStateFlow<List<Received>>(emptyList())
    val messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val animations = MutableSharedFlow<Animation>(extraBufferCapacity = 4)

    private var node: Node? = null
    private var discovery: Discovery? = null
    @Volatile private var visible = false
    private val outgoing get() = File(app.cacheDir, "outgoing")

    init {
        scope.launch { tick() }
    }

    // --- cycle de vie du réseau ----------------------------------------------------

    fun onAppVisible(isVisible: Boolean) {
        visible = isVisible
        if (isVisible) ensureRunning() else maybeStop()
    }

    @Synchronized
    fun ensureRunning() {
        if (node != null) return
        val code = config.groupCode ?: return
        val channel = Channel(parseGroupCode(code))
        val n = Node(config.deviceId, config.deviceName, channel, held,
            logger = { Log.i(TAG, it) }, onItemSent = ::onItemSent)
        n.start()
        val d = Discovery(app, config.deviceId, config.deviceName, channel.groupId) { peers.value = it }
        d.start(n.port)
        n.peersProvider = { d.peers() + knownPcsNotDiscovered(d.peers()) }
        node = n
        discovery = d
    }

    /** PC appairés dont l'adresse est connue (QR), en secours de la découverte mDNS. */
    private fun knownPcsNotDiscovered(discovered: List<Peer>): List<Peer> {
        val seen = discovered.map { it.host }.toSet()
        return config.knownPcs.mapNotNull { entry ->
            val host = entry.substringBeforeLast(':')
            val port = entry.substringAfterLast(':').toIntOrNull() ?: return@mapNotNull null
            if (host in seen) null else Peer("", "PC ($host)", host, port)
        }
    }

    @Synchronized
    fun maybeStop() {
        if (visible || held.peek() != null) return
        discovery?.stop()
        node?.stop()
        node = null
        discovery = null
        peers.value = emptyList()
    }

    @Synchronized
    private fun restart() {
        discovery?.stop(); node?.stop(); node = null; discovery = null
        peers.value = emptyList()
        ensureRunning()
    }

    /** Toutes les 0,5 s : compte à rebours de l'objet en main, arrêt du réseau quand plus rien n'est à faire. */
    private suspend fun tick() {
        var wasHolding = false
        while (true) {
            val current = held.peek()
            heldView.value = current?.let { (item, ageMs) ->
                HeldView(item.describe(), ((HOLD_MS - ageMs) / 1000).toInt().coerceAtLeast(0), (HOLD_MS / 1000).toInt())
            }
            if (wasHolding && current == null) {
                outgoing.deleteRecursively()
                maybeStop()
            }
            wasHolding = current != null
            delay(500)
        }
    }

    // --- mettre en main (envoyer) ------------------------------------------------

    fun putInHand(item: Item) {
        held.hold(item)
        ensureRunning()
        animations.tryEmit(Animation.Grabbed(item.describe()))
        messages.tryEmit("En main : ${item.describe()}. Faites DROP devant un PC.")
        app.startForegroundService(Intent(app, GrabDropService::class.java))
    }

    /** Contenus reçus par « Partager » ou choisis dans l'app. */
    fun shareToHand(uris: List<Uri>, text: String?) = scope.launch {
        if (!requirePaired()) return@launch
        if (uris.isEmpty()) {
            if (!text.isNullOrBlank()) putInHand(textItem(text))
            return@launch
        }
        busy.value = "Préparation…"
        try {
            outgoing.deleteRecursively()
            val files = copySharedToCache(app, uris, File(outgoing, System.nanoTime().toString()))
            if (files.isEmpty()) return@launch messages.emit("Impossible de lire les éléments partagés.").let { }
            val entries = files.map { f -> FileEntry(f.name, f.length()) { f.inputStream() } }
            putInHand(Item(Kind.FILES, if (files.size == 1) files[0].name else "${files.size} éléments", files = entries))
        } finally {
            busy.value = null
        }
    }

    /** GRAB fait devant le téléphone : ce qui a été copié il y a moins d'une minute. */
    fun grabFromGesture() {
        if (!requirePaired()) return
        val clip = app.getSystemService(ClipboardManager::class.java).primaryClip
        val copiedAt = clip?.description?.timestamp ?: 0L
        val recent = System.currentTimeMillis() - copiedAt <= RECENT_COPY_MS
        if (clip == null || clip.itemCount == 0 || !recent) {
            messages.tryEmit("Rien à attraper : copiez un texte, ou utilisez « Partager » puis « GrabDrop ».")
            return
        }
        val first = clip.getItemAt(0)
        val uris = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri }
        if (uris.isNotEmpty()) shareToHand(uris, null)
        else putInHand(textItem(first.coerceToText(app).toString()))
    }

    private fun textItem(text: String) = Item(Kind.TEXT, "texte", "text/plain; charset=utf-8", text.toByteArray())

    private fun onItemSent(item: Item) {
        animations.tryEmit(Animation.Sent(item.describe()))
        messages.tryEmit("Déposé sur le PC : ${item.describe()}")
    }

    // --- recevoir (DROP) -------------------------------------------------------------

    fun receive() = scope.launch {
        if (!requirePaired()) return@launch
        busy.value = "Recherche d'un objet en main…"
        try {
            ensureRunning()
            val n = node ?: return@launch
            var offers = n.findOffers()  // PC connus tout de suite...
            if (offers.isEmpty() && peers.value.isEmpty()) {
                repeat(6) { if (peers.value.isEmpty()) delay(500) }  // ...puis laisser le temps à la découverte
                offers = n.findOffers()
            }
            if (offers.isEmpty()) {
                messages.emit(
                    if (peers.value.isEmpty()) "Aucun PC GrabDrop trouvé sur le Wi-Fi."
                    else "Rien à recevoir : faites d'abord un GRAB sur un PC."
                )
                return@launch
            }
            for (offer in offers) {
                busy.value = "Réception de ${offer.describe()}…"
                val sink = MediaStoreSink(app)
                val item = n.claim(offer, sink) ?: continue
                val result = deliver(item, sink, offer.deviceName)
                received.value = (listOf(result) + received.value).take(20)
                animations.emit(Animation.Dropped(result))
                return@launch
            }
            messages.emit("L'objet n'est plus disponible (déjà pris, ou expiré).")
        } finally {
            busy.value = null
        }
    }

    private fun deliver(item: Item, sink: MediaStoreSink, from: String): Received = when (item.kind) {
        Kind.SCREENSHOT, Kind.IMAGE -> {
            val uri = saveImage(app, item.data, item.name)
            if (item.kind == Kind.IMAGE) copyImageToClipboard(app, uri)
            openUri(app, uri, "image/png")
            Received(item.describe(), from, listOf(uri to "image/png"))
        }
        Kind.TEXT -> {
            val text = item.data.decodeToString()
            copyTextToClipboard(app, text)
            if (isSingleUrl(text)) openUrl(app, text.trim())
            Received("texte copié dans le presse-papiers", from, emptyList(), text)
        }
        else -> {
            if (sink.created.size == 1) sink.created[0].let { (uri, mime) -> openUri(app, uri, mime) }
            Received(item.describe(), from, sink.created.toList())
        }
    }

    // --- appairage -----------------------------------------------------------------

    fun pairWithQr(content: String) = scope.launch {
        busy.value = "Appairage…"
        try {
            val result = joinWithQr(parsePairingQr(content), config.deviceId, config.deviceName, node?.port ?: DEFAULT_PORT)
            if (result.groupCode != config.groupCode) config.knownPcs = emptySet()  // nouveau groupe
            config.groupCode = result.groupCode
            config.knownPcs = config.knownPcs + "${result.host}:${result.port}"
            paired.value = true
            restart()
            messages.emit("Appairé avec « ${result.hostName} ».")
        } catch (e: PairingException) {
            messages.emit("Appairage impossible : ${e.message}")
        } catch (e: Exception) {
            messages.emit("Appairage impossible : ${e.message ?: e.javaClass.simpleName}")
        } finally {
            busy.value = null
        }
    }

    fun forgetGroup() {
        config.groupCode = null
        config.knownPcs = emptySet()
        paired.value = false
        held.clear()
        synchronized(this) { discovery?.stop(); node?.stop(); node = null; discovery = null }
        peers.value = emptyList()
    }

    fun cancelHeld() {
        held.clear()
        messages.tryEmit("Objet relâché.")
    }

    private fun requirePaired(): Boolean {
        if (config.groupCode != null) return true
        messages.tryEmit("Appairez d'abord le téléphone avec un PC (scanner le QR code).")
        return false
    }

    companion object {
        const val TAG = "GrabDrop"
        const val HOLD_MS = 60_000L
        const val RECENT_COPY_MS = 60_000L
    }
}
