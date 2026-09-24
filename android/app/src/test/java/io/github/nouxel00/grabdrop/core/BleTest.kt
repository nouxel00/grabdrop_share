package io.github.nouxel00.grabdrop.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Vecteurs produits par grabdrop/ble.py : le téléphone et les PC se comprennent en Bluetooth. */
class BleTest {
    private val key = Ble.key(ByteArray(16) { it.toByte() })
    private val now = 1_790_000_000L
    private val announcement = Ble.Announcement(
        Ble.deviceTag("9587922337d6410a82f60f5b9511f920"), "192.168.1.42", 47800, Ble.FLAG_HOLDING or Ble.FLAG_PHONE,
    )
    private val pythonPayload = "474401d556fa805b8c1c76ffeb01e2e4c466"

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    @Test
    fun keyAndPayloadMatchPython() {
        assertEquals("385daa77d2b51e7f95acc23cc0c6ec62c8ff592489659d59fe37af2323be1153", key.toHex())
        assertEquals(pythonPayload, Ble.encode(key, announcement, now).toHex())
    }

    @Test
    fun decodesPythonAnnouncement() {
        val got = Ble.decode(key, hex(pythonPayload), now)!!
        assertEquals(announcement, got)
        assertTrue(got.holding && got.isPhone)
        assertArrayEquals(hex("95879223"), got.deviceTag)
    }

    @Test
    fun rejectsOtherGroupTamperingAndOldAnnouncements() {
        val payload = Ble.encode(key, announcement, now)
        assertNull(Ble.decode(Ble.key(ByteArray(16)), payload, now))
        assertNull(Ble.decode(key, payload.copyOf().also { it[10] = (it[10].toInt() xor 1).toByte() }, now))
        assertNull(Ble.decode(key, payload.copyOf(17), now))
        assertEquals(announcement, Ble.decode(key, payload, now + Ble.PERIOD_S))
        assertNull(Ble.decode(key, payload, now + 3 * Ble.PERIOD_S))
    }

    @Test
    fun proximityLabels() {
        assertEquals("très proche", Ble.proximity(-45))
        assertEquals("proche", Ble.proximity(-65))
        assertEquals("à distance", Ble.proximity(-85))
    }
}
