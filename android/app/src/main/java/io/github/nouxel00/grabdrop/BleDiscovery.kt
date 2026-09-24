package io.github.nouxel00.grabdrop

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import io.github.nouxel00.grabdrop.core.Ble
import io.github.nouxel00.grabdrop.core.Peer
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.ConcurrentHashMap

/** Appareil du groupe entendu en Bluetooth. */
data class BlePeer(val announcement: Ble.Announcement, val rssi: Int, val lastSeenMs: Long)

/**
 * Découverte par Bluetooth basse consommation (voir core/Ble.kt et grabdrop/ble.py) :
 * diffuse l'annonce du téléphone et écoute celles du groupe. Le transfert passe par le Wi-Fi.
 * Les permissions (BLUETOOTH_SCAN / BLUETOOTH_ADVERTISE) sont vérifiées par l'appelant.
 */
@SuppressLint("MissingPermission")
class BleDiscovery(
    context: Context,
    private var key: ByteArray,
    private val deviceId: String,
    private val port: Int,
    private val onChanged: () -> Unit,
) {
    private val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
    private val peers = ConcurrentHashMap<String, BlePeer>()
    private val handler = Handler(Looper.getMainLooper())
    private val ownTag = Ble.deviceTag(deviceId)
    @Volatile private var holding = false
    @Volatile var status = "arrêté"
        private set

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
            Log.i(TAG, "annonce Bluetooth active")
        }
        override fun onStartFailure(errorCode: Int) {
            Log.w(TAG, "annonce Bluetooth impossible ($errorCode)")
        }
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val payload = result.scanRecord?.getManufacturerSpecificData(Ble.COMPANY_ID) ?: return
            val announcement = Ble.decode(key, payload) ?: return
            if (announcement.deviceTag.contentEquals(ownTag)) return
            val isNew = !peers.containsKey(announcement.tagHex)
            peers[announcement.tagHex] = BlePeer(announcement, result.rssi, System.currentTimeMillis())
            if (isNew) {
                Log.i(TAG, "Bluetooth : appareil du groupe entendu (${announcement.host}:${announcement.port}, ${result.rssi} dBm)")
                onChanged()
            }
        }
        override fun onScanFailed(errorCode: Int) {
            Log.w(TAG, "détection Bluetooth impossible ($errorCode)")
        }
    }

    /** Nouvelle période (clé tournante) ou changement d'état : l'annonce est republiée. */
    private val refresh = object : Runnable {
        override fun run() {
            restartAdvertising()
            handler.postDelayed(this, Ble.PERIOD_S * 1000 / 2)
        }
    }

    fun start() {
        val a = adapter
        if (a == null || !a.isEnabled) {
            status = "Bluetooth désactivé"
            return
        }
        // Filtre matériel : seules les annonces commençant par « GD » réveillent l'app.
        val filter = ScanFilter.Builder()
            .setManufacturerData(Ble.COMPANY_ID, byteArrayOf('G'.code.toByte(), 'D'.code.toByte()), byteArrayOf(-1, -1))
            .build()
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        runCatching { a.bluetoothLeScanner?.startScan(listOf(filter), settings, scanCallback) }
            .onFailure { Log.w(TAG, "détection Bluetooth impossible", it) }
        handler.post(refresh)
        status = "actif"
    }

    fun stop() {
        handler.removeCallbacks(refresh)
        runCatching { adapter?.bluetoothLeScanner?.stopScan(scanCallback) }
        runCatching { adapter?.bluetoothLeAdvertiser?.stopAdvertising(advertiseCallback) }
        peers.clear()
        status = "arrêté"
    }

    fun setHolding(value: Boolean) {
        if (value == holding) return
        holding = value
        handler.post { restartAdvertising() }
    }

    fun setKey(newKey: ByteArray) {
        key = newKey
        peers.clear()
        handler.post { restartAdvertising() }
    }

    /** Appareils du groupe entendus depuis moins de 20 s, du plus proche au plus lointain. */
    fun peers(): List<BlePeer> {
        val now = System.currentTimeMillis()
        peers.entries.removeIf { now - it.value.lastSeenMs > PEER_TTL_MS }
        return peers.values.sortedByDescending { it.rssi }
    }

    fun asNetworkPeers(): List<Peer> = peers().map {
        Peer("", "appareil proche (${it.announcement.host})", it.announcement.host, it.announcement.port)
    }

    private fun restartAdvertising() {
        val advertiser = adapter?.takeIf { it.isEnabled }?.bluetoothLeAdvertiser ?: return
        val host = wifiAddress() ?: return  // sans Wi-Fi, rien d'utile à annoncer
        val flags = Ble.FLAG_PHONE or (if (holding) Ble.FLAG_HOLDING else 0)
        val payload = Ble.encode(key, Ble.Announcement(ownTag, host, port, flags))
        runCatching { advertiser.stopAdvertising(advertiseCallback) }
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
            .setConnectable(false)
            .build()
        val data = AdvertiseData.Builder().addManufacturerData(Ble.COMPANY_ID, payload).build()
        runCatching { advertiser.startAdvertising(settings, data, advertiseCallback) }
            .onFailure { Log.w(TAG, "annonce Bluetooth impossible", it) }
    }

    companion object {
        private const val TAG = "GrabDrop"
        private const val PEER_TTL_MS = 20_000L

        /** Adresse IPv4 du téléphone sur le Wi-Fi (ou sur son partage de connexion). */
        fun wifiAddress(): String? {
            val candidates = NetworkInterface.getNetworkInterfaces().toList()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { nif -> nif.inetAddresses.toList().filterIsInstance<Inet4Address>().map { nif.name to it } }
                .filter { (_, addr) -> addr.isSiteLocalAddress }
            val preferred = listOf("wlan", "swlan", "ap", "softap")
            return (preferred.firstNotNullOfOrNull { prefix -> candidates.firstOrNull { it.first.startsWith(prefix) } }
                ?: candidates.firstOrNull())?.second?.hostAddress
        }
    }
}

/** Autorisations nécessaires à la découverte Bluetooth, selon la version d'Android. */
fun blePermissions(): Array<String> =
    if (android.os.Build.VERSION.SDK_INT >= 31) {
        arrayOf(android.Manifest.permission.BLUETOOTH_SCAN, android.Manifest.permission.BLUETOOTH_ADVERTISE)
    } else {
        arrayOf(android.Manifest.permission.ACCESS_FINE_LOCATION)  // Android 10-11 : exigée pour détecter en BLE
    }

fun hasBlePermissions(context: Context): Boolean = blePermissions().all {
    context.checkSelfPermission(it) == android.content.pm.PackageManager.PERMISSION_GRANTED
}
