package il.homegallery

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

class SettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val foreground = Color.rgb(246, 241, 235)
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            setBackgroundColor(Color.rgb(23, 22, 25))
            setPadding(dp(22), dp(18), dp(22), dp(18))
        }
        panel.setOnApplyWindowInsetsListener { view, insets ->
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() or
                    android.view.WindowInsets.Type.displayCutout())
                view.setPadding(dp(22) + bars.left, dp(18) + bars.top, dp(22) + bars.right, dp(18) + bars.bottom)
            }
            insets
        }
        panel.addView(Button(this).apply {
            text = getString(R.string.settings_back)
            setOnClickListener { finish() }
        }, LinearLayout.LayoutParams(-2, -2))
        panel.addView(TextView(this).apply {
            setText(R.string.gallery_settings)
            textSize = 31f
            setTextColor(foreground)
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(16), 0, dp(20))
        })
        val option = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(10), dp(16), dp(16))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(Color.rgb(36, 34, 40))
                cornerRadius = dp(18).toFloat()
            }
        }
        val toggle = Switch(this).apply {
            setText(R.string.keep_tailnet_connected)
            setTextColor(foreground)
            textSize = 17f
            minHeight = dp(48)
            gravity = Gravity.CENTER_VERTICAL
            isChecked = TailnetRuntime.keepConnected(this@SettingsActivity)
        }
        option.addView(toggle, LinearLayout.LayoutParams(-1, -2))
        option.addView(TextView(this).apply {
            setText(R.string.keep_tailnet_description)
            setTextColor(Color.rgb(183, 174, 185))
            textSize = 14f
        })
        panel.addView(option, LinearLayout.LayoutParams(-1, -2))
        setContentView(panel)
        toggle.setOnCheckedChangeListener { _, enabled ->
            TailnetRuntime.setKeepConnected(this, enabled)
            val service = Intent(this, TailnetService::class.java)
            if (enabled) {
                try {
                    startForegroundService(service)
                    if (android.os.Build.VERSION.SDK_INT >= 33 &&
                        checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) !=
                        android.content.pm.PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
                    }
                } catch (_: IllegalStateException) {
                    TailnetRuntime.setKeepConnected(this, false)
                    toggle.isChecked = false
                    Toast.makeText(this, R.string.keep_tailnet_error, Toast.LENGTH_SHORT).show()
                }
            } else {
                stopService(service)
            }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
