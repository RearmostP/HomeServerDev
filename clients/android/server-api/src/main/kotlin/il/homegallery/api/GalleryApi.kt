package il.homegallery.api

import android.webkit.JavascriptInterface
import il.homegallery.network.TailnetConnection
import java.io.Closeable
import java.util.concurrent.Executors
import org.json.JSONObject

class GalleryApi(
    private val connection: TailnetConnection,
    private val completed: (String, Int, Int) -> Unit,
) : Closeable {
    private val executor = Executors.newFixedThreadPool(4)
    private val uploads = mutableMapOf<String, StringBuilder>()
    private val responses = mutableMapOf<String, String>()
    private val active = mutableSetOf<String>()
    private var closed = false

    @JavascriptInterface
    @Synchronized
    fun append(id: String, chunk: String): Boolean {
        if (closed || !validId(id) || chunk.length > CHUNK || id in active) return false
        if (uploads.size >= MAX_ACTIVE && id !in uploads) return false
        val buffer = uploads.getOrPut(id) { StringBuilder() }
        if (buffer.length + chunk.length > MAX_ENCODED) {
            uploads.remove(id)
            return false
        }
        buffer.append(chunk)
        return true
    }

    @JavascriptInterface
    @Synchronized
    fun send(id: String, method: String, path: String, contentType: String): Boolean {
        if (closed || !validId(id) || active.size >= MAX_ACTIVE || id in active) return false
        val body = uploads.remove(id)?.toString().orEmpty()
        active.add(id)
        executor.execute {
            val reply = runCatching { connection.request(method, path, contentType, body) }.getOrNull()
            val encoded = reply?.optString("body").orEmpty()
            synchronized(this) {
                if (closed || id !in active) return@execute
                responses[id] = encoded
            }
            completed(id, reply?.optInt("status") ?: 0, encoded.length)
        }
        return true
    }

    @JavascriptInterface
    @Synchronized
    fun read(id: String, start: Int): String {
        val response = responses[id] ?: return ""
        if (start !in response.indices) return ""
        return response.substring(start, minOf(start + CHUNK, response.length))
    }

    @JavascriptInterface
    @Synchronized
    fun release(id: String) {
        uploads.remove(id)
        responses.remove(id)
        active.remove(id)
    }

    @Synchronized
    override fun close() {
        closed = true
        uploads.clear()
        responses.clear()
        active.clear()
        executor.shutdownNow()
    }

    private fun validId(id: String) = id.length == 36 && UUID.matches(id)

    companion object {
        private const val CHUNK = 65_536
        private const val MAX_ENCODED = ((26 * 1024 * 1024 + 2) / 3) * 4
        private const val MAX_ACTIVE = 12
        private val UUID = Regex("[0-9a-f-]{36}")
    }
}
