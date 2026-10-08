// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Native-library registration; no Activity callbacks.
package org.esdeplus.frontend

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log

object ConfiguratorSession {
    private val monitor = Object()
    @Volatile private var registered = false
    @Volatile var configuring = false
        private set
    @Volatile var resourceFailure: String? = null
        private set
    private var retry = 0
    @Volatile private var entry = Intent()
    @Volatile var home = false
        private set

    fun recordEntry(intent: Intent) {
        entry = Intent(intent).replaceExtras(null as android.os.Bundle?)
            .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        home = intent.component?.className == MainActivity::class.java.name.substringBeforeLast('.') + ".HomeEntry" &&
            intent.hasCategory(Intent.CATEGORY_HOME)
        if (registered) MainActivity.nativeSetHomeApp(home)
        Log.i("ES-DE-Plus", "Entry component=${intent.component} HOME=$home")
    }

    // Called only after SDL loads libmain. Function targets are static JNI
    // exports, independent of the current/destroyed activity. A new process
    // gets a new registration when its SDL activity loads the library.
    fun registerNative() {
        registered = true
        MainActivity.nativeSetHomeApp(home)
        MainActivity.nativeSetHold(configuring)
    }

    fun open(context: Context, message: String? = null) {
        configuring = true
        if (registered) MainActivity.nativeSetHold(true)
        val app = context.applicationContext
        val launch = Intent(app, ConfiguratorActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("entry", entry).putExtra("message", message ?: resourceFailure)
        Handler(Looper.getMainLooper()).post { app.startActivity(launch) }
    }

    fun finishConfiguration() {
        configuring = false
        if (registered) MainActivity.nativeSetHold(false)
        Log.i("ES-DE-Plus", "Configuration persisted; native hold released")
    }

    // Only the native startup thread waits. User interaction has no timeout.
    // Retry wakes that thread; the failed operation is executed again there.
    fun awaitResourceRetry(context: Context, message: String) {
        synchronized(monitor) {
            val previous = retry
            resourceFailure = message
            open(context, message)
            while (retry == previous) monitor.wait()
            resourceFailure = null
        }
    }

    fun retryResources(): Boolean = synchronized(monitor) {
        if (resourceFailure == null) return@synchronized false
        finishConfiguration()
        retry++
        monitor.notifyAll()
        true
    }
}
