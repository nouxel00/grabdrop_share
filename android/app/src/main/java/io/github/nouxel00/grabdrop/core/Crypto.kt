package io.github.nouxel00.grabdrop.core

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.security.SecureRandom
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Chiffrement des échanges, identique à grabdrop/crypto.py (côté PC).
 *
 * Clé du groupe : 16 octets, saisis sous forme de code base32. Chaque message est
 * chiffré et authentifié en AES-256-GCM avec une clé dérivée (HKDF-SHA256).
 */
class CryptoException(message: String) : Exception(message)

const val SECRET_BYTES = 16
const val NONCE_BYTES = 12
const val TAG_BYTES = 16
const val CHUNK_BYTES = 1 shl 20

private val random = SecureRandom()

fun randomBytes(n: Int): ByteArray = ByteArray(n).also { random.nextBytes(it) }

object Hkdf {
    /** HKDF-SHA256 sans sel (sel = 32 zéros), comme `cryptography` avec salt=None. */
    fun derive(ikm: ByteArray, info: ByteArray, length: Int): ByteArray {
        val prk = hmacSha256(ByteArray(32), ikm)
        val out = ByteArrayOutputStream()
        var previous = ByteArray(0)
        var counter = 1
        while (out.size() < length) {
            previous = hmacSha256(prk, previous + info + byteArrayOf(counter.toByte()))
            out.write(previous)
            counter++
        }
        return out.toByteArray().copyOf(length)
    }
}

fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray =
    Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key, "HmacSHA256"))
        doFinal(data)
    }

fun aesGcmEncrypt(key: ByteArray, nonce: ByteArray, plaintext: ByteArray, aad: ByteArray): ByteArray =
    Cipher.getInstance("AES/GCM/NoPadding").run {
        init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BYTES * 8, nonce))
        updateAAD(aad)
        doFinal(plaintext)
    }

fun aesGcmDecrypt(key: ByteArray, nonce: ByteArray, ciphertext: ByteArray, aad: ByteArray): ByteArray =
    try {
        Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BYTES * 8, nonce))
            updateAAD(aad)
            doFinal(ciphertext)
        }
    } catch (e: AEADBadTagException) {
        throw CryptoException("message non authentifié")
    }

/** « abcd efgh-… » -> 16 octets. Tolère minuscules, espaces, tirets, et 0/1/8 tapés pour O/I/B. */
fun parseGroupCode(code: String): ByteArray {
    val cleaned = code.uppercase().filter { it.isLetterOrDigit() }
        .map { when (it) { '0' -> 'O'; '1' -> 'I'; '8' -> 'B'; else -> it } }
        .joinToString("")
    val secret = try {
        Base32.decode(cleaned)
    } catch (e: IllegalArgumentException) {
        throw IllegalArgumentException("code de groupe invalide")
    }
    require(secret.size == SECRET_BYTES) { "code de groupe invalide (longueur incorrecte)" }
    return secret
}

fun formatGroupCode(secret: ByteArray): String =
    Base32.encode(secret).chunked(4).joinToString("-")

/** Canal chiffré partagé par tous les appareils du groupe. */
class Channel(secret: ByteArray) {
    private val key = Hkdf.derive(secret, "grabdrop v1 key".toByteArray(), 32)

    /** Identifiant public du groupe, annoncé sur le réseau (ne révèle rien du secret). */
    val groupId: String = Hkdf.derive(secret, "grabdrop v1 group".toByteArray(), 6).toHex()

    fun seal(plaintext: ByteArray, context: ByteArray): ByteArray {
        val nonce = randomBytes(NONCE_BYTES)
        return nonce + aesGcmEncrypt(key, nonce, plaintext, context)
    }

    fun open(blob: ByteArray, context: ByteArray): ByteArray {
        if (blob.size < NONCE_BYTES + TAG_BYTES) throw CryptoException("message trop court")
        return aesGcmDecrypt(key, blob.copyOfRange(0, NONCE_BYTES), blob.copyOfRange(NONCE_BYTES, blob.size), context)
    }
}

// --- Flux chiffrés (voir crypto.py) ------------------------------------------------
// Trame : longueur (4 octets) + drapeau « dernier » (1 octet) + morceau chiffré.
// Le numéro du morceau et le drapeau sont authentifiés (contexte AES-GCM).

