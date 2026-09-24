package io.github.nouxel00.grabdrop.core

import kotlin.math.hypot
import kotlin.math.sqrt

/**
 * Détection des gestes, identique à grabdrop/gestures.py et grabdrop/hand_geometry.py.
 *
 * GRAB : main ouverte (stable) -> poing (tenu). DROP : poing (stable) -> main ouverte (tenue).
 */
enum class Posture { OPEN, FIST, NONE }

enum class GestureEvent { GRAB, DROP }

data class GestureConfig(val holdMs: Long = 300, val transitionMs: Long = 800, val cooldownMs: Long = 600)

class GestureStateMachine(private val config: GestureConfig = GestureConfig()) {
    private var current = Posture.NONE
    private var currentSince = 0L
    var stablePosture = Posture.NONE
        private set
    private var stableLastSeen = 0L
    private var lastEventAt: Long? = null

    fun update(posture: Posture, nowMs: Long): GestureEvent? {
        if (posture != current) {
            current = posture
            currentSince = nowMs
        }
        if (posture == Posture.NONE) return null
        if (posture == stablePosture) {
            stableLastSeen = nowMs
            return null
        }
        if (nowMs - currentSince < config.holdMs) return null

        val previous = stablePosture
        val gap = currentSince - stableLastSeen
        val isTransition = previous != Posture.NONE && gap <= config.transitionMs
        val inCooldown = lastEventAt?.let { nowMs - it < config.cooldownMs } ?: false
        if (isTransition && inCooldown) return null  // retardé, pas perdu

        stablePosture = posture
        stableLastSeen = nowMs
        if (!isTransition) return null
        lastEventAt = nowMs
        return if (posture == Posture.FIST) GestureEvent.GRAB else GestureEvent.DROP
    }
}

/** Calculs sur les 21 points MediaPipe (0 = poignet, 5/9/17 = bases index/majeur/auriculaire). */
object HandGeometry {
    private const val WRIST = 0
    private const val INDEX_MCP = 5
    private const val MIDDLE_MCP = 9
    private const val PINKY_MCP = 17
    private val FINGERS = listOf(6 to 8, 10 to 12, 14 to 16, 18 to 20)  // (PIP, bout), pouce ignoré
    private const val EXTENDED_RATIO = 1.15
    private const val CURLED_RATIO = 0.9

    private fun dist(a: FloatArray, b: FloatArray): Double {
        var s = 0.0
        for (i in a.indices) s += (a[i] - b[i]).toDouble().let { it * it }
        return sqrt(s)
    }

    fun fingerRatios(points: List<FloatArray>): List<Double> =
        FINGERS.map { (pip, tip) -> dist(points[WRIST], points[tip]) / maxOf(dist(points[WRIST], points[pip]), 1e-6) }

    fun extendedFingers(points: List<FloatArray>) = fingerRatios(points).count { it > EXTENDED_RATIO }

    fun postureFromLandmarks(points: List<FloatArray>): Posture {
        val ratios = fingerRatios(points)
        val extended = ratios.count { it > EXTENDED_RATIO }
        val curled = ratios.count { it < CURLED_RATIO }
        return when {
            extended == 4 -> Posture.OPEN
            extended == 0 && curled >= 3 -> Posture.FIST
            else -> Posture.NONE
        }
    }

    fun combine(geometric: Posture, classifier: Posture): Posture = when {
        classifier == Posture.NONE || geometric == classifier -> geometric
        geometric == Posture.NONE -> classifier
        else -> Posture.NONE
    }

    /**
     * Paume face à la caméra ? Image en miroir ; [handedness] tel que renvoyé par MediaPipe
     * (qui, sur une image en miroir, étiquette la vraie main droite « Left »).
     */
    fun palmFacingCamera(points2d: List<FloatArray>, handedness: String): Boolean {
        val w = points2d[WRIST]
        val ax = points2d[INDEX_MCP][0] - w[0]; val ay = points2d[INDEX_MCP][1] - w[1]
        val bx = points2d[PINKY_MCP][0] - w[0]; val by = points2d[PINKY_MCP][1] - w[1]
        val cross = ax * by - ay * bx
        val isRealRightHand = handedness == "Left"
        return (cross > 0) == isRealRightHand
    }

    /** Taille apparente de la paume (poignet -> base du majeur), en fraction de la hauteur d'image. */
    fun handScale(points2d: List<FloatArray>, width: Int, height: Int): Double {
        val a = points2d[WRIST]; val b = points2d[MIDDLE_MCP]
        return hypot(((b[0] - a[0]) * width).toDouble(), ((b[1] - a[1]) * height).toDouble()) / height
    }
}
