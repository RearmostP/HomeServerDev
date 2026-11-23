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
import il.homegallery.api.GallerySessionStore
import il.homegallery.network.TailnetConnection
import java.io.ByteArrayInputStream
import java.util.concurrent.Executors
import org.json.JSONObject

class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var root: FrameLayout
    private lateinit var panel: LinearLayout
    private lateinit var message: TextView
    private lateinit var primary: Button
    private lateinit var report: Button
    private lateinit var reset: Button
    private lateinit var progress: ProgressBar
    private val tailnetOwner = Any()
    private var connection: TailnetConnection? = null
    private lateinit var sessionStore: GallerySessionStore
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
        if (TailnetRuntime.keepConnected(this)) startForegroundService(Intent(this, TailnetService::class.java))
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
        report = Button(this).apply {
            isAllCaps = false
            background = rounded(Color.rgb(53, 49, 58), Color.rgb(53, 49, 58), 32)
            setTextColor(TEXT)
            setText(R.string.send_report)
            visibility = View.GONE
        }
        panel.addView(report, row())
    }

    private fun row() = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) }

    private fun showState(text: Int, button: Int? = null, canReset: Boolean = false, reportDetail: Int? = null) {
        report.visibility = if (reportDetail == null) View.GONE else View.VISIBLE
        report.setOnClickListener(if (reportDetail == null) null else View.OnClickListener { shareFailure(reportDetail) })
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

    private fun shareFailure(detail: Int) {
        val time = java.time.Instant.now().toString()
        val text = getString(R.string.report_message, getString(detail), time)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
        for (app in listOf("com.whatsapp", "com.whatsapp.w4b")) {
            try {
                startActivity(intent.setPackage(app))
                return
            } catch (_: android.content.ActivityNotFoundException) {
                // Try the other WhatsApp edition.
            }
        }
        android.widget.Toast.makeText(this, R.string.no_whatsapp, android.widget.Toast.LENGTH_SHORT).show()
    }

    private fun probeFailure(error: Throwable?): Int {
        val description = error?.message.orEmpty()
        return when {
            description.contains("not yet valid", ignoreCase = true) ||
                description.contains("has expired", ignoreCase = true) -> R.string.report_certificate_time
            description.contains("tls:", ignoreCase = true) ||
                description.contains("x509:", ignoreCase = true) -> R.string.report_tls
            description.contains("timeout", ignoreCase = true) ||
                description.contains("deadline exceeded", ignoreCase = true) -> R.string.report_timeout
            else -> R.string.report_server
        }
    }

    private fun startConnection(replaceState: Boolean = false) {
        val generation = ++cycle
        main.removeCallbacks(poll)
        authUrl = null
        showState(R.string.connecting)
        val host = assets.open("server-host.txt").bufferedReader().use { it.readText().trim() }
        sessionStore = GallerySessionStore(applicationContext, host)
        if (replaceState) sessionStore.clear()
        worker.execute {
            val result = runCatching {
                TailnetRuntime.acquire(applicationContext, tailnetOwner, replaceState).also { connection = it }
            }
            main.post {
                if (closed || generation != cycle) return@post
                if (result.isSuccess) checkConnection(generation)
                else {
                    android.util.Log.w("HomeGallery", "Tailscale startup failed", result.exceptionOrNull())
                    showState(R.string.startup_error, R.string.retry, reportDetail = R.string.startup_error)
                }
            }
        }
    }

    private fun checkConnection(generation: Int) {
        worker.execute {
            val current = connection
            val status = runCatching { current?.status() }.getOrNull()
            val probe = if (status?.state == "Running") runCatching { current?.probe() } else null
            main.post {
                if (closed || generation != cycle) return@post
                authUrl = status?.authUrl?.takeIf(String::isNotBlank)?.let(Uri::parse)
                    ?.takeIf { it.scheme == "https" && it.host == "login.tailscale.com" && it.userInfo == null }
                when {
                    probe?.isSuccess == true && current != null -> {
                        openGallery(current)
                        return@post
                    }
                    status?.state == "WrongTailnet" -> showState(R.string.wrong_tailnet, canReset = true, reportDetail = R.string.wrong_tailnet)
                    status?.state == "NeedsMachineAuth" -> showState(R.string.approval, canReset = true)
                    status?.state == "Running" -> showState(R.string.server_wait, reportDetail = probeFailure(probe?.exceptionOrNull()))
                    authUrl != null -> showState(R.string.login_ready, R.string.tailscale_login)
                    status == null -> showState(R.string.startup_error, R.string.retry, reportDetail = R.string.startup_error)
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
        val transport = GalleryApi(current, sessionStore, { main.post {
            if (!closed) startActivity(Intent(this, SettingsActivity::class.java))
        } }) { id, status, length ->
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
            val callback = picker
            picker = null
            val selected = if (resultCode == RESULT_OK && data != null) {
                buildList {
                    data.clipData?.let { clip ->
                        for (index in 0 until clip.itemCount) clip.getItemAt(index).uri?.let(::add)
                    }
                    data.data?.let(::add)
                }.distinct().filter { uri ->
                    uri.scheme == "content" && checkUriPermission(
                        uri, android.os.Process.myPid(), android.os.Process.myUid(),
                        Intent.FLAG_GRANT_READ_URI_PERMISSION,
                    ) == android.content.pm.PackageManager.PERMISSION_GRANTED
                }
            } else emptyList()
            callback?.onReceiveValue(selected.takeIf { it.isNotEmpty() }?.toTypedArray())
            if (resultCode == RESULT_OK && selected.isEmpty()) {
                android.widget.Toast.makeText(this, R.string.photo_selection_unavailable,
                    android.widget.Toast.LENGTH_LONG).show()
            }
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
        worker.execute { runCatching { TailnetRuntime.release(tailnetOwner) } }
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
