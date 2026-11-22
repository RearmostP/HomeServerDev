package il.homegallery

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import il.homegallery.api.GalleryApi
import il.homegallery.network.TailnetConnection
import java.io.ByteArrayInputStream
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors
import org.json.JSONObject

class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var root: FrameLayout
    private lateinit var panel: LinearLayout
    private lateinit var message: TextView
    private lateinit var primary: Button
    private lateinit var reset: Button
    private lateinit var progress: ProgressBar
    private var connection: TailnetConnection? = null
    private var api: GalleryApi? = null
    private var web: WebView? = null
    private var picker: ValueCallback<Array<Uri>>? = null
    private var authUrl: Uri? = null
    private var closed = false
    private var cycle = 0
    private val poll = Runnable { checkConnection(cycle) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL
        root = FrameLayout(this).apply { setBackgroundColor(BACKGROUND) }
        root.setOnApplyWindowInsetsListener { view, insets ->
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() or
                    android.view.WindowInsets.Type.displayCutout() or android.view.WindowInsets.Type.ime())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            }
            insets
        }
        setContentView(root)
        buildPanel()
        startConnection()
    }

    private fun rounded(start: Int, end: Int, radius: Int) = GradientDrawable(
        GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(start, end),
    ).apply { cornerRadius = dp(radius).toFloat() }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun buildPanel() {
        val backdrop = FrameLayout(this).apply {
            background = rounded(Color.rgb(58, 46, 59), BACKGROUND, 0)
        }
        root.addView(backdrop, FrameLayout.LayoutParams(-1, -1))
        panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            background = rounded(SURFACE, SURFACE, 24)
            setPadding(dp(24), dp(24), dp(24), dp(24))
        }
        val width = minOf(resources.displayMetrics.widthPixels - dp(32), dp(420))
        backdrop.addView(panel, FrameLayout.LayoutParams(width, -2, Gravity.CENTER))
        val title = TextView(this).apply {
            text = getString(R.string.app_name)
            textSize = 30f
            setTextColor(TEXT)
            setTypeface(typeface, Typeface.BOLD)
            gravity = Gravity.CENTER
        }
        panel.addView(title, row())
        progress = ProgressBar(this).apply { indeterminateTintList = ColorStateList.valueOf(ACCENT) }
        panel.addView(progress, LinearLayout.LayoutParams(dp(32), dp(32)).apply { topMargin = dp(20) })
        message = TextView(this).apply {
            textSize = 16f
            gravity = Gravity.CENTER
            setTextColor(TEXT)
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        panel.addView(message, row())
        primary = Button(this).apply {
            isAllCaps = false
            background = rounded(ACCENT, ACCENT, 32)
            setTextColor(Color.rgb(44, 27, 19))
            setOnClickListener {
                val link = authUrl
                if (link == null) startConnection()
                else try {
                    startActivity(Intent(Intent.ACTION_VIEW, link).addCategory(Intent.CATEGORY_BROWSABLE))
                } catch (_: android.content.ActivityNotFoundException) {
                    message.setText(R.string.no_browser)
                }
            }
        }
        panel.addView(primary, row())
        reset = Button(this).apply {
            isAllCaps = false
            background = rounded(Color.rgb(53, 49, 58), Color.rgb(53, 49, 58), 32)
            setTextColor(TEXT)
            setText(R.string.reset_connection)
            setOnClickListener {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(R.string.reset_prompt)
                    .setNegativeButton(android.R.string.cancel, null)
                    .setPositiveButton(R.string.reset_connection) { _, _ -> startConnection(replaceState = true) }
                    .show()
            }
        }
        panel.addView(reset, row())
    }

    private fun row() = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) }

    private fun showState(text: Int, button: Int? = null, canReset: Boolean = false) {
        if (message.text != getText(text)) {
            message.setText(text)
            message.alpha = .55f
            message.animate().alpha(1f).setDuration(180).start()
        }
        primary.visibility = if (button == null) View.GONE else View.VISIBLE
        if (button != null) primary.setText(button)
        reset.visibility = if (canReset) View.VISIBLE else View.GONE
        progress.visibility = if (button == null && !canReset) View.VISIBLE else View.GONE
    }

    private fun startConnection(replaceState: Boolean = false) {
        val generation = ++cycle
        main.removeCallbacks(poll)
        authUrl = null
        showState(R.string.connecting)
        val host = assets.open("server-host.txt").bufferedReader().use { it.readText().trim() }
        worker.execute {
            val result = runCatching {
                connection?.close()
                connection = null
                val preferences = getSharedPreferences("tailnet", MODE_PRIVATE)
                val existing = preferences.getString("node", null)
                val token = if (existing == null || replaceState) {
                    UUID.randomUUID().toString().also {
                        check(preferences.edit().putString("node", it).commit())
                    }
                } else existing
                val nodeDir = File(noBackupFilesDir, "tailscale-" + token)
                if (replaceState && existing != null) File(noBackupFilesDir, "tailscale-" + existing).deleteRecursively()
                TailnetConnection(nodeDir, "home-gallery-" + token.take(8), host).also { connection = it }
            }
            main.post {
                if (closed || generation != cycle) return@post
                if (result.isSuccess) checkConnection(generation)
                else showState(R.string.startup_error, R.string.retry)
            }
        }
    }

    private fun checkConnection(generation: Int) {
        worker.execute {
            val current = connection
            val status = runCatching { current?.status() }.getOrNull()
            val galleryReady = status?.state == "Running" && runCatching { current?.probe() }.isSuccess
            main.post {
                if (closed || generation != cycle) return@post
                authUrl = status?.authUrl?.takeIf(String::isNotBlank)?.let(Uri::parse)
                    ?.takeIf { it.scheme == "https" && it.host == "login.tailscale.com" && it.userInfo == null }
                when {
                    galleryReady && current != null -> {
                        openGallery(current)
                        return@post
                    }
                    status?.state == "WrongTailnet" -> showState(R.string.wrong_tailnet, canReset = true)
                    status?.state == "NeedsMachineAuth" -> showState(R.string.approval, canReset = true)
                    status?.state == "Running" -> showState(R.string.server_wait, canReset = true)
                    authUrl != null -> showState(R.string.login_ready, R.string.tailscale_login)
                    status == null -> showState(R.string.startup_error, R.string.retry)
                    else -> showState(R.string.connecting)
                }
                main.postDelayed(poll, 2500)
            }
        }
    }

    private fun openGallery(current: TailnetConnection) {
        val view = WebView(this).apply {
            setBackgroundColor(BACKGROUND)
            settings.javaScriptEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = true
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            webViewClient = GalleryAssets()
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    webView: WebView,
                    filePathCallback: ValueCallback<Array<Uri>>,
                    fileChooserParams: FileChooserParams,
                ): Boolean {
                    picker?.onReceiveValue(null)
                    picker = filePathCallback
                    return try {
                        startActivityForResult(fileChooserParams.createIntent(), PICK_PHOTOS)
                        true
                    } catch (_: android.content.ActivityNotFoundException) {
                        picker = null
                        false
                    }
                }
            }
        }
        val transport = GalleryApi(current) { id, status, length ->
            main.post {
                if (!closed && web === view) {
                    view.evaluateJavascript(
                        "window.galleryNativeComplete(" + JSONObject.quote(id) + "," + status + "," + length + ")",
                        null,
                    )
                }
            }
        }
        api = transport
        web = view
        view.addJavascriptInterface(transport, "GalleryNative")
        root.removeAllViews()
        root.addView(view, FrameLayout.LayoutParams(-1, -1))
        view.alpha = 0f
        view.loadUrl("$ORIGIN/index.html")
        view.animate().alpha(1f).setDuration(250).start()
    }

    private inner class GalleryAssets : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
            request.url.toString() != "$ORIGIN/index.html"

        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
            val name = request.url.path
            val mime = FILES[name]
            if (request.url.scheme != "https" || request.url.host != HOST ||
                request.url.port != -1 || mime == null || request.method != "GET") {
                return WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                    emptyMap(), ByteArrayInputStream(ByteArray(0)))
            }
            return WebResourceResponse(
                mime, "UTF-8", 200, "OK",
                mapOf(
                    "Content-Security-Policy" to
                        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-src 'none'; form-action 'none'",
                    "X-Content-Type-Options" to "nosniff",
                ),
                assets.open(requireNotNull(name).removePrefix("/")),
            )
        }
    }

    @Deprecated("Uses the native file chooser result API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PICK_PHOTOS) {
            picker?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            picker = null
        }
    }

    override fun onDestroy() {
        closed = true
        main.removeCallbacksAndMessages(null)
        picker?.onReceiveValue(null)
        picker = null
        api?.close()
        web?.let {
            it.removeJavascriptInterface("GalleryNative")
            root.removeView(it)
            it.destroy()
        }
        worker.execute { runCatching { connection?.close() } }
        worker.shutdown()
        super.onDestroy()
    }

    companion object {
        private const val HOST = "appassets.androidplatform.net"
        private const val ORIGIN = "https://$HOST"
        private const val PICK_PHOTOS = 101
        private val BACKGROUND = Color.rgb(23, 22, 25)
        private val SURFACE = Color.rgb(36, 34, 40)
        private val ACCENT = Color.rgb(246, 201, 164)
        private val TEXT = Color.rgb(246, 241, 235)
        private val FILES = mapOf(
            "/index.html" to "text/html",
            "/app.css" to "text/css",
            "/app.js" to "text/javascript",
            "/android-transport.js" to "text/javascript",
        )
    }
}
