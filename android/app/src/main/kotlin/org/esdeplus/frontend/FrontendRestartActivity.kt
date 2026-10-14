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
import android.view.View

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
    private val awaitRetirement = object : Runnable {
        override fun run() {
            if (isFinishing || isDestroyed || started || !resumed) return
            val alive = try { Os.kill(parentPid, 0); true }
                catch (error: ErrnoException) { error.errno != OsConstants.ESRCH }
            if (!alive && focused) {
                started = true
                Log.i("ES-DE-Plus", "SDL process $parentPid retired; restarting entry ${entry.component}")
                startActivity(Intent(entry).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                finish()
            } else if (SystemClock.elapsedRealtime() >= deadline) {
                // Never kill the parent or replay destruction. A stalled
                // native thread remains a real, gating failure.
                Log.e("ES-DE-Plus", "Cannot restart frontend: old SDL process still alive or restart window unfocused")
                finish()
            } else handler.postDelayed(this, 20)
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
        setContentView(View(this))
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        if (::entry.isInitialized) {
            deadline = SystemClock.elapsedRealtime() + 5_000
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
