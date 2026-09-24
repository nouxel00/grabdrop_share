package io.github.nouxel00.grabdrop.core

import java.io.InputStream
import java.util.Locale
import java.util.UUID

/** Types d'objets, identiques à grabdrop/items.py. */
object Kind {
    const val SCREENSHOT = "screenshot"
    const val IMAGE = "image"
    const val TEXT = "text"
    const val FILES = "files"
}

/**
 * Fichier d'un objet. [path] est relatif, séparateur « / ».
 * Côté expéditeur, [open] fournit le contenu (fichier, Uri Android...).
 */
class FileEntry(val path: String, val size: Long, val open: (() -> InputStream)? = null)

class Item(
    val kind: String,
    val name: String,
    val mime: String = "",
    val data: ByteArray = ByteArray(0),
    val files: List<FileEntry> = emptyList(),
    val id: String = UUID.randomUUID().toString().replace("-", ""),
) {
    val size: Long get() = data.size + files.sumOf { it.size }

    fun describe(): String = describe(kind, name, size, files.size)
}

fun describe(kind: String, name: String, size: Long, count: Int): String = when {
    kind == Kind.SCREENSHOT -> "capture d'écran (${humanSize(size)})"
    kind == Kind.IMAGE -> "image copiée (${humanSize(size)})"
    kind == Kind.TEXT -> "texte copié"
    count == 1 -> "« $name » (${humanSize(size)})"
    else -> "$count fichiers (${humanSize(size)})"
}

fun humanSize(bytes: Long): String {
    var n = bytes.toDouble()
    for (unit in listOf("octets", "Ko", "Mo", "Go")) {
        if (n < 1024 || unit == "Go") {
            return if (unit == "octets") "${n.toLong()} octets"
            else String.format(Locale.FRANCE, "%.1f %s", n, unit)
        }
        n /= 1024
    }
    error("inatteignable")
}

/** L'objet « en main » : expire après [ttlMs] et ne peut être pris qu'une fois. */
class HeldItem(val ttlMs: Long = 60_000, private val clock: () -> Long = System::currentTimeMillis) {
    private var item: Item? = null
    private var since = 0L

    @Synchronized
    fun hold(newItem: Item) {
        item = newItem
        since = clock()
    }

    /** (objet, âge en ms), ou null. */
    @Synchronized
    fun peek(): Pair<Item, Long>? {
        expire()
        return item?.let { it to (clock() - since) }
    }

    @Synchronized
    fun take(itemId: String): Item? {
        expire()
        val current = item ?: return null
        if (current.id != itemId) return null
        item = null
        return current
    }

    @Synchronized
    fun clear() {
        item = null
    }

    private fun expire() {
        if (item != null && clock() - since > ttlMs) item = null
    }
}

private val forbiddenChars = Regex("[<>:\"/\\\\|?*\\x00-\\x1f]")
private val reservedNames = setOf("CON", "PRN", "AUX", "NUL") + (1..9).flatMap { listOf("COM$it", "LPT$it") }

/** Nom de fichier sûr (mêmes règles que items.safe_name). */
fun safeName(name: String, default: String = "grabdrop"): String {
    val cleaned = name.replace(forbiddenChars, "_").trim(' ', '.')
    if (cleaned.isEmpty()) return default
    return if (cleaned.substringBefore('.').uppercase() in reservedNames) "_$cleaned" else cleaned
}

/** Chemin relatif venant d'un autre appareil, rendu inoffensif (pas de « .. », ni de chemin absolu). */
fun safeRelativePath(path: String): String {
    val parts = path.split('/', '\\').filter { it.isNotEmpty() && it != "." && it != ".." }
    return if (parts.isEmpty()) "grabdrop" else parts.joinToString("/") { safeName(it, "_") }
}
