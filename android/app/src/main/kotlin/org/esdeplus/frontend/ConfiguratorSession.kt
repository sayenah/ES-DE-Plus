// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Native-library registration; no Activity callbacks.
package org.esdeplus.frontend

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.Bundle
import android.util.Log
import java.io.IOException
import java.util.UUID

object ConfiguratorSession {
    private val monitor = Object()
    @Volatile private var registered = false
    @Volatile var configuring = false
        private set
    @Volatile var resourceFailure: String? = null
        private set
    @Volatile private var entry = Intent()
    @Volatile var home = false
        private set
    private val draftStrings = listOf("mode", "path", "tree", "typedPath", "message")
    private val draftBooleans = listOf("createSystems", "permissionPending", "resourceError")
    @Volatile private var pendingDraft: Bundle? = null
    private var currentSession: String? = null

    @Synchronized fun session(context: Context): String {
        currentSession?.let { return it }
        return (context.getSharedPreferences("configurator-draft", Context.MODE_PRIVATE)
            .getString("session", null) ?: UUID.randomUUID().toString()).also { currentSession = it }
    }

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
            .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra("session", session(app))
            .putExtra("entry", entry).putExtra("message", message ?: resourceFailure)
        Handler(Looper.getMainLooper()).post {
            // A retained configurator may be below a newly started SDL host
            // after process death. Move it above that host without clearing it.
            val frontend = MainActivity.liveInstance()
            if (frontend != null) frontend.startActivity(launch)
            else app.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    fun finishConfiguration() {
        configuring = false
        if (registered) MainActivity.nativeSetHold(false)
        Log.i("ES-DE-Plus", "Native startup hold released")
    }

    // Only the native startup thread waits. User interaction has no timeout.
    // Retry wakes that thread; the failed operation is executed again there.
    fun awaitResourceRetry(context: Context, message: String) {
        synchronized(monitor) {
            resourceFailure = message
            open(context, message)
        }
        MainActivity.nativeWaitForConfiguration()
        synchronized(monitor) { resourceFailure = null }
    }

    fun retryResources(): Boolean = synchronized(monitor) {
        if (resourceFailure == null) return@synchronized false
        finishConfiguration()
        true
    }

    // App-private draft, separate from accepted storage configuration and
    // upstream user-data files. Persist before SDL destruction can end the VM.
    @Synchronized fun rememberDraft(state: Bundle) {
        if (state.getString("session") == currentSession) pendingDraft = Bundle(state)
    }

    fun persistPendingDraft(context: Context) { pendingDraft?.let { saveDraft(context, it) } }

    @Synchronized fun saveDraft(context: Context, state: Bundle) {
        if (state.getString("session") != session(context)) return
        val editor = context.getSharedPreferences("configurator-draft", Context.MODE_PRIVATE).edit().clear()
        editor.putString("session", currentSession)
        for (key in draftStrings) editor.putString(key, state.getString(key))
        for (key in draftBooleans) editor.putBoolean(key, state.getBoolean(key))
        editor.putInt("focusId", state.getInt("focusId"))
        @Suppress("DEPRECATION")
        val entry = state.getParcelable<Intent>("entry")
        editor.putString("entry", entry?.toUri(Intent.URI_INTENT_SCHEME))
        if (!editor.commit()) throw IOException(context.getString(R.string.configuration_save_failed))
        Log.i("ES-DE-Plus", "Configurator draft saved")
    }

    fun loadDraft(context: Context, sessionId: String): Bundle? {
        val preferences = context.getSharedPreferences("configurator-draft", Context.MODE_PRIVATE)
        if (!preferences.contains("mode") || preferences.getString("session", null) != sessionId) return null
        return Bundle().apply {
            putString("session", sessionId)
            for (key in draftStrings) putString(key, preferences.getString(key, null))
            for (key in draftBooleans) putBoolean(key, preferences.getBoolean(key, false))
            putInt("focusId", preferences.getInt("focusId", 0))
            preferences.getString("entry", null)?.let {
                putParcelable("entry", Intent.parseUri(it, Intent.URI_INTENT_SCHEME))
            }
        }
    }

    @Synchronized fun clearDraft(context: Context) {
        if (!context.getSharedPreferences("configurator-draft", Context.MODE_PRIVATE).edit().clear().commit())
            throw IOException(context.getString(R.string.configuration_save_failed))
        pendingDraft = null
        currentSession = null
        Log.i("ES-DE-Plus", "Configurator session draft cleared")
    }
}
