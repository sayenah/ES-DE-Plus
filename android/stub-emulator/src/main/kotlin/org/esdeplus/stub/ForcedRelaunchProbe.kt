// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Test scheduling only; real overlay/configuration events.
package org.esdeplus.stub

import android.app.Activity
import android.app.Instrumentation
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.res.AssetManager
import android.os.Bundle
import android.util.Log
import java.io.File

class ForcedRelaunchProbe : Instrumentation() {
    private var mode = ""
    @Volatile private var blocked = false

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        mode = arguments?.getString("mode").orEmpty()
        start()
    }

    override fun callActivityOnCreate(activity: Activity, state: Bundle?) {
        super.callActivityOnCreate(activity, state)
        if (mode != "copy" || activity.javaClass.name != "org.esdeplus.frontend.MainActivity") return
        val bridge = activity.javaClass.getDeclaredMethod("getBridge").apply { isAccessible = true }.invoke(activity)
        val field = bridge.javaClass.getDeclaredField("context").apply { isAccessible = true }
        val original = field.get(bridge) as Context
        field.set(bridge, object : ContextWrapper(original) {
            override fun getAssets(): AssetManager {
                if (!blocked && Thread.currentThread().name == "SDLThread" &&
                    Thread.currentThread().stackTrace.any { it.methodName == "setupResources" &&
                        it.className == "org.esdeplus.frontend.NativeBridge" }) {
                    blocked = true
                    Log.i("ES-DE-Plus-Probe", "ASSETS copy barrier entered")
                    val destroying = activity.javaClass.getDeclaredField("destroying").apply { isAccessible = true }
                    val deadline = System.nanoTime() + 60_000_000_000L
                    while (!destroying.getBoolean(activity)) {
                        check(System.nanoTime() < deadline) { "Overlay did not destroy the copying host" }
                        Thread.sleep(1)
                    }
                    Log.i("ES-DE-Plus-Probe", "ASSETS copy barrier released by actual destruction")
                }
                return super.getAssets()
            }
        })
    }

    override fun onStart() {
        try {
            check(mode in listOf("copy", "configurator"))
            if (mode == "copy") {
                val certificate = File(targetContext.filesDir, "resources/certificates/curl-ca-bundle.crt")
                check(!certificate.exists() || certificate.delete())
            }
            val activity = startActivitySync(Intent(Intent.ACTION_MAIN)
                .setClassName(targetContext.packageName, "org.esdeplus.frontend.MainActivity")
                .addCategory(Intent.CATEGORY_LAUNCHER).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            if (mode == "configurator") {
                val command = File("/data/local/tmp/esde-assets-configurator")
                val deadline = System.nanoTime() + 60_000_000_000L
                while (!command.exists()) {
                    check(System.nanoTime() < deadline) { "Configurator command missing" }
                    Thread.sleep(20)
                }
                runOnMainSync {
                    val type = activity.classLoader.loadClass("org.esdeplus.frontend.ConfiguratorSession")
                    type.getMethod("open", Context::class.java, String::class.java)
                        .invoke(type.getField("INSTANCE").get(null), activity, null)
                }
            }
            // Never finish instrumentation to retire the host or manufacture a restart.
            Thread.sleep(180_000)
            error("Forced relaunch host did not retire")
        } catch (error: Throwable) {
            Log.e("ES-DE-Plus-Probe", "ASSETS probe failed", error)
            finish(0, Bundle().apply { putString("stream", "FAIL: $error\n") })
        }
    }
}
