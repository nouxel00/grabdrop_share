package io.github.nouxel00.grabdrop.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import io.github.nouxel00.grabdrop.R

// --- Police : Plus Jakarta Sans (fichier variable, graisses 200 à 800) ------------------

@OptIn(ExperimentalTextApi::class)
private fun jakarta(weight: Int) = Font(
    R.font.plus_jakarta_sans,
    weight = FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight)),
)

val Jakarta = FontFamily(jakarta(400), jakarta(500), jakarta(600), jakarta(700), jakarta(800))

private fun style(size: Int, weight: Int, line: Int, spacing: Double = 0.0) = TextStyle(
    fontFamily = Jakarta,
    fontWeight = FontWeight(weight),
    fontSize = size.sp,
    lineHeight = line.sp,
    letterSpacing = spacing.em,
)

private val GrabDropTypography = Typography(
    displaySmall = style(34, 800, 40, -0.02),
    headlineMedium = style(28, 800, 34, -0.02),
    headlineSmall = style(24, 700, 30, -0.015),
    titleLarge = style(21, 700, 28, -0.01),
    titleMedium = style(17, 700, 24, -0.005),
    titleSmall = style(15, 600, 20),
    bodyLarge = style(16, 400, 24),
    bodyMedium = style(15, 400, 22),
    bodySmall = style(13, 400, 18),
    labelLarge = style(15, 700, 20),
    labelMedium = style(13, 600, 16, 0.01),
    labelSmall = style(11, 700, 14, 0.06),
)

// --- Couleurs -----------------------------------------------------------------------

object Brand {
    val Blue = Color(0xFF2563EB)
    val BlueDeep = Color(0xFF1E40AF)
    val Sky = Color(0xFF60A5FA)
    val Orange = Color(0xFFF59E0B)
    val OrangeDeep = Color(0xFFEA580C)
    val Green = Color(0xFF16A34A)
}

/** Couleurs propres à GrabDrop, en plus de celles de Material. */
@Immutable
data class GrabDropColors(
    val held: Color,
    val heldContainer: Color,
    val onHeldContainer: Color,
    val success: Color,
    val subtle: Color,
)

val LocalGrabDropColors = staticCompositionLocalOf {
    GrabDropColors(Brand.Orange, Color(0xFFFFF4E0), Color(0xFF7A3E00), Brand.Green, Color(0xFFEEF2FA))
}

private val LightColors = lightColorScheme(
    primary = Brand.Blue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDDE7FF),
    onPrimaryContainer = Color(0xFF0B2A6B),
    secondary = Brand.Orange,
    onSecondary = Color(0xFF3B1F00),
    background = Color(0xFFF5F7FB),
    onBackground = Color(0xFF0F172A),
    surface = Color(0xFFF5F7FB),
    onSurface = Color(0xFF0F172A),
    surfaceVariant = Color(0xFFE9EDF5),
    onSurfaceVariant = Color(0xFF586275),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color.White,
    surfaceContainer = Color.White,
    surfaceContainerHigh = Color(0xFFF0F3F9),
    surfaceContainerHighest = Color(0xFFE6EAF2),
    outline = Color(0xFFCBD2DE),
    outlineVariant = Color(0xFFE3E7EF),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF7FA6FF),
    onPrimary = Color(0xFF08204F),
    primaryContainer = Color(0xFF1C3A85),
    onPrimaryContainer = Color(0xFFDDE7FF),
    secondary = Color(0xFFFBBF24),
    onSecondary = Color(0xFF3B2600),
    background = Color(0xFF0A0F1C),
    onBackground = Color(0xFFE7EAF3),
    surface = Color(0xFF0A0F1C),
    onSurface = Color(0xFFE7EAF3),
    surfaceVariant = Color(0xFF1E2638),
    onSurfaceVariant = Color(0xFF9AA4B8),
    surfaceContainerLowest = Color(0xFF0D1322),
    surfaceContainerLow = Color(0xFF131A2B),
    surfaceContainer = Color(0xFF151D30),
    surfaceContainerHigh = Color(0xFF1B2438),
    surfaceContainerHighest = Color(0xFF222C42),
    outline = Color(0xFF34405A),
    outlineVariant = Color(0xFF263049),
)

private val LightExtra = GrabDropColors(
    held = Color(0xFFD97706), heldContainer = Color(0xFFFFF3DD), onHeldContainer = Color(0xFF6B3500),
    success = Brand.Green, subtle = Color(0xFFEEF2FA),
)
private val DarkExtra = GrabDropColors(
    held = Color(0xFFFBBF24), heldContainer = Color(0xFF2E2210), onHeldContainer = Color(0xFFFDE7B8),
    success = Color(0xFF4ADE80), subtle = Color(0xFF182036),
)

private val GrabDropShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

@Composable
fun GrabDropTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalGrabDropColors provides if (dark) DarkExtra else LightExtra) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = GrabDropTypography,
            shapes = GrabDropShapes,
            content = content,
        )
    }
}

/** Accès court : GrabDropTheme.colors.held, etc. */
object GrabDropTheme {
    val colors: GrabDropColors
        @Composable get() = LocalGrabDropColors.current
}
