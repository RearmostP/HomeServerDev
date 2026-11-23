package il.homegallery.network

import il.homegallery.nativebridge.tailbridge.Client
import il.homegallery.nativebridge.tailbridge.Tailbridge
import android.content.Context
import java.io.Closeable
import java.io.File
import org.json.JSONObject

data class TailnetStatus(val state: String, val authUrl: String)

class TailnetConnection(context: Context, state: File, name: String, host: String) : Closeable {
    private val client: Client

    init {
        Tailbridge.configureAndroidNetwork(AndroidNetwork(context), File(context.cacheDir, "tailscale").absolutePath)
        client = Tailbridge.start(state.absolutePath, name, host)
    }

    fun status(): TailnetStatus {
        val result = JSONObject(client.status())
        return TailnetStatus(result.getString("state"), result.optString("authUrl"))
    }

    fun probe() = client.probe()

    fun request(method: String, path: String, contentType: String, body: String): JSONObject =
        JSONObject(client.request(method, path, contentType, body))

    fun sessionToken(): String = client.sessionToken()

    fun restoreSession(token: String): Boolean = client.restoreSession(token)

    override fun close() = client.close()
}
