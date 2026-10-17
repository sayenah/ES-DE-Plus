// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Scheduling probe; no injected lifecycle or native events.
package org.esdeplus.stub

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log

class ClearTaskProbe : Instrumentation() {
    private var entry = "MainActivity"
    private var armed = false

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        entry = arguments?.getString("entry") ?: entry
        start()
    }

    override fun callActivityOnResume(activity: Activity) {
        super.callActivityOnResume(activity)
        if (armed || activity.javaClass.name != "org.esdeplus.frontend.FrontendRedirectActivity") return
        armed = true
        // Widen the interval between replacement resume/focus and the main
        // queue becoming idle. All framework messages still run, including
        // focus, stop and destroy. The helper's separate VM is unaffected.
        // No finish/recreate/quit, task operation, or result is substituted.
        val handler = Handler(Looper.getMainLooper())
        val deadline = SystemClock.uptimeMillis() + 15_000
        Log.i("ES-DE-Plus-Probe", "Clear-task replacement idle barrier armed pid=${android.os.Process.myPid()}")
        handler.post(object : Runnable {
            override fun run() {
                if (SystemClock.uptimeMillis() < deadline) handler.post(this)
                else Log.i("ES-DE-Plus-Probe", "Clear-task replacement idle barrier released")
            }
        })
    }

    override fun onStart() {
        try {
            check(entry in listOf("MainActivity", "HomeEntry", "LeanbackEntry"))
            val category = when (entry) {
                "HomeEntry" -> Intent.CATEGORY_HOME
                "LeanbackEntry" -> Intent.CATEGORY_LEANBACK_LAUNCHER
                else -> Intent.CATEGORY_LAUNCHER
            }
            startActivitySync(Intent(Intent.ACTION_MAIN).setClassName(targetContext.packageName,
                "org.esdeplus.frontend.$entry").addCategory(category).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            // The shell issues the single clear-task launch after observing
            // real native readiness. Instrumentation never ends the session.
            Thread.sleep(180_000)
            error("Clear-task host did not retire")
        } catch (error: Throwable) {
            Log.e("ES-DE-Plus-Probe", "Clear-task probe failed", error)
            finish(0, Bundle().apply { putString("stream", "FAIL: $error\n") })
        }
    }
}
