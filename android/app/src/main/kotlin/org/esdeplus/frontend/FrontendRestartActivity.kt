// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using Android SDK process and activity APIs.
package org.esdeplus.frontend

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import android.util.Log
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

// A Java-only foreground owner for Android's non-finishing recreation. The
// manifest places it in a separate private process: native globals are never
// restarted in their old VM, and no alarm/background-launch permission is used.
class FrontendRestartActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private var parentPid = 0
    private lateinit var entry: Intent
    private var deadline = 0L
    private var focused = false
    private var resumed = false
    private var started = false
    private var waiting = true
    private val awaitRetirement = object : Runnable {
        override fun run() {
            if (isFinishing || isDestroyed || started || !resumed || !waiting) return
            val alive = try { Os.kill(parentPid, 0); true }
                catch (error: ErrnoException) { error.errno != OsConstants.ESRCH }
            if (!alive && focused) {
                started = true
                Log.i("ES-DE-Plus", "SDL process $parentPid retired; restarting entry ${entry.component}")
                try {
                    // Android assigns the real HOME type to an implicit HOME
                    // intent. Explicit app-originated launches are standard
                    // activities on newer Android; restrict resolution to our
                    // own package so no other launcher or chooser can open.
                    val restart = if (entry.hasCategory(Intent.CATEGORY_HOME) &&
                        entry.component?.className?.endsWith(".HomeEntry") == true)
                        Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).setPackage(packageName)
                    else Intent(entry)
                    startActivity(restart.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                    finish()
                } catch (error: RuntimeException) {
                    started = false
                    Log.e("ES-DE-Plus", "Cannot open frontend entry", error)
                    showRecovery()
                }
            } else if (SystemClock.elapsedRealtime() >= deadline) {
                // Never kill the parent or replay destruction. A stalled
                // native thread remains a real, gating failure.
                Log.e("ES-DE-Plus", "Cannot restart frontend: old SDL process still alive or restart window unfocused")
                showRecovery()
            } else handler.postDelayed(this, 100)
        }
    }

    @Suppress("DEPRECATION")
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        parentPid = intent.getIntExtra("parentPid", 0)
        val requested = intent.getParcelableExtra<Intent>("entry")
        val component = requested?.component
        val frontend = MainActivity::class.java.name
        val namespace = frontend.substringBeforeLast('.')
        if (parentPid <= 0 || parentPid == Process.myPid() || requested == null || component == null ||
            component.packageName != packageName ||
            component.className !in listOf(frontend, "$namespace.HomeEntry", "$namespace.LeanbackEntry")) {
            Log.e("ES-DE-Plus", "Invalid private frontend restart request")
            finish()
            return
        }
        entry = Intent(requested).replaceExtras(null as Bundle?)
        // Large libraries can take much longer than the CI fixture to load
        // or free on slow storage. Allow two minutes before offering recovery;
        // expiry leaves a retry screen, never kills or overlaps the parent.
        deadline = SystemClock.elapsedRealtime() + 120_000
        showWaiting()
    }

    private fun showWaiting() {
        waiting = true
        setContentView(TextView(this).apply {
            setText(R.string.frontend_restart_waiting)
            setPadding(32, 32, 32, 32)
        })
    }

    private fun showRecovery() {
        waiting = false
        Log.i("ES-DE-Plus", "Frontend restart recovery shown; entry remains available")
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            addView(TextView(this@FrontendRestartActivity).apply { setText(R.string.frontend_restart_recovery) })
            addView(Button(this@FrontendRestartActivity).apply {
                setText(R.string.retry)
                setOnClickListener {
                    deadline = SystemClock.elapsedRealtime() + 120_000
                    showWaiting()
                    this@FrontendRestartActivity.handler.post(awaitRetirement)
                }
                requestFocus()
            })
        })
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        if (::entry.isInitialized) {
            handler.post(awaitRetirement)
        }
    }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        focused = hasFocus
    }
    override fun onPause() {
        resumed = false
        handler.removeCallbacks(awaitRetirement)
        super.onPause()
    }
    override fun onDestroy() {
        handler.removeCallbacks(awaitRetirement)
        super.onDestroy()
    }

    companion object {
        internal fun prepare(context: Context, entry: Intent) {
            context.startActivity(Intent(context, FrontendRestartActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra("parentPid", Process.myPid()).putExtra("entry", entry))
        }
    }
}
