package io.github.nouxel00.grabdrop.core

import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.net.InetAddress
import java.util.UUID

/** Plusieurs appareils Kotlin simulés en local. */
class NodeTest {
    private val code = formatGroupCode(randomBytes(16))
    private val nodes = mutableListOf<Node>()

    private fun node(name: String, groupCode: String = code, peers: List<Node> = emptyList()): Node =
        Node(UUID.randomUUID().toString(), name, Channel(parseGroupCode(groupCode)), HeldItem(), 0,
             InetAddress.getLoopbackAddress()).also { n ->
            n.start()
            n.peersProvider = { peers.map { Peer(it.deviceId, it.deviceName, "127.0.0.1", it.port) } }
            nodes += n
        }

    @After fun stop() = nodes.forEach { it.stop() }

    class MemorySink : ReceiveSink {
        val files = linkedMapOf<String, ByteArrayOutputStream>()
        var committed = false; var aborted = false
        override fun openFile(relativePath: String, size: Long): OutputStream = ByteArrayOutputStream().also { files[relativePath] = it }
        override fun commit() { committed = true }
        override fun abort() { aborted = true }
    }

    @Test
    fun filesAndTextBetweenPhones() {
        val a = node("Tel-A"); val b = node("Tel-B", peers = listOf(a))
        val big = randomBytes(3 * CHUNK_BYTES + 5)
        a.held.hold(Item(Kind.FILES, "Vacances", files = listOf(
            FileEntry("Vacances/photo.jpg", big.size.toLong()) { big.inputStream() },
            FileEntry("Vacances/../../evil.txt", 3) { "abc".byteInputStream() },
        )))
        val offer = b.findOffers().single()
        assertEquals("2 fichiers (3,0 Mo)", offer.describe())
        val sink = MemorySink()
        val item = b.claim(offer, sink)!!
        assertTrue(sink.committed)
        assertArrayEquals(big, sink.files["Vacances/photo.jpg"]!!.toByteArray())
        assertEquals(listOf("Vacances/photo.jpg", "Vacances/evil.txt"), item.files.map { it.path })  // chemin assaini
        assertNull(a.held.peek())
        assertEquals(emptyList<Offer>(), b.findOffers())

        a.held.hold(Item(Kind.TEXT, "texte", "text/plain", "Voilà ✓".toByteArray()))
        assertEquals("Voilà ✓", b.claim(b.findOffers().single(), MemorySink())!!.data.decodeToString())
    }

    @Test
    fun strangerRefusedAndFirstClaimWins() {
        val a = node("Tel-A")
        a.held.hold(Item(Kind.TEXT, "t", data = "x".toByteArray()))
        val stranger = node("Intrus", groupCode = formatGroupCode(randomBytes(16)), peers = listOf(a))
        assertEquals(emptyList<Offer>(), stranger.findOffers())
        val b = node("Tel-B", peers = listOf(a)); val c = node("Tel-C", peers = listOf(a))
        val ob = b.findOffers().single(); val oc = c.findOffers().single()
        assertNotNull(b.claim(ob, MemorySink()))
        assertNull(c.claim(oc, MemorySink()))
    }

    @Test
    fun qrParsing() {
        val info = parsePairingQr("grabdrop://pair?v=1&h=192.168.1.10%2C10.0.0.2&p=47800&t=AAAQEAYEAUDAOCAJBIFQYDIOB4&n=Mon+PC")
        assertEquals(listOf("192.168.1.10", "10.0.0.2"), info.hosts)
        assertEquals(47800, info.port)
        assertEquals("Mon PC", info.hostName)
        assertArrayEquals(ByteArray(16) { it.toByte() }, info.token)
        for (bad in listOf("https://example.com", "grabdrop://autre?v=1", "grabdrop://pair?v=2&h=1&p=1&t=AA")) {
            try { parsePairingQr(bad); throw AssertionError(bad) } catch (e: PairingException) { }
        }
    }
}
