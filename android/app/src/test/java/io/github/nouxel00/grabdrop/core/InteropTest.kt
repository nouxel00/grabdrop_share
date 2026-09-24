package io.github.nouxel00.grabdrop.core

import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.OutputStream
import java.net.InetAddress
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * Interopérabilité réelle avec le code Python des PC (tools/interop_peer.py) :
 * transferts dans les deux sens et appairage par QR, sur la boucle locale.
 * Ignoré si l'environnement Python du projet (.venv) est absent.
 */
class InteropTest {
    private fun sha256(data: ByteArray) = MessageDigest.getInstance("SHA-256").digest(data).toHex()

    @Test
    fun kotlinAndPythonUnderstandEachOther() {
        val repo = File(System.getProperty("grabdrop.repo") ?: "../..").absoluteFile
        val python = listOf(".venv/Scripts/python.exe", ".venv/bin/python").map { File(repo, it) }.firstOrNull { it.exists() }
        assumeTrue("environnement Python absent : test ignoré", python != null)

        val code = formatGroupCode(randomBytes(16))
        val process = ProcessBuilder(python!!.path, File(repo, "tools/interop_peer.py").path, code)
            .redirectError(ProcessBuilder.Redirect.INHERIT)
            .apply { environment()["PYTHONIOENCODING"] = "utf-8" }
            .start()
        val stdout = process.inputStream.bufferedReader(Charsets.UTF_8)
        val stdin = process.outputStream.bufferedWriter(Charsets.UTF_8)
        try {
            // 1. Le PC (Python) tient des fichiers : Kotlin les récupère.
            val ready = stdout.readLine().split(" ")
            assertEquals("READY", ready[0])
            val pyPort = ready[1].toInt()
            val expected = ready[2].split(",").associate { it.split(":").let { p -> p[0] to (p[1].toLong() to p[2]) } }
            val qr = ready[3]

            val phone = Node(UUID.randomUUID().toString(), "Téléphone", Channel(parseGroupCode(code)), HeldItem(), 0,
                             InetAddress.getLoopbackAddress())
            phone.start()
            phone.peersProvider = { listOf(Peer("", "PC-Python", "127.0.0.1", pyPort)) }
            val offer = phone.findOffers().single()
            assertEquals("PC-Python", offer.deviceName)
            val received = linkedMapOf<String, ByteArrayOutputStream>()
            val sink = object : ReceiveSink {
                override fun openFile(relativePath: String, size: Long): OutputStream = ByteArrayOutputStream().also { received[relativePath] = it }
                override fun commit() {}
                override fun abort() {}
            }
            val item = phone.claim(offer, sink)!!
            assertEquals(Kind.FILES, item.kind)
            assertEquals(expected.keys, received.keys)
            for ((path, bytes) in received) {
                assertEquals(expected.getValue(path).first, bytes.size().toLong())
                assertEquals(expected.getValue(path).second, sha256(bytes.toByteArray()))
            }

            // 2. Appairage par QR avec le PC Python.
            val joined = joinWithQr(parsePairingQr(qr), phone.deviceId, "Téléphone", phone.port)
            assertEquals(code, joined.groupCode)

            // 3. Le téléphone (Kotlin) tient des fichiers : Python les récupère.
            val photo = randomBytes(1_300_000)
            val caption = "Été 2026".toByteArray()  // 10 octets en UTF-8
            phone.held.hold(Item(Kind.FILES, "DCIM", files = listOf(
                FileEntry("DCIM/IMG_0001.jpg", photo.size.toLong()) { photo.inputStream() },
                FileEntry("DCIM/légende.txt", caption.size.toLong()) { caption.inputStream() },
            )))
            stdin.write("YOUR_TURN ${phone.port}\n"); stdin.flush()
            val result = stdout.readLine().split(" ")
            assertEquals("RESULT", result[0])
            assertEquals(Kind.FILES, result[1])
            val got = result[2].split(",").associate { it.split(":").let { p -> p[0] to (p[1].toLong() to p[2]) } }
            assertEquals(photo.size.toLong() to sha256(photo), got["DCIM/IMG_0001.jpg"])
            assertEquals(caption.size.toLong() to sha256(caption), got["DCIM/légende.txt"])
            assertEquals("PAIRED=Téléphone", result[4])
            assertEquals("GUEST=127.0.0.1:${phone.port}", result[5])  // le PC retient l'adresse du téléphone
            assertEquals(0, process.waitFor().also { phone.stop() })
        } finally {
            if (!process.waitFor(10, TimeUnit.SECONDS)) process.destroyForcibly()
        }
    }
}