private fun chunkContext(context: ByteArray, index: Long, last: Boolean): ByteArray =
    context + ByteBuffer.allocate(9).putLong(index).put(if (last) 1 else 0).array()

class StreamSealer(private val channel: Channel, private val context: ByteArray, private val out: OutputStream) {
    private val buffer = ByteArrayOutputStream()
    private var index = 0L

    fun write(data: ByteArray, offset: Int = 0, length: Int = data.size) {
        buffer.write(data, offset, length)
        while (buffer.size() > CHUNK_BYTES) {
            val all = buffer.toByteArray()
            emit(all.copyOfRange(0, CHUNK_BYTES), last = false)
            buffer.reset()
            buffer.write(all, CHUNK_BYTES, all.size - CHUNK_BYTES)
        }
    }

    fun close() {
        emit(buffer.toByteArray(), last = true)
        buffer.reset()
        out.flush()
    }

    private fun emit(chunk: ByteArray, last: Boolean) {
        val sealed = channel.seal(chunk, chunkContext(context, index, last))
        out.write(ByteBuffer.allocate(5).putInt(sealed.size).put(if (last) 1 else 0).array())
        out.write(sealed)
        index++
    }
}

class StreamOpener(private val channel: Channel, private val context: ByteArray, private val input: InputStream) {
    private var buffer = ByteArray(0)
    private var position = 0
    private var index = 0L
    private var finished = false

    private val available get() = buffer.size - position

    fun readExact(n: Int): ByteArray {
        val out = ByteArrayOutputStream(n)
        var remaining = n
        while (remaining > 0) {
            if (available == 0) {
                if (finished) throw CryptoException("flux plus court qu'annoncé")
                nextChunk()
                continue
            }
            val take = minOf(remaining, available)
            out.write(buffer, position, take)
            position += take
            remaining -= take
        }
        return out.toByteArray()
    }

    /** Jusqu'à [maxBytes] octets (au moins 1 si le flux n'est pas fini). */
    fun readSome(maxBytes: Int): ByteArray {
        while (available == 0) {
            if (finished) throw CryptoException("flux plus court qu'annoncé")
            nextChunk()
        }
        return readExact(minOf(maxBytes, available))
    }

    fun finish() {
        while (!finished) nextChunk()
        if (available > 0) throw CryptoException("données inattendues en fin de flux")
    }

    private fun nextChunk() {
        val header = ByteBuffer.wrap(readRaw(5))
        val length = header.int
        val last = header.get().toInt()
        if (length < 0 || length > CHUNK_BYTES + NONCE_BYTES + TAG_BYTES || last > 1) throw CryptoException("trame invalide")
        buffer = channel.open(readRaw(length), chunkContext(context, index, last == 1))
        position = 0
        index++
        finished = last == 1
    }

    private var rawBytes = 0L

    private fun readRaw(n: Int): ByteArray {
        val data = ByteArray(n)
        var read = 0
        while (read < n) {
            val r = input.read(data, read, n - read)
            if (r < 0) throw CryptoException("flux interrompu après $rawBytes octets, morceau n°$index")
            read += r
            rawBytes += r
        }
        return data
    }
}

object Base32 {
    private const val ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

    fun encode(data: ByteArray): String {
        val sb = StringBuilder()
        var buffer = 0
        var bits = 0
        for (b in data) {
            buffer = (buffer shl 8) or (b.toInt() and 0xff)
            bits += 8
            while (bits >= 5) {
                sb.append(ALPHABET[(buffer shr (bits - 5)) and 31])
                bits -= 5
            }
        }
        if (bits > 0) sb.append(ALPHABET[(buffer shl (5 - bits)) and 31])
        return sb.toString()
    }

    fun decode(text: String): ByteArray {
        val out = ByteArrayOutputStream()
        var buffer = 0
        var bits = 0
        for (c in text.trimEnd('=')) {
            val v = ALPHABET.indexOf(c)
            require(v >= 0) { "caractère base32 invalide : $c" }
            buffer = (buffer shl 5) or v
            bits += 5
            if (bits >= 8) {
                out.write((buffer shr (bits - 8)) and 0xff)
                bits -= 8
            }
        }
        return out.toByteArray()
    }
}

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
