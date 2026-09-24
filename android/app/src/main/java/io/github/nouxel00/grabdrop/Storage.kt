package io.github.nouxel00.grabdrop

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import io.github.nouxel00.grabdrop.core.ReceiveSink
import io.github.nouxel00.grabdrop.core.safeName
import java.io.File
import java.io.IOException
import java.io.OutputStream

/** Écrit les fichiers reçus dans Téléchargements/GrabDrop (MediaStore, sans permission de stockage). */
class MediaStoreSink(private val context: Context) : ReceiveSink {
    private val base = "${Environment.DIRECTORY_DOWNLOADS}/GrabDrop"
    val created = mutableListOf<Pair<Uri, String>>()  // (uri, type MIME)

    override fun openFile(relativePath: String, size: Long): OutputStream {
        val parts = relativePath.split("/")
        val dirs = parts.dropLast(1).joinToString("/")
        val name = parts.last()
        val mime = mimeFor(name)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, if (dirs.isEmpty()) "$base/" else "$base/$dirs/")
            put(MediaStore.MediaColumns.IS_PENDING, 1)  // invisible tant que le transfert n'est pas terminé
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("impossible d'écrire dans Téléchargements")
        created += uri to mime
        return resolver.openOutputStream(uri) ?: throw IOException("impossible d'écrire $name")
    }

    override fun commit() {
        val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
        created.forEach { (uri, _) -> context.contentResolver.update(uri, done, null, null) }
    }

    override fun abort() {
        created.forEach { (uri, _) -> runCatching { context.contentResolver.delete(uri, null, null) } }
        created.clear()
    }
}

/** Enregistre une image (capture d'écran, image copiée) dans Images/GrabDrop. */
fun saveImage(context: Context, png: ByteArray, name: String): Uri {
    val values = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, safeName(name.substringAfterLast('/')).let { if (it.endsWith(".png")) it else "$it.png" })
        put(MediaStore.MediaColumns.MIME_TYPE, "image/png")
        put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/GrabDrop/")
        put(MediaStore.MediaColumns.IS_PENDING, 1)
    }
    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
        ?: throw IOException("impossible d'enregistrer l'image")
    resolver.openOutputStream(uri)!!.use { it.write(png) }
    resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
    return uri
}

fun mimeFor(name: String): String =
    MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substringAfterLast('.', "").lowercase())
        ?: "application/octet-stream"

fun copyTextToClipboard(context: Context, text: String) {
    context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("GrabDrop", text))
}

fun copyImageToClipboard(context: Context, uri: Uri) {
    context.getSystemService(ClipboardManager::class.java)
        .setPrimaryClip(ClipData.newUri(context.contentResolver, "GrabDrop", uri))
}

fun openUri(context: Context, uri: Uri, mime: String) {
    val intent = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}

fun openUrl(context: Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

fun isSingleUrl(text: String): Boolean {
    val t = text.trim()
    return (t.startsWith("http://") || t.startsWith("https://")) && t.none { it.isWhitespace() }
}

/**
 * Copie des contenus partagés vers le cache de l'app : la permission de lecture
 * accordée par l'app d'origine peut expirer avant qu'un PC ne vienne les chercher.
 */
fun copySharedToCache(context: Context, uris: List<Uri>, dir: File): List<File> {
    dir.mkdirs()
    return uris.mapNotNull { uri ->
        val name = safeName(displayName(context, uri) ?: uri.lastPathSegment ?: "fichier")
        var target = File(dir, name)
        var n = 1
        while (target.exists()) target = File(dir, "${name.substringBeforeLast('.')} ($n)" +
            (name.substringAfterLast('.', "").let { if (it.isEmpty()) "" else ".$it" })).also { n++ }
        context.contentResolver.openInputStream(uri)?.use { input -> target.outputStream().use { input.copyTo(it) } }
            ?: return@mapNotNull null
        target
    }
}

private fun displayName(context: Context, uri: Uri): String? =
    runCatching {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }
    }.getOrNull()
