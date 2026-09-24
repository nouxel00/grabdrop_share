package io.github.nouxel00.grabdrop

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.SystemClock
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.lifecycle.LifecycleOwner
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.gesturerecognizer.GestureRecognizer
import io.github.nouxel00.grabdrop.core.GestureEvent
import io.github.nouxel00.grabdrop.core.GestureStateMachine
import io.github.nouxel00.grabdrop.core.HandGeometry
import io.github.nouxel00.grabdrop.core.Posture
import java.util.concurrent.Executors

/** Lecture d'une image : ce que l'interface affiche sous l'aperçu. */
data class HandReading(val posture: Posture, val palmFacing: Boolean, val extended: Int, val size: Double)

/**
 * Analyse la caméra frontale (même logique que grabdrop/detector.py) :
 * classifieur MediaPipe + géométrie des doigts, paume face à la caméra, main assez proche.
 */
class GestureAnalyzer(
    context: Context,
    private val onEvent: (GestureEvent) -> Unit,
    private val onReading: (HandReading?) -> Unit,
) : ImageAnalysis.Analyzer {
    private val recognizer: GestureRecognizer = GestureRecognizer.createFromOptions(
        context,
        GestureRecognizer.GestureRecognizerOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath("gesture_recognizer.task").build())
            .setRunningMode(RunningMode.VIDEO)
            .setNumHands(2)
            .build(),
    )
    private val machine = GestureStateMachine()
    private var lastTimestamp = 0L

    override fun analyze(image: ImageProxy) {
        try {
            val bitmap = uprightMirrored(image)
            val now = maxOf(SystemClock.uptimeMillis(), lastTimestamp + 1)  // strictement croissant pour MediaPipe
            lastTimestamp = now
            val reading = detect(bitmap, now)
            onReading(reading)
            machine.update(reading?.posture ?: Posture.NONE, now)?.let(onEvent)
        } catch (e: Exception) {
            Log.w("GrabDrop", "analyse impossible", e)
        } finally {
            image.close()
        }
    }

    fun close() = recognizer.close()

    /** Image remise à l'endroit et en miroir (comme un selfie), ce qu'attend la logique de la paume. */
    private fun uprightMirrored(image: ImageProxy): Bitmap {
        val source = image.toBitmap()
        val matrix = Matrix().apply {
            postRotate(image.imageInfo.rotationDegrees.toFloat())
            postScale(-1f, 1f)
        }
        return Bitmap.createBitmap(source, 0, 0, source.width, source.height, matrix, true)
    }

    private fun detect(bitmap: Bitmap, timestampMs: Long): HandReading? {
        val result = recognizer.recognizeForVideo(BitmapImageBuilder(bitmap).build(), timestampMs)
        if (result.landmarks().isEmpty()) return null
        // Plusieurs mains : la plus grande (la plus proche).
        val best = result.landmarks().indices.maxBy { i ->
            val xs = result.landmarks()[i].map { it.x() }; val ys = result.landmarks()[i].map { it.y() }
            (xs.max() - xs.min()) * (ys.max() - ys.min())
        }
        val points2d = result.landmarks()[best].map { floatArrayOf(it.x(), it.y()) }
        val world = result.worldLandmarks()[best].map { floatArrayOf(it.x(), it.y(), it.z()) }
        val top = result.gestures().getOrNull(best)?.firstOrNull()
        val handedness = result.handedness().getOrNull(best)?.firstOrNull()?.categoryName() ?: "Right"

        val fromClassifier = when {
            top == null || top.score() < MIN_SCORE -> Posture.NONE
            top.categoryName() == "Open_Palm" -> Posture.OPEN
            top.categoryName() == "Closed_Fist" -> Posture.FIST
            else -> Posture.NONE
        }
        var posture = HandGeometry.combine(HandGeometry.postureFromLandmarks(world), fromClassifier)
        val palm = HandGeometry.palmFacingCamera(points2d, handedness)
        if (posture == Posture.OPEN && !palm) posture = Posture.NONE
        val size = HandGeometry.handScale(points2d, bitmap.width, bitmap.height)
        if (size < MIN_HAND_SIZE) posture = Posture.NONE
        return HandReading(posture, palm, HandGeometry.extendedFingers(world), size)
    }

    companion object {
        private const val MIN_SCORE = 0.6f
        private const val MIN_HAND_SIZE = 0.10
    }
}

/** Relie la caméra frontale (aperçu + analyse) au cycle de vie de l'écran. Renvoie de quoi tout arrêter. */
fun bindGestureCamera(
    context: Context,
    owner: LifecycleOwner,
    previewView: PreviewView,
    onEvent: (GestureEvent) -> Unit,
    onReading: (HandReading?) -> Unit,
): () -> Unit {
    val executor = Executors.newSingleThreadExecutor()
    val providerFuture = ProcessCameraProvider.getInstance(context)
    var analyzer: GestureAnalyzer? = null
    var provider: ProcessCameraProvider? = null
    providerFuture.addListener({
        provider = providerFuture.get()
        val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
        val selector = ResolutionSelector.Builder()
            .setResolutionStrategy(ResolutionStrategy(Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
            .build()
        val analysis = ImageAnalysis.Builder()
            .setResolutionSelector(selector)
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
            .build()
        executor.execute {
            val a = GestureAnalyzer(context, onEvent, onReading)  // chargement du modèle hors du thread principal
            analyzer = a
            analysis.setAnalyzer(executor, a)
        }
        runCatching {
            provider?.unbindAll()
            provider?.bindToLifecycle(owner, CameraSelector.DEFAULT_FRONT_CAMERA, preview, analysis)
        }.onFailure { Log.w("GrabDrop", "caméra indisponible", it) }
    }, context.mainExecutor)

    return {
        provider?.unbindAll()
        executor.execute { analyzer?.close() }
        executor.shutdown()
    }
}
