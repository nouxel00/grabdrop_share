package io.github.nouxel00.grabdrop.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.nio.ByteBuffer
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import kotlin.math.abs

/**
 * Échanges entre appareils, identiques à grabdrop/network.py :
 * - POST /v1/offer : « as-tu quelque chose en main ? »
 * - POST /v1/claim : « je prends l'objet X » -> flux chiffré par morceaux.
 */
const val SERVICE_TYPE = "_grabdrop._tcp"
const val DEFAULT_PORT = 47800
private const val MAX_CLOCK_SKEW_S = 120.0
private const val MAX_REQUEST_BYTES = 64 * 1024
private const val MAX_HEADER_BYTES = 16 * 1024 * 1024
private const val MAX_MEMORY_BYTES = 256 * 1024 * 1024
private const val CONNECT_TIMEOUT_MS = 3000
private const val READ_TIMEOUT_MS = 10_000

data class Peer(val deviceId: String, val name: String, val host: String, val port: Int) {
    val url get() = "http://${if (':' in host) "[$host]" else host}:$port"
}

data class Offer(
    val peer: Peer,
    val deviceId: String,
    val deviceName: String,
    val itemId: String,
    val kind: String,
    val name: String,
    val size: Long,
    val count: Int,
    val ageS: Double,
) {
    fun describe() = describe(kind, name, size, count)
}

/** Où écrire les fichiers reçus (disque, MediaStore Android...). */
interface ReceiveSink {
    fun openFile(relativePath: String, size: Long): OutputStream
    fun commit()
    fun abort()
}

fun interface Logger {
    fun log(message: String)
}

