// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. CI-only platform lifecycle probe; no native injection.
package org.esdeplus.stub

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Process
import android.util.Log
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.ViewGroup
import java.io.File

class LifecycleProbe : Instrumentation() {
    private var mode = ""
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        mode = arguments?.getString("mode").orEmpty()
        start()
    }

    override fun callActivityOnCreate(activity: Activity, state: Bundle?) {
        super.callActivityOnCreate(activity, state)
        if (mode != "recreate-early" || activity.javaClass.name != "org.esdeplus.frontend.MainActivity") return
        fun surface(view: View): SurfaceView? {
            if (view is SurfaceView) return view
            if (view is ViewGroup) {
                for (index in 0 until view.childCount) surface(view.getChildAt(index))?.let { return it }
            }
            return null
        }
        val view = surface(activity.window.decorView) ?: error("No frontend surface")
        view.holder.addCallback(object : SurfaceHolder.Callback {
            private var triggered = false
            override fun surfaceCreated(holder: SurfaceHolder) {}
            override fun surfaceDestroyed(holder: SurfaceHolder) {}
            override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
                if (triggered) return
                check(Thread.getAllStackTraces().keys.any { it.name == "SDLThread" && it.isAlive })
                triggered = true
                Log.i("ES-DE-Plus-Probe", "Lifecycle probe triggering $mode pid=${Process.myPid()}")
                activity.recreate()
            }
        })
    }

    override fun onStart() {
        val result = Bundle()
        try {
            check(mode in listOf("recreate-early", "recreate-running", "finish-running"))
            val command = File("/data/local/tmp/esde-lifecycle-command")
            val activity = startActivitySync(Intent(Intent.ACTION_MAIN)
                .setClassName(targetContext.packageName, "org.esdeplus.frontend.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            check(activity.javaClass.name == "org.esdeplus.frontend.MainActivity")
            Log.i("ES-DE-Plus-Probe", "Lifecycle probe ready mode=$mode pid=${Process.myPid()}")
            val deadline = System.nanoTime() + 60_000_000_000L
            if (mode != "recreate-early") {
                while (!command.isFile) {
                    check(System.nanoTime() < deadline) { "External running-frontend barrier not reached" }
                    Thread.sleep(20)
                }
                runOnMainSync {
                    check(!activity.isFinishing && !activity.isDestroyed)
                    Log.i("ES-DE-Plus-Probe", "Lifecycle probe triggering $mode pid=${Process.myPid()}")
                    if (mode == "finish-running") activity.finish() else activity.recreate()
                }
            }
            // Host destruction must end this process, including the probe.
            // Keep it alive so instrumentation completion cannot hide a stall.
            Thread.sleep(30_000)
            error("Host process survived destruction")
        } catch (error: Throwable) {
            result.putString("stream", "FAIL: lifecycle probe $mode: $error\n")
            finish(0, result)
        }
    }
}
