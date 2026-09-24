package io.github.nouxel00.grabdrop.core

import java.net.Inet4Address
import java.net.InetAddress
import java.nio.ByteBuffer
import java.security.MessageDigest

/**
 * Annonce Bluetooth (BLE), identique à grabdrop/ble.py : 18 octets dans les
 * « données fabricant » (identifiant 0xFFFF).
 *
 *   « GD » (2) | version (1) | signature (4) | contenu chiffré (11)
 *   contenu : identifiant court (4) | IPv4 (4) | port (2) | indicateurs (1)
 *
 * Le BLE sert à trouver les appareils ; les données passent par le Wi-Fi.
 */
object Ble {
    const val COMPANY_ID = 0xFFFF
    const val PAYLOAD_BYTES = 18
    const val PERIOD_S = 600L
    const val FLAG_HOLDING = 0x01
    const val FLAG_PHONE = 0x02
    private val MAGIC = byteArrayOf('G'.code.toByte(), 'D'.code.toByte())
    private const val VERSION: Byte = 1

    data class Announcement(val deviceTag: ByteArray, val host: String, val port: Int, val flags: Int) {
        val holding get() = flags and FLAG_HOLDING != 0
        val isPhone get() = flags and FLAG_PHONE != 0
        val tagHex get() = deviceTag.toHex()

        override fun equals(other: Any?) = other is Announcement && deviceTag.contentEquals(other.deviceTag) &&
            host == other.host && port == other.port && flags == other.flags
        override fun hashCode() = deviceTag.contentHashCode() * 31 + host.hashCode()
    }

    fun deviceTag(deviceId: String): ByteArray = ByteArray(4) { i -> deviceId.substring(2 * i, 2 * i + 2).toInt(16).toByte() }

    /** Clé des annonces, dérivée de la clé du groupe (comme Channel.ble_key côté PC). */
    fun key(groupSecret: ByteArray): ByteArray = Hkdf.derive(groupSecret, "grabdrop v1 ble".toByteArray(), 32)

    private fun mac(key: ByteArray, label: String, period: Long, data: ByteArray = ByteArray(0)): ByteArray =
        hmacSha256(key, label.toByteArray() + ByteBuffer.allocate(4).putInt(period.toInt()).array() + data)

    fun encode(key: ByteArray, a: Announcement, nowS: Long = System.currentTimeMillis() / 1000): ByteArray {
        val period = nowS / PERIOD_S
        val body = a.deviceTag + InetAddress.getByName(a.host).address +
            ByteBuffer.allocate(3).putShort(a.port.toShort()).put(a.flags.toByte()).array()
        val stream = mac(key, "body", period)
        val encrypted = ByteArray(body.size) { i -> (body[i].toInt() xor stream[i].toInt()).toByte() }
        return MAGIC + byteArrayOf(VERSION) + mac(key, "tag", period, body).copyOf(4) + encrypted
    }

    /** Annonce d'un appareil du groupe, ou null (autre groupe, altérée, trop ancienne). */
    fun decode(key: ByteArray, payload: ByteArray, nowS: Long = System.currentTimeMillis() / 1000): Announcement? {
        if (payload.size != PAYLOAD_BYTES || payload[0] != MAGIC[0] || payload[1] != MAGIC[1] || payload[2] != VERSION) return null
        val signature = payload.copyOfRange(3, 7)
        val encrypted = payload.copyOfRange(7, PAYLOAD_BYTES)
        val current = nowS / PERIOD_S
        for (period in listOf(current, current - 1, current + 1)) {  // horloges légèrement décalées
            val stream = mac(key, "body", period)
            val body = ByteArray(encrypted.size) { i -> (encrypted[i].toInt() xor stream[i].toInt()).toByte() }
            if (MessageDigest.isEqual(signature, mac(key, "tag", period, body).copyOf(4))) {
                val host = (InetAddress.getByAddress(body.copyOfRange(4, 8)) as Inet4Address).hostAddress ?: return null
                val port = ByteBuffer.wrap(body, 8, 2).short.toInt() and 0xffff
                return Announcement(body.copyOfRange(0, 4), host, port, body[10].toInt() and 0xff)
            }
        }
        return null
    }

    /** Ordre de grandeur seulement : le signal varie selon les murs, le corps, l'appareil... */
    fun proximity(rssi: Int) = when {
        rssi >= -55 -> "très proche"
        rssi >= -70 -> "proche"
        else -> "à distance"
    }
}
