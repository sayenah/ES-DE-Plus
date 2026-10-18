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
    private var busyUntil = 0L

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        entry = arguments?.getString("entry") ?: entry
        start()
    }

    override fun callActivityOnCreate(activity: Activity, state: Bundle?) {
        if (activity.javaClass.name == "org.esdeplus.frontend.FrontendRedirectActivity") {
            val style = activity.resources.getIdentifier("ClearTaskProbeAnimations", "style", activity.packageName)
            check(style != 0) { "Missing debug transition resource" }
            activity.window.setWindowAnimations(style)
            Log.i("ES-DE-Plus-Probe", "Clear-task replacement transition barrier armed flags=0x${activity.intent.flags.toString(16)}")
            if (!armed) {
                armed = true
                busyUntil = SystemClock.uptimeMillis() + 30_000
                val handler = Handler(Looper.getMainLooper())
                // Framework stop/destroy/focus messages still run. No native
                // event, finish call, lifecycle callback or task is fabricated.
                handler.post(object : Runnable {
                    override fun run() {
                        if (SystemClock.uptimeMillis() < busyUntil) handler.post(this)
                        else Log.i("ES-DE-Plus-Probe", "Clear-task replacement idle barrier released")
                    }
                })
            }
        }
        super.callActivityOnCreate(activity, state)
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
