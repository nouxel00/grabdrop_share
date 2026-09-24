package io.github.nouxel00.grabdrop.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.util.Base64

/**
 * Appairage par QR code à usage unique (voir grabdrop/pairing.py, variante téléphone).
 *
 * Le QR contient l'adresse du PC et un jeton de 128 bits qui ne circule jamais :
 * le téléphone prouve qu'il le connaît (HMAC) et reçoit la clé du groupe chiffrée
 * avec une clé dérivée du jeton.
 */
class PairingException(message: String) : Exception(message)

data class QrInfo(val hosts: List<String>, val port: Int, val token: ByteArray, val hostName: String)

/** [host]/[port] : l'adresse du PC qui a répondu, gardée en secours si la découverte mDNS échoue. */
data class JoinResult(val groupCode: String, val hostName: String, val host: String = "", val port: Int = 0)

fun parsePairingQr(content: String): QrInfo {
    val uri = try { URI(content.trim()) } catch (e: Exception) { throw PairingException("QR code non reconnu") }
    if (uri.scheme != "grabdrop" || uri.host != "pair") throw PairingException("QR code non reconnu")
    val query = (uri.rawQuery ?: "").split("&").filter { "=" in it }.associate {
        val (k, v) = it.split("=", limit = 2)
        URLDecoder.decode(k, "UTF-8") to URLDecoder.decode(v, "UTF-8")
    }
    if (query["v"] != "1") throw PairingException("QR code d'une version de GrabDrop non prise en charge")
    return try {
        QrInfo(
            hosts = query.getValue("h").split(",").filter { it.isNotBlank() },
            port = query.getValue("p").toInt(),
            token = Base32.decode(query.getValue("t")),
            hostName = query["n"] ?: "PC",
        )
    } catch (e: Exception) {
        throw PairingException("QR code incomplet")
    }
}

/** [servicePort] : port du serveur du téléphone, que le PC retient pour le joindre si mDNS échoue. */
fun joinWithQr(info: QrInfo, deviceId: String, deviceName: String, servicePort: Int = DEFAULT_PORT): JoinResult {
    val nonce = randomBytes(16)
    val mac = hmacSha256(Hkdf.derive(info.token, "grabdrop qr mac".toByteArray(), 32), nonce + deviceId.toByteArray())
    val b64 = Base64.getEncoder()
    val body = buildJsonObject {
        put("id", deviceId); put("name", deviceName); put("port", servicePort)
        put("nonce", b64.encodeToString(nonce)); put("mac", b64.encodeToString(mac))
    }.toString().toByteArray()

    var error = PairingException("PC injoignable : êtes-vous sur le même Wi-Fi ?")
    for (host in info.hosts) {
        val conn = (URL("http://$host:${info.port}/v1/pair/qr").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; connectTimeout = 3000; readTimeout = 5000; doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            conn.outputStream.use { it.write(body) }
            when (conn.responseCode) {
                200 -> {
                    val reply = Json.parseToJsonElement(conn.inputStream.use { it.readBytes() }.decodeToString()).jsonObject
                    val box = Base64.getDecoder().decode(reply["box"]!!.jsonPrimitive.content)
                    val key = Hkdf.derive(info.token, "grabdrop qr box".toByteArray(), 32)
                    val group = Json.parseToJsonElement(
                        aesGcmDecrypt(key, box.copyOfRange(0, 12), box.copyOfRange(12, box.size), nonce).decodeToString()
                    ).jsonObject
                    return JoinResult(
                        group["group_code"]!!.jsonPrimitive.content,
                        reply["name"]?.jsonPrimitive?.content ?: info.hostName,
                        host, info.port,
                    )
                }
                409, 410 -> error = PairingException("QR code expiré ou déjà utilisé : affichez-en un nouveau sur le PC")
                else -> error = PairingException("appairage refusé (HTTP ${conn.responseCode})")
            }
        } catch (e: IOException) {
            // adresse injoignable (VPN, carte réseau virtuelle...) : on essaie la suivante
        } finally {
            conn.disconnect()
        }
    }
    throw error
}
