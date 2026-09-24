package io.github.nouxel00.grabdrop

import android.content.Context
import android.os.Build
import android.provider.Settings
import java.util.UUID

/** Identité du téléphone et clé du groupe (équivalent de config.json sur PC). */
class DeviceConfig(private val context: Context) {
    private val prefs = context.getSharedPreferences("grabdrop", Context.MODE_PRIVATE)

    val deviceId: String = prefs.getString("device_id", null)
        ?: UUID.randomUUID().toString().replace("-", "").also { prefs.edit().putString("device_id", it).apply() }

    val deviceName: String
        get() = Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME)
            ?.takeIf { it.isNotBlank() } ?: Build.MODEL

    var groupCode: String?
        get() = prefs.getString("group_code", null)
        set(value) = prefs.edit().putString("group_code", value).apply()

    /** Adresses « hôte:port » des PC appairés, utilisées si la découverte automatique ne les trouve pas. */
    var knownPcs: Set<String>
        get() = prefs.getStringSet("known_pcs", emptySet()) ?: emptySet()
        set(value) = prefs.edit().putStringSet("known_pcs", value).apply()

    var gesturesEnabled: Boolean
        get() = prefs.getBoolean("gestures", true)
        set(value) = prefs.edit().putBoolean("gestures", value).apply()
}