class Node(
    val deviceId: String,
    @Volatile var deviceName: String,
    @Volatile var channel: Channel,
    val held: HeldItem,
    private val requestedPort: Int = DEFAULT_PORT,
    private val bindAddress: InetAddress? = null,
    private val logger: Logger = Logger { },
    /** Événements côté serveur : un autre appareil vient de prendre notre objet. */
    private val onItemSent: (Item) -> Unit = {},
) {
    @Volatile var peersProvider: () -> List<Peer> = { emptyList() }
    /** Noms des appareils du groupe, par identifiant court (les annonces Bluetooth n'ont pas le nom). */
    val names = java.util.concurrent.ConcurrentHashMap<String, String>()
    private var server: ServerSocket? = null
    private val pool = Executors.newCachedThreadPool { r -> Thread(r, "grabdrop-http").apply { isDaemon = true } }

    val port: Int get() = server?.localPort ?: requestedPort

    fun start() {
        val socket = try {
            ServerSocket(requestedPort, 16, bindAddress)
        } catch (e: IOException) {
            ServerSocket(0, 16, bindAddress)  // port occupé : un autre, annoncé par mDNS
        }
        server = socket
        Thread({ acceptLoop(socket) }, "grabdrop-accept").apply { isDaemon = true }.start()
    }

    fun stop() {
        server?.close()
        server = null
    }

    // --- client ---------------------------------------------------------------------

    fun findOffers(): List<Offer> {
        val peers = peersProvider()
        if (peers.isEmpty()) return emptyList()
        val executor = Executors.newFixedThreadPool(minOf(8, peers.size))
        try {
            return executor.invokeAll(peers.map { p -> Callable { askOffer(p) } })
                .mapNotNull { runCatching { it.get() }.getOrNull() }
                .filter { it.deviceId != deviceId }
                .sortedBy { it.ageS }
        } finally {
            executor.shutdown()
        }
    }

    /** Récupère l'objet ; les fichiers vont dans [sink]. Null si indisponible ou transfert échoué. */
    fun claim(offer: Offer, sink: ReceiveSink): Item? {
        val path = "/v1/claim"
        val sealed = sealRequest(path, buildJsonObject { put("item_id", offer.itemId) })
        val conn = post(offer.peer, path, sealed)
        return try {
            val status = conn.responseCode
            if (status != 200) {
                if (status == 403) logger.log("${offer.peer.name} refuse la requête (groupe différent, ou horloges décalées ?)")
                return null
            }
            conn.inputStream.use { input ->
                readItem(StreamOpener(channel, responseContext(path, sealed), BufferedInputStream(input)), sink)
            }.also { sink.commit() }
        } catch (e: CryptoException) {
            logger.log("transfert depuis ${offer.peer.name} invalide (${e.message})")
            sink.abort(); null
        } catch (e: IOException) {
            logger.log("transfert depuis ${offer.peer.name} interrompu (${e.message})")
            sink.abort(); null
        } finally {
            conn.disconnect()
        }
    }

    /** Demande son nom à un appareil (entendu en Bluetooth, par exemple). */
    fun identify(peer: Peer) {
        runCatching { askOffer(peer) }
    }

    private fun askOffer(peer: Peer): Offer? {
        val body = request(peer, "/v1/offer", buildJsonObject { }) ?: return null
        val reply = Json.parseToJsonElement(body.decodeToString()).jsonObject
        names[reply.str("device_id").take(8)] = reply.str("device_name")
        val item = reply["item"]?.takeIf { it !is JsonNull }?.jsonObject ?: return null
        return Offer(
            peer, reply.str("device_id"), reply.str("device_name"), item.str("id"), item.str("kind"), item.str("name"),
            item["size"]!!.jsonPrimitive.long, item["count"]!!.jsonPrimitive.long.toInt(), item["age_s"]!!.jsonPrimitive.double,
        )
    }

    private fun request(peer: Peer, path: String, payload: JsonObject): ByteArray? {
        val sealed = sealRequest(path, payload)
        val conn = post(peer, path, sealed)
        return try {
            val status = conn.responseCode
            if (status != 200) {
                if (status == 403) logger.log("${peer.name} refuse la requête (groupe différent, ou horloges décalées ?)")
                return null
            }
            val raw = conn.inputStream.use { it.readLimited(MAX_REQUEST_BYTES) }
            try {
                channel.open(raw, responseContext(path, sealed))
            } catch (e: CryptoException) {
                logger.log("réponse invalide de ${peer.name}, ignorée"); null
            }
        } catch (e: IOException) {
            null  // appareil injoignable ou éteint
        } finally {
            conn.disconnect()
        }
    }

    private fun sealRequest(path: String, payload: JsonObject): ByteArray {
        val full = JsonObject(payload + mapOf(
            "ts" to kotlinx.serialization.json.JsonPrimitive(System.currentTimeMillis() / 1000.0),
            "from" to kotlinx.serialization.json.JsonPrimitive(deviceId),
        ))
        return channel.seal(full.toString().toByteArray(), path.toByteArray())
    }

    private fun post(peer: Peer, path: String, body: ByteArray): HttpURLConnection =
        (URL(peer.url + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            doOutput = true
            setFixedLengthStreamingMode(body.size)
            outputStream.use { it.write(body) }
        }

    // --- serveur --------------------------------------------------------------------

    private fun acceptLoop(socket: ServerSocket) {
        while (!socket.isClosed) {
            val client = try { socket.accept() } catch (e: IOException) { break }
            pool.execute { client.use { handle(it) } }
        }
    }

    private fun handle(client: Socket) {
        client.soTimeout = READ_TIMEOUT_MS
        val input = BufferedInputStream(client.getInputStream())
        val out = client.getOutputStream()
        val requestLine = input.readLine() ?: return
        val path = requestLine.split(" ").getOrNull(1) ?: return reply(out, 400)
        var length = 0
        while (true) {
            val line = input.readLine() ?: return
            if (line.isEmpty()) break
            val (name, value) = line.split(":", limit = 2).let { it[0].trim().lowercase() to it.getOrElse(1) { "" }.trim() }
            if (name == "content-length") length = value.toIntOrNull() ?: 0
        }
        if (length > MAX_REQUEST_BYTES) return reply(out, 413)
        val body = input.readNBytesCompat(length)

        val request = try {
            Json.parseToJsonElement(channel.open(body, path.toByteArray()).decodeToString()).jsonObject
        } catch (e: Exception) {
            return reply(out, 403)
        }
        val ts = request["ts"]?.jsonPrimitive?.double ?: 0.0
        if (abs(System.currentTimeMillis() / 1000.0 - ts) > MAX_CLOCK_SKEW_S) return reply(out, 403)

        val context = responseContext(path, body)
        when (path) {
            "/v1/offer" -> reply(out, 200, channel.seal(offerJson().toString().toByteArray(), context))
            "/v1/claim" -> {
                val item = held.take(request["item_id"]?.jsonPrimitive?.content ?: "") ?: return reply(out, 410)
                out.write("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n".toByteArray())
                try {
                    writeItem(item, StreamSealer(channel, context, out))
                    logger.log("Envoyé : ${item.describe()}")
                    onItemSent(item)
                } catch (e: IOException) {
                    logger.log("Envoi interrompu : ${item.describe()} (${e.message})")
                }
            }
            else -> reply(out, 404)
        }
    }

    private fun offerJson(): JsonObject = buildJsonObject {
        put("device_id", deviceId)
        put("device_name", deviceName)
        val current = held.peek()
        if (current == null) put("item", JsonNull) else {
            val (item, ageMs) = current
            put("item", buildJsonObject {
                put("id", item.id); put("kind", item.kind); put("name", item.name)
                put("size", item.size); put("count", item.files.size); put("age_s", ageMs / 1000.0)
            })
        }
    }

    private fun reply(out: OutputStream, status: Int, body: ByteArray = ByteArray(0)) {
        val reason = mapOf(200 to "OK", 400 to "Bad Request", 403 to "Forbidden", 404 to "Not Found", 410 to "Gone", 413 to "Payload Too Large")[status] ?: ""
        out.write("HTTP/1.1 $status $reason\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
        out.write(body)
        out.flush()
    }
}

private fun responseContext(path: String, requestBody: ByteArray): ByteArray =
    "resp:$path".toByteArray() + requestBody.copyOfRange(0, minOf(NONCE_BYTES, requestBody.size))

internal fun writeItem(item: Item, stream: StreamSealer) {
    val header = buildJsonObject {
        put("id", item.id); put("kind", item.kind); put("name", item.name); put("mime", item.mime)
        put("data_len", item.data.size)
        put("files", buildJsonArray {
            item.files.forEach { f -> add(buildJsonObject { put("path", f.path); put("size", f.size) }) }
        })
    }.toString().toByteArray()
    stream.write(ByteBuffer.allocate(4).putInt(header.size).array())
    stream.write(header)
    stream.write(item.data)
    val block = ByteArray(CHUNK_BYTES)
    for (f in item.files) {
        (f.open ?: throw IOException("contenu indisponible : ${f.path}"))().use { src ->
            var remaining = f.size
            while (remaining > 0) {
                val n = src.read(block, 0, minOf(block.size.toLong(), remaining).toInt())
                if (n < 0) throw IOException("${f.path} a été raccourci pendant l'envoi")
                stream.write(block, 0, n)
                remaining -= n
            }
        }
    }
    stream.close()
}

internal fun readItem(stream: StreamOpener, sink: ReceiveSink): Item {
    val headerLen = ByteBuffer.wrap(stream.readExact(4)).int
    if (headerLen < 0 || headerLen > MAX_HEADER_BYTES) throw CryptoException("en-tête trop grand")
    val header = Json.parseToJsonElement(stream.readExact(headerLen).decodeToString()).jsonObject
    val dataLen = header["data_len"]!!.jsonPrimitive.long
    if (dataLen > MAX_MEMORY_BYTES) throw CryptoException("contenu en mémoire trop grand")
    val data = stream.readExact(dataLen.toInt())
    val files = mutableListOf<FileEntry>()
    for (f in (header["files"] as JsonArray)) {
        val obj = f.jsonObject
        val path = safeRelativePath(obj.str("path"))
        val size = obj["size"]!!.jsonPrimitive.long
        sink.openFile(path, size).use { out ->
            var remaining = size
            while (remaining > 0) {
                val block = stream.readSome(minOf(CHUNK_BYTES.toLong(), remaining).toInt())
                out.write(block)
                remaining -= block.size
            }
        }
        files += FileEntry(path, size)
    }
    stream.finish()
    return Item(header.str("kind"), header.str("name"), header.str("mime"), data, files, header.str("id"))
}

private fun JsonObject.str(key: String) = this[key]!!.jsonPrimitive.content

private fun InputStream.readLimited(max: Int): ByteArray {
    val out = ByteArrayOutputStream()
    val buf = ByteArray(8192)
    while (true) {
        val n = read(buf)
        if (n < 0) break
        out.write(buf, 0, n)
        if (out.size() > max) throw IOException("réponse trop grande")
    }
    return out.toByteArray()
}

private fun InputStream.readNBytesCompat(n: Int): ByteArray {
    val data = ByteArray(n)
    var read = 0
    while (read < n) {
        val r = read(data, read, n - read)
        if (r < 0) break
        read += r
    }
    return data.copyOf(read)
}

/** Ligne HTTP terminée par CRLF (en-têtes ASCII). */
private fun InputStream.readLine(): String? {
    val sb = StringBuilder()
    while (true) {
        val c = read()
        if (c < 0) return if (sb.isEmpty()) null else sb.toString()
        if (c == '\n'.code) return sb.toString().trimEnd('\r')
        sb.append(c.toChar())
        if (sb.length > 8192) return null
    }
}
