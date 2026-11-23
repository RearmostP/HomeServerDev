package il.homegallery

import android.content.Context
import il.homegallery.network.TailnetConnection
import java.io.File
import java.util.UUID

internal object TailnetRuntime {
    private val owners = mutableSetOf<Any>()
    private var connection: TailnetConnection? = null

    fun keepConnected(context: Context): Boolean =
        context.getSharedPreferences("tailnet", Context.MODE_PRIVATE).getBoolean("keepConnected", false)

    fun setKeepConnected(context: Context, enabled: Boolean) {
        context.getSharedPreferences("tailnet", Context.MODE_PRIVATE)
            .edit().putBoolean("keepConnected", enabled).apply()
    }

    @Synchronized
    fun acquire(context: Context, owner: Any, replaceState: Boolean = false): TailnetConnection {
        if (!replaceState) connection?.let {
            owners.add(owner)
            return it
        }
        connection?.close()
        connection = null
        val prefs = context.getSharedPreferences("tailnet", Context.MODE_PRIVATE)
        val oldToken = prefs.getString("node", null)
        val token = if (oldToken == null || replaceState) {
            UUID.randomUUID().toString().also { check(prefs.edit().putString("node", it).commit()) }
        } else oldToken
        if (replaceState && oldToken != null) {
            File(context.noBackupFilesDir, "tailscale-" + oldToken).deleteRecursively()
        }
        val directory = File(context.noBackupFilesDir, "tailscale-" + token)
        val host = context.assets.open("server-host.txt").bufferedReader().use { it.readText().trim() }
        return TailnetConnection(context.applicationContext, directory, "home-gallery-" + token.take(8), host).also {
            connection = it
            owners.add(owner)
        }
    }

    @Synchronized
    fun release(owner: Any) {
        if (!owners.remove(owner) || owners.isNotEmpty()) return
        val current = connection
        connection = null
        current?.close()
    }
}
