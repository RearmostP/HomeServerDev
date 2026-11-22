package il.homegallery.network

import il.homegallery.nativebridge.tailbridge.Client
import il.homegallery.nativebridge.tailbridge.Tailbridge
import java.io.Closeable
import java.io.File
import org.json.JSONObject

data class TailnetStatus(val state: String, val authUrl: String)

class TailnetConnection(state: File, name: String, host: String) : Closeable {
    private val client: Client = Tailbridge.start(state.absolutePath, name, host)

    fun status(): TailnetStatus {
        val result = JSONObject(client.status())
        return TailnetStatus(result.getString("state"), result.optString("authUrl"))
    }

    fun probe() = client.probe()

    fun request(method: String, path: String, contentType: String, body: String): JSONObject =
        JSONObject(client.request(method, path, contentType, body))

    override fun close() = client.close()
}
