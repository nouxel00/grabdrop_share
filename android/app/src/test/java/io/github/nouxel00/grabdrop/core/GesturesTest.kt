package io.github.nouxel00.grabdrop.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Mêmes scénarios que tests/test_gestures.py et tests/test_hand_geometry.py. */
class GesturesTest {
    private val O = Posture.OPEN
    private val F = Posture.FIST
    private val N = Posture.NONE

    private fun run(sequence: List<Pair<Posture, Int>>, config: GestureConfig = GestureConfig()): List<GestureEvent> {
        val sm = GestureStateMachine(config)
        val events = mutableListOf<GestureEvent>()
        var t = 0L
        for ((posture, duration) in sequence) {
            repeat(duration / 50) {
                sm.update(posture, t)?.let(events::add)
                t += 50
            }
        }
        return events
    }

    @Test fun openThenFistIsGrab() = assertEquals(listOf(GestureEvent.GRAB), run(listOf(O to 600, F to 600)))
    @Test fun fistThenOpenIsDrop() = assertEquals(listOf(GestureEvent.DROP), run(listOf(F to 600, O to 600)))
    @Test fun singlePostureNothing() = assertEquals(emptyList<GestureEvent>(), run(listOf(F to 3000)))
    @Test fun shortPosturesIgnored() = assertEquals(emptyList<GestureEvent>(), run(listOf(O to 600, F to 150, O to 600)))
    @Test fun ambiguousFramesTolerated() = assertEquals(listOf(GestureEvent.GRAB), run(listOf(O to 600, N to 300, F to 600)))
    @Test fun longGapBreaks() = assertEquals(emptyList<GestureEvent>(), run(listOf(O to 600, N to 2000, F to 600)))
    @Test fun quickGrabThenDrop() =
        assertEquals(listOf(GestureEvent.GRAB, GestureEvent.DROP), run(listOf(O to 600, F to 400, O to 600)))
    @Test fun cooldownDelaysNotDrops() {
        val long = GestureConfig(cooldownMs = 1500)
        assertEquals(listOf(GestureEvent.GRAB, GestureEvent.DROP), run(listOf(O to 600, F to 400, O to 2000), long))
        assertEquals(listOf(GestureEvent.GRAB), run(listOf(O to 600, F to 400, O to 500, N to 1500), long))
    }

    // --- géométrie (main synthétique : poignet à l'origine, doigts vers le haut) ---
    private val fingerX = listOf(-0.03f, -0.01f, 0.01f, 0.03f)

    private fun hand(tips: List<Float>): List<FloatArray> {
        val pts = MutableList(21) { floatArrayOf(0f, 0f, 0f) }
        for (i in 1..4) pts[i] = floatArrayOf(-0.04f, -0.03f * i / 4, 0f)
        for (f in 0 until 4) {
            val mcp = 5 + 4 * f; val x = fingerX[f]
            pts[mcp] = floatArrayOf(x, -0.09f, 0f)
            pts[mcp + 1] = floatArrayOf(x, -0.13f, 0f)
            pts[mcp + 2] = floatArrayOf(x, (-0.13f + tips[f]) / 2, 0f)
            pts[mcp + 3] = floatArrayOf(x, tips[f], 0f)
        }
        return pts
    }

    private val open = hand(List(4) { -0.175f })
    private val fist = hand(List(4) { -0.06f })

    @Test
    fun geometry() {
        assertEquals(Posture.OPEN, HandGeometry.postureFromLandmarks(open))
        assertEquals(Posture.FIST, HandGeometry.postureFromLandmarks(fist))
        assertEquals(Posture.NONE, HandGeometry.postureFromLandmarks(hand(List(4) { -0.138f })))
        assertEquals(Posture.NONE, HandGeometry.postureFromLandmarks(hand(listOf(-0.175f, -0.06f, -0.06f, -0.06f))))
        assertEquals(4, HandGeometry.extendedFingers(open))
        assertEquals(Posture.NONE, HandGeometry.combine(O, F))
        assertEquals(F, HandGeometry.combine(N, F))
    }

    @Test
    fun palmOrientation() {
        val mirrored = open.map { floatArrayOf(-it[0], it[1], it[2]) }
        // Image en miroir : MediaPipe étiquette la vraie main droite « Left ».
        assertTrue(HandGeometry.palmFacingCamera(open, "Left"))
        assertFalse(HandGeometry.palmFacingCamera(mirrored, "Left"))
        assertTrue(HandGeometry.palmFacingCamera(mirrored, "Right"))
        val rotated = open.map { floatArrayOf(it[1], -it[0], it[2]) }
        assertTrue(HandGeometry.palmFacingCamera(rotated, "Left"))
    }
}
