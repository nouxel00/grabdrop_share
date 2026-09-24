package io.github.nouxel00.grabdrop

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import io.github.nouxel00.grabdrop.core.Peer
import io.github.nouxel00.grabdrop.core.SERVICE_TYPE
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue

/**
 * Annonce du téléphone et découverte des PC du même groupe (mDNS / DNS-SD via NsdManager),
 * compatible avec grabdrop/network.py : type « _grabdrop._tcp », attributs id / name / group.
 */
class Discovery(
    context: Context,
    private val deviceId: String,
    private val deviceName: String,
    private val groupId: String,
    private val onPeersChanged: (List<Peer>) -> Unit,
) {
    private val nsd = context.getSystemService(NsdManager::class.java)
    private val ownName = "GrabDrop-${deviceId.take(8)}"
    private val peers = ConcurrentHashMap<String, Peer>()
    private val toResolve = LinkedBlockingQueue<NsdServiceInfo>()
    @Volatile private var running = false
    private var registration: NsdManager.RegistrationListener? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    fun peers(): List<Peer> = peers.values.toList()

    fun start(port: Int) {
        running = true
        val info = NsdServiceInfo().apply {
            serviceName = ownName
            serviceType = SERVICE_TYPE
            setPort(port)
            setAttribute("id", deviceId)
            setAttribute("name", deviceName)
            setAttribute("group", groupId)
        }
        registration = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(info: NsdServiceInfo) = Log.i(TAG, "annoncé : ${info.serviceName}").let { }
            override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) = Log.w(TAG, "annonce impossible ($code)").let { }
            override fun onServiceUnregistered(info: NsdServiceInfo) {}
            override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) {}
        }.also { nsd.registerService(info, NsdManager.PROTOCOL_DNS_SD, it) }

        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(info: NsdServiceInfo) {
                if (!info.serviceName.startsWith(ownName)) toResolve.offer(info)
            }
            override fun onServiceLost(info: NsdServiceInfo) {
                if (peers.remove(info.serviceName) != null) onPeersChanged(peers())
            }
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, code: Int) = Log.w(TAG, "découverte impossible ($code)").let { }
            override fun onStopDiscoveryFailed(serviceType: String, code: Int) {}
        }.also { nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, it) }

        // Une résolution à la fois : NsdManager refuse les résolutions simultanées (avant Android 14).
        Thread({ resolveLoop() }, "grabdrop-nsd").apply { isDaemon = true }.start()
    }

    fun stop() {
        running = false
        toResolve.offer(NsdServiceInfo())  // réveille la boucle de résolution
        runCatching { registration?.let(nsd::unregisterService) }
        runCatching { discoveryListener?.let(nsd::stopServiceDiscovery) }
        peers.clear()
    }

    @Suppress("DEPRECATION")
    private fun resolveLoop() {
        while (running) {
            val info = toResolve.take()
            if (!running) break
            val done = Object()
            var resolved: NsdServiceInfo? = null
            nsd.resolveService(info, object : NsdManager.ResolveListener {
                override fun onServiceResolved(result: NsdServiceInfo) {
                    resolved = result
                    synchronized(done) { done.notifyAll() }
                }
                override fun onResolveFailed(info: NsdServiceInfo, code: Int) {
                    synchronized(done) { done.notifyAll() }
                }
            })
            synchronized(done) { done.wait(5000) }
            resolved?.let(::addPeer)
        }
    }

    private fun addPeer(info: NsdServiceInfo) {
        val attrs = info.attributes.mapValues { (_, v) -> v?.decodeToString() ?: "" }
        if (attrs["group"] != groupId || attrs["id"] == deviceId) return
        val address = info.host ?: return
        peers[info.serviceName] = Peer(attrs["id"] ?: "", attrs["name"] ?: info.serviceName, hostString(address), info.port)
        Log.i(TAG, "appareil trouvé : ${attrs["name"]} (${address.hostAddress})")
        onPeersChanged(peers())
    }

    /** IPv6 avec zone (fe80::1%wlan0) : « % » doit être encodé dans une URL. */
    private fun hostString(address: InetAddress): String = when (address) {
        is Inet4Address -> address.hostAddress ?: ""
        is Inet6Address -> (address.hostAddress ?: "").replace("%", "%25")
        else -> address.hostAddress ?: ""
    }

    companion object {
        private const val TAG = "GrabDrop"
    }
}
