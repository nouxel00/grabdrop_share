package io.github.nouxel00.grabdrop.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.Base64

class CryptoTest {
    // Vecteurs produits par le code Python (grabdrop/crypto.py) : garantissent la compatibilité.
    private val secret = ByteArray(16) { it.toByte() }
    private val pythonCode = "AAAQ-EAYE-AUDA-OCAJ-BIFQ-YDIO-B4"

    @Test
    fun groupCodeMatchesPython() {
        assertEquals(pythonCode, formatGroupCode(secret))
        assertArrayEquals(secret, parseGroupCode(pythonCode))
        assertArrayEquals(secret, parseGroupCode(pythonCode.lowercase().replace("-", " ")))
        assertArrayEquals(secret, parseGroupCode(pythonCode.replace("O", "0")))
        assertThrows(IllegalArgumentException::class.java) { parseGroupCode("ABCD-EFGH") }
        assertThrows(IllegalArgumentException::class.java) { parseGroupCode("!!!!") }
    }

    @Test
    fun hkdfAndGroupIdMatchPython() {
        assertEquals("aefa6113fa77", Channel(secret).groupId)
        assertEquals(
            "fc14aa524f0599e1ceff71f6ca550323d199ddac0e51c80862a49d481b31be351a8be88fd8200bef",
            Hkdf.derive("abc".toByteArray(), "label".toByteArray(), 40).toHex(),
        )
    }

    @Test
    fun opensMessageSealedByPython() {
        val blob = Base64.getDecoder().decode("JdtKikd0AXGvt+g6lJPTouj/z+QZm2HLLuCA5EEcwt7nsmLh1G3f")
        assertEquals("Bonjour ✓", Channel(secret).open(blob, "/v1/offer".toByteArray()).decodeToString())
        assertThrows(CryptoException::class.java) { Channel(secret).open(blob, "/v1/claim".toByteArray()) }
    }

    @Test
    fun sealOpenRoundtripAndTampering() {
        val ch = Channel(secret)
        val blob = ch.seal("secret".toByteArray(), "ctx".toByteArray())
        assertEquals("secret", ch.open(blob, "ctx".toByteArray()).decodeToString())
        val tampered = blob.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 1).toByte() }
        assertThrows(CryptoException::class.java) { ch.open(tampered, "ctx".toByteArray()) }
        assertThrows(CryptoException::class.java) { Channel(ByteArray(16)).open(blob, "ctx".toByteArray()) }
        assertThrows(CryptoException::class.java) { ch.open(ByteArray(5), "ctx".toByteArray()) }
    }

    private fun sealed(data: ByteArray, pieces: Int = 7): ByteArray {
        val out = ByteArrayOutputStream()
        val sealer = StreamSealer(Channel(secret), "ctx".toByteArray(), out)
        val step = maxOf(1, data.size / pieces)
        var i = 0
        while (i < data.size) {
            sealer.write(data, i, minOf(step, data.size - i)); i += step
        }
        sealer.close()
        return out.toByteArray()
    }

    @Test
    fun streamRoundtrip() {
        for (size in listOf(0, 10, CHUNK_BYTES, CHUNK_BYTES + 1, 3 * CHUNK_BYTES + 12345)) {
            val data = randomBytes(size)
            val opener = StreamOpener(Channel(secret), "ctx".toByteArray(), ByteArrayInputStream(sealed(data)))
            val got = ByteArrayOutputStream()
            while (got.size() < size) got.write(opener.readSome(100_000))
            opener.finish()
            assertArrayEquals(data, got.toByteArray())
        }
    }

    @Test
    fun streamTruncatedOrReordered() {
        val data = randomBytes(2 * CHUNK_BYTES + 10)
        val blob = sealed(data)
        fun readAll(raw: ByteArray) = StreamOpener(Channel(secret), "ctx".toByteArray(), ByteArrayInputStream(raw)).run {
            readExact(data.size); finish()
        }
        readAll(blob)
        assertThrows(CryptoException::class.java) { readAll(blob.copyOf(blob.size - 1)) }
        val firstFrame = 5 + java.nio.ByteBuffer.wrap(blob, 0, 4).int
        assertThrows(CryptoException::class.java) { readAll(blob.copyOfRange(firstFrame, blob.size)) }
    }

    @Test
    fun base32Roundtrip() {
        for (n in 0..40) {
            val data = randomBytes(n)
            assertArrayEquals(data, Base32.decode(Base32.encode(data)))
        }
    }
}
