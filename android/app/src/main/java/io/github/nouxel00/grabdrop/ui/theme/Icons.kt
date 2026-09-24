package io.github.nouxel00.grabdrop.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathBuilder
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/**
 * Icônes de GrabDrop, dessinées pour l'app (même style que le logo) :
 * rendu identique sur tous les téléphones, contrairement aux émojis.
 * Grille 24 × 24 ; la couleur vient de l'Icon qui les affiche.
 */
object GdIcons {
    val HandOpen by lazy { filled("main ouverte") { hand(open = true) } }
    val Fist by lazy { filled("poing") { hand(open = false) } }
    val Photo by lazy {
        outlined("photos") {
            roundRect(3f, 5f, 21f, 19f, 3f)
            moveTo(6.5f, 16f); lineTo(10f, 11.5f); lineTo(13f, 14.5f); lineTo(15f, 12.5f); lineTo(18f, 16f)
            moveTo(16.8f, 8.6f); arcToRelative(0.9f, 0.9f, 0f, true, true, -1.8f, 0f); arcToRelative(0.9f, 0.9f, 0f, true, true, 1.8f, 0f)
        }
    }
    val Folder by lazy {
        outlined("fichiers") {
            moveTo(3f, 8f); arcTo(2f, 2f, 0f, false, true, 5f, 6f); lineTo(9.5f, 6f); lineTo(11.5f, 8f); lineTo(19f, 8f)
            arcTo(2f, 2f, 0f, false, true, 21f, 10f); lineTo(21f, 17f); arcTo(2f, 2f, 0f, false, true, 19f, 19f)
            lineTo(5f, 19f); arcTo(2f, 2f, 0f, false, true, 3f, 17f); close()
        }
    }
    val Receive by lazy {
        outlined("recevoir") {
            moveTo(12f, 3.5f); lineTo(12f, 14f)
            moveTo(7.5f, 9.5f); lineTo(12f, 14f); lineTo(16.5f, 9.5f)
            moveTo(4f, 15.5f); lineTo(4f, 18f); arcTo(2f, 2f, 0f, false, false, 6f, 20f); lineTo(18f, 20f)
            arcTo(2f, 2f, 0f, false, false, 20f, 18f); lineTo(20f, 15.5f)
        }
    }
    val Bluetooth by lazy {
        outlined("Bluetooth") {
            moveTo(6.5f, 7.5f); lineTo(17f, 16.5f); lineTo(12f, 21f); lineTo(12f, 3f); lineTo(17f, 7.5f); lineTo(6.5f, 16.5f)
        }
    }
    val Laptop by lazy {
        outlined("PC") {
            roundRect(4.5f, 5f, 19.5f, 15.5f, 1.8f)
            moveTo(2.5f, 19f); lineTo(21.5f, 19f)
        }
    }
    val Qr by lazy {
        ImageVector.Builder("QR code", 24.dp, 24.dp, 24f, 24f).apply {
            val stroke = SolidColor(Color.Black)
            for ((x, y) in listOf(3f to 3f, 14f to 3f, 3f to 14f)) {
                path(stroke = stroke, strokeLineWidth = 2f, strokeLineJoin = StrokeJoin.Round) {
                    roundRect(x + 1f, y + 1f, x + 6f, y + 6f, 1.5f)
                }
                path(fill = stroke) { roundRect(x + 2.6f, y + 2.6f, x + 4.4f, y + 4.4f, 0.4f) }
            }
            path(fill = stroke) {
                for ((x, y) in listOf(14f to 14f, 18f to 14f, 16f to 16.5f, 14f to 19f, 19f to 19f)) roundRect(x, y, x + 2f, y + 2f, 0.4f)
            }
        }.build()
    }
    val Check by lazy { outlined("fait") { moveTo(5f, 12.5f); lineTo(9.5f, 17f); lineTo(19f, 7.5f) } }
    val Chevron by lazy { outlined("puis") { moveTo(9.5f, 6f); lineTo(15.5f, 12f); lineTo(9.5f, 18f) } }
    val Text by lazy {
        outlined("texte") {
            moveTo(5f, 6.5f); lineTo(19f, 6.5f)
            moveTo(5f, 11f); lineTo(19f, 11f)
            moveTo(5f, 15.5f); lineTo(14f, 15.5f)
        }
    }
    val Send by lazy {
        outlined("envoyer") {
            moveTo(12f, 20f); lineTo(12f, 5f)
            moveTo(6.5f, 10.5f); lineTo(12f, 5f); lineTo(17.5f, 10.5f)
        }
    }

    // --- outils de dessin ---------------------------------------------------------------

    private fun filled(name: String, block: PathBuilder.() -> Unit) =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            path(fill = SolidColor(Color.Black), pathBuilder = block)
        }.build()

    private fun outlined(name: String, block: PathBuilder.() -> Unit) =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            path(
                stroke = SolidColor(Color.Black), strokeLineWidth = 2f,
                strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round, pathBuilder = block,
            )
        }.build()

    private fun PathBuilder.roundRect(l: Float, t: Float, r: Float, b: Float, rad: Float) {
        moveTo(l + rad, t); lineTo(r - rad, t); arcTo(rad, rad, 0f, false, true, r, t + rad)
        lineTo(r, b - rad); arcTo(rad, rad, 0f, false, true, r - rad, b)
        lineTo(l + rad, b); arcTo(rad, rad, 0f, false, true, l, b - rad)
        lineTo(l, t + rad); arcTo(rad, rad, 0f, false, true, l + rad, t); close()
    }

    /** Main du logo : paume, quatre doigts et pouce ; repliés pour le poing. */
    private fun PathBuilder.hand(open: Boolean) {
        if (open) {
            roundRect(6.2f, 11f, 18.2f, 21.5f, 3.4f)  // paume
            listOf(6.2f to 5f, 9.3f to 3f, 12.4f to 4f, 15.5f to 6.5f).forEach { (x, top) ->
                roundRect(x, top, x + 2.7f, 14f, 1.35f)
            }
            roundRect(2.5f, 11.2f, 8.5f, 14.4f, 1.6f)  // pouce
        } else {
            roundRect(5.5f, 8.5f, 18.5f, 20.5f, 3.6f)  // poing
            listOf(5.5f, 8.8f, 12.1f, 15.4f).forEach { x -> roundRect(x, 6.2f, x + 3.1f, 10.5f, 1.55f) }  // phalanges
        }
    }
}
