// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. CI-only platform lifecycle probe; no native injection.
package org.esdeplus.stub

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.content.Context
import android.content.ContextWrapper
import android.content.res.AssetManager
import android.os.Bundle
import android.os.Process
import android.os.Looper
import android.os.Handler
import android.util.Log
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class LifecycleProbe : Instrumentation() {
    private var mode = ""
    @Volatile private var earlyTriggered = false
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        mode = arguments?.getString("mode").orEmpty()
        start()
    }

    override fun callActivityOnCreate(activity: Activity, state: Bundle?) {
        super.callActivityOnCreate(activity, state)
        if (mode != "recreate-early" || activity.javaClass.name != "org.esdeplus.frontend.MainActivity") return
        if (earlyTriggered) return
        // Forward every real SDK result. Delay only the resource-copy call
        // after native window creation, then release it after SDL sends quit
        // and joins. Captured stacks are after this test barrier is released.
        val bridge = activity.javaClass.getDeclaredMethod("getBridge").apply { isAccessible = true }
            .invoke(activity)
        val field = bridge.javaClass.getDeclaredField("context").apply { isAccessible = true }
        val original = field.get(bridge) as Context
        field.set(bridge, object : ContextWrapper(original) {
            override fun getAssets(): AssetManager {
                if (!earlyTriggered && Thread.currentThread().name == "SDLThread" &&
                    Thread.currentThread().stackTrace.any { it.methodName == "setupResources" &&
                        it.className == "org.esdeplus.frontend.NativeBridge" }) {
                    earlyTriggered = true
                    val released = CountDownLatch(1)
                    Thread({
                        val deadline = System.nanoTime() + 20_000_000_000L
                        while (System.nanoTime() < deadline) {
                            val frames = Looper.getMainLooper().thread.stackTrace
                            if (frames.any { it.className == "java.lang.Thread" && it.methodName == "join" } &&
                                frames.any { it.methodName == "onDestroy" && it.className in listOf(
                                    "org.libsdl.app.SDLActivity", "org.esdeplus.frontend.MainActivity") }) {
                                Log.i("ES-DE-Plus-Probe", "Lifecycle startup barrier released after destruction quit/join")
                                released.countDown()
                                return@Thread
                            }
                            Thread.sleep(5)
                        }
                        Log.e("ES-DE-Plus-Probe", "FAIL: lifecycle startup barrier timed out")
                        released.countDown()
                    }, "LifecycleStartupBarrier").start()
                    Handler(Looper.getMainLooper()).post {
                        Log.i("ES-DE-Plus-Probe", "Lifecycle probe triggering $mode pid=${Process.myPid()}")
                        activity.recreate()
                    }
                    check(released.await(20, TimeUnit.SECONDS)) { "Startup barrier did not release" }
                }
                return super.getAssets()
            }
        })
    }

    override fun onStart() {
        val result = Bundle()
        try {
            check(mode in listOf("recreate-early", "recreate-running", "finish-running"))
            val command = File("/data/local/tmp/esde-lifecycle-command")
            if (mode == "recreate-early") {
                // Generated packaged content, not user data. Its real repair
                // enters setupResources after the native window exists.
                val certificate = File(targetContext.filesDir, "resources/certificates/curl-ca-bundle.crt")
                check(!certificate.exists() || certificate.delete()) { "Cannot prepare actual resource repair" }
            }
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
