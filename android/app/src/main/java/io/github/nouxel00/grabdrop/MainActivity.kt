package io.github.nouxel00.grabdrop

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import io.github.nouxel00.grabdrop.ui.HomeScreen

class MainActivity : ComponentActivity() {
    private val runtime get() = (application as GrabDropApp).runtime

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handleIntent(intent)
        if (Build.VERSION.SDK_INT >= 33 && !granted(Manifest.permission.POST_NOTIFICATIONS)) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        setContent {
            val blue = Color(0xFF2563EB)
            val scheme = if (isSystemInDarkTheme()) darkColorScheme(primary = Color(0xFF7AA2F7)) else lightColorScheme(primary = blue)
            MaterialTheme(colorScheme = scheme) {
                var cameraGranted by remember { mutableStateOf(granted(Manifest.permission.CAMERA)) }
                val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
                    cameraGranted = it
                }
                val pickPhotos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) {
                    if (it.isNotEmpty()) runtime.shareToHand(it, null)
                }
                val pickFiles = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) {
                    if (it.isNotEmpty()) runtime.shareToHand(it, null)
                }
                HomeScreen(
                    runtime = runtime,
                    hasCameraPermission = cameraGranted,
                    onRequestCamera = { cameraPermission.launch(Manifest.permission.CAMERA) },
                    onScanQr = ::scanQr,
                    onPickPhotos = {
                        pickPhotos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
                    },
                    onPickFiles = { pickFiles.launch(arrayOf("*/*")) },
                )
                // Une seule demande groupée (deux demandes simultanées s'annuleraient) :
                // caméra pour les gestes, Bluetooth pour trouver les appareils proches.
                val startupPermissions = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestMultiplePermissions()
                ) { results ->
                    cameraGranted = granted(Manifest.permission.CAMERA)
                    if (blePermissions().all { results[it] == true || granted(it) }) runtime.startBle()
                }
                val paired by runtime.paired.collectAsState()
                LaunchedEffect(paired) {
                    if (!paired) return@LaunchedEffect
                    val missing = (blePermissions().toList() +
                        listOfNotNull(Manifest.permission.CAMERA.takeIf { runtime.config.gesturesEnabled }))
                        .filterNot(::granted)
                    if (missing.isNotEmpty()) startupPermissions.launch(missing.toTypedArray())
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    /** QR scanné avec l'appareil photo, ou « Partager → GrabDrop » depuis une autre app. */
    private fun handleIntent(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_VIEW -> intent.data?.takeIf { it.scheme == "grabdrop" }?.let { runtime.pairWithQr(it.toString()) }
            Intent.ACTION_SEND -> runtime.shareToHand(listOfNotNull(streamExtra(intent)), intent.getStringExtra(Intent.EXTRA_TEXT))
            Intent.ACTION_SEND_MULTIPLE -> runtime.shareToHand(streamListExtra(intent), null)
        }
    }

    private fun scanQr() {
        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
        GmsBarcodeScanning.getClient(this, options).startScan()
            .addOnSuccessListener { barcode -> barcode.rawValue?.let(runtime::pairWithQr) }
            .addOnFailureListener { runtime.messages.tryEmit("Scanner indisponible : ${it.message}") }
    }

    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    @Suppress("DEPRECATION")
    private fun streamExtra(intent: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun streamListExtra(intent: Intent): List<Uri> =
        (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)) ?: emptyList()
}
