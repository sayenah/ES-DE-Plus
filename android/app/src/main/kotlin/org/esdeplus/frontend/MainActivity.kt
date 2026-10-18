// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using SDL release-2.32.10 and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Intent
import android.os.Bundle
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import android.content.res.Configuration
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicBoolean
import org.libsdl.app.SDLActivity

open class MainActivity : SDLActivity() {
    private data class DeferredRestart(val configured: Boolean)
    @Volatile private var destroying = false
    @Volatile private var configured = false
    @Volatile private var restartRequested = false
    @Volatile private var deferringRestart = false
    private var visibleForRestart = false
    private var resumedForRestart = false
    private var awaitingCommittedEntry = false
    private val restartPrepared = AtomicBoolean(false)
    private val bridge by lazy { NativeBridge(applicationContext, recoverStartup = true) }
    override fun getLibraries(): Array<String> = arrayOf("SDL2", "main")
    override fun onCreate(savedInstanceState: Bundle?) {
        val deferred = deferredRestart
        awaitingCommittedEntry = deferred != null
        if (deferred != null) configured = deferred.configured
        live = WeakReference(this)
        Log.i("ES-DE-Plus", "Creating sole SDL activity task=$taskId")
        ConfiguratorSession.recordEntry(intent)
        super.onCreate(savedInstanceState)
        // SDL's JNI bindings are now ready; prepare cancellation before
        // onResume can start the native thread and its configuration query.
        if (!awaitingCommittedEntry) {
            if (!SDLActivity.mBrokenLibraries) ConfiguratorSession.registerNative()
            updateWindowSize()
            window.decorView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> updateWindowSize() }
        } else {
            Log.i("ES-DE-Plus", "Recreated frontend waiting for committed entry task=$taskId")
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.i("ES-DE-Plus", "SDL entry reused via onNewIntent")
        receiveEntry(intent)
    }
    fun receiveEntry(intent: Intent) {
        setIntent(intent)
        ConfiguratorSession.recordEntry(intent)
        if (ConfiguratorSession.configuring) ConfiguratorSession.open(applicationContext)
    }
    internal fun retireForEntry(intent: Intent) {
        setIntent(intent)
        ConfiguratorSession.recordEntry(intent)
        // This is an explicit new session, including when another entry task
        // was cleared. A foreground owner in the existing private helper VM
        // lets Android finish the old record before starting any new native main.
        // Unlike a configuration restore, an explicit entry also preserves a
        // pending configurator draft through the ordinary destruction path.
        deferringRestart = false
        deferredRestart = null
        if (restartPrepared.compareAndSet(false, true)) {
            FrontendRestartActivity.prepare(applicationContext, ConfiguratorSession.restartEntry())
            Log.i("ES-DE-Plus", "Clear-task entry retiring SDL session task=$taskId")
        }
        finish()
    }
    override fun onConfigurationChanged(configuration: Configuration) {
        super.onConfigurationChanged(configuration)
        if (!awaitingCommittedEntry) updateWindowSize()
        Log.i("ES-DE-Plus", "SDL activity configuration handled task=$taskId")
    }
    override fun onResume() {
        resumedForRestart = true
        super.onResume()
        observeCommittedEntry()
        // Re-present a pending startup screen after backgrounding or unlock;
        // user interaction never expires and HOME is still set only by entry.
        if (!awaitingCommittedEntry) {
            if (ConfiguratorSession.configuring) ConfiguratorSession.open(applicationContext)
            else bridge.checkStorageOnResume()
        }
    }
    // Framework recreation retires the old native process and restores
    // the recorded entry. Cached native settings/paths never switch in place.
    internal val nativePathsSelected: Boolean get() = bridge.pathsSelected
    internal val storageRecoveryVisible: Boolean get() = resumedForRestart && hasWindowFocus() &&
        !destroying && !isFinishing && !awaitingCommittedEntry
    internal fun restartAfterStorageSelection(): Boolean {
        if (!bridge.pathsSelected) return false
        Log.i("ES-DE-Plus", "Storage selection requires a fresh frontend start")
        // Save has validated and committed both roots. The configurator is in
        // front, so ordinary onStop visibility cannot authorize this restart.
        configured = true
        restartRequested = true
        prepareRestart()
        recreate()
        return true
    }
    override fun onPause() {
        resumedForRestart = false
        if (!isChangingConfigurations) visibleForRestart = false
        super.onPause()
    }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        // The recreated activity is a Java-side gate over retired native
        // globals. Neither focus nor a surface may start a second native main.
        if (!awaitingCommittedEntry) super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            observeCommittedEntry()
            if (!awaitingCommittedEntry) bridge.checkStorageOnResume()
        }
    }
    override fun resumeNativeThread() {
        if (!awaitingCommittedEntry) super.resumeNativeThread()
    }
    private fun observeCommittedEntry() {
        if (!resumedForRestart || !hasWindowFocus() || isFinishing) return
        visibleForRestart = true
        if (awaitingCommittedEntry && !restartRequested) {
            Log.i("ES-DE-Plus", "Frontend entry committed resumed=true focused=true task=$taskId")
            decideRestart(true)
        }
    }
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        // G-28 instrumentation: remove when its root cause is found or no first-key
        // loss occurs in 20 consecutive main runs, closing G-28 (D-024 am. 2).
        val traceInput = BuildConfig.DEBUG && Log.isLoggable("ESDE-PDF-CLOSE", Log.DEBUG)
        if (traceInput) Log.d("ES-DE-Plus", "Input dispatch begin uptime=${SystemClock.uptimeMillis()} " +
            "eventTime=${event.eventTime} action=${event.action} code=${event.keyCode} " +
            "repeat=${event.repeatCount} focus=${hasWindowFocus()} view=${currentFocus?.javaClass?.name}")
        val handled = super.dispatchKeyEvent(event)
        if (traceInput) Log.d("ES-DE-Plus", "Input dispatch end uptime=${SystemClock.uptimeMillis()} " +
            "eventTime=${event.eventTime} action=${event.action} code=${event.keyCode} handled=$handled")
        return handled
    }
    override fun onStop() {
        // Preserve a committed entry across configuration destruction only.
        if (!isChangingConfigurations) visibleForRestart = false
        super.onStop()
    }
    override fun finish() {
        // SDLMain finishes its old Activity after native quit. During a
        // deferred recreation that would remove the task being previewed.
        // A real finish was captured before this flag could become true.
        if (deferringRestart) {
            Log.i("ES-DE-Plus", "Ignoring retired SDL activity finish during deferred recreation")
            return
        }
        super.finish()
    }
    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (ConfiguratorSession.configuring) {
            ConfiguratorSession.open(applicationContext)
        } else if (mBrokenLibraries) {
            finish()
        } else {
            // Gesture/system Back uses the same upstream input policy as the
            // hardware Back key, including HOME and BackEventAppExit.
            SDLActivity.onNativeKeyDown(KeyEvent.KEYCODE_BACK)
            SDLActivity.onNativeKeyUp(KeyEvent.KEYCODE_BACK)
        }
    }
    override fun onDestroy() {
        if (awaitingCommittedEntry) {
            if (isFinishing || !isChangingConfigurations) {
                deferredRestart = null
                decideRestart(false)
            }
            destroying = true
            super.onDestroy()
            live = null
            if (deferredRestart == null) kotlin.system.exitProcess(0)
            return
        }
        // Cancellation can return native main, whose SDL thread calls finish().
        // Capture the framework's inputs once, before making cancellation visible.
        val finishing = isFinishing
        val changing = isChangingConfigurations
        val changes = changingConfigurations
        val visible = visibleForRestart
        val held = ConfiguratorSession.configuring
        val terminal = !held && !SDLActivity.mBrokenLibraries
        // ASSETS visibility is not commitment: AOSP BackNavigationController
        // setLaunchBehind() applies pending configuration before gesture commit.
        // Keep only a Java-side recreation until it is resumed AND focused.
        val assetsPathsChanged = (changes and Int.MIN_VALUE) != 0
        val requested = terminal && visible && changing && !finishing
        deferringRestart = terminal && !visible && assetsPathsChanged && changing && !finishing && configured
        if (deferringRestart) deferredRestart = DeferredRestart(configured)
        val destruction = "Destroying SDL activity held=$held " +
            "finishing=$finishing changingConfigurations=$changing " +
            "configurationChanges=0x${changes.toString(16)} task=$taskId " +
            "visibleForRestart=$visible assetsPathsChanged=$assetsPathsChanged"
        if (BuildConfig.DEBUG) Log.i("ES-DE-Plus", destruction, Throwable("SDL destruction caller"))
        else Log.i("ES-DE-Plus", destruction)
        if (deferringRestart) Log.i("ES-DE-Plus", "Frontend restart deferred until committed entry")
        else decideRestart(requested)
        // SDLMain clears mSDLThread before its final singleton.finish(). Keep
        // the reference so that finish cannot race recreation of the singleton.
        val retiringThread = if (deferringRestart) mSDLThread else null
        destroying = true
        // Task clear can destroy the root before pausing the configurator.
        // Save its scalar snapshot without calling a retained Activity.
        if (ConfiguratorSession.configuring) ConfiguratorSession.persistPendingDraft(applicationContext)
        // Every destruction retires this native process, including Android's
        // local relaunch after package/resource updates. SDL and the frontend
        // cannot initialise a second main over their retained native globals.
        // Startup/held quit polls may end it before the Java join returns.
        super.onDestroy()
        retiringThread?.join()
        Log.i("ES-DE-Plus", "SDL activity destroy join returned")
        live = null
        // A stopped ASSETS recreation may be only a back preview. Native
        // main has returned/joined; its VM stays idle until a committed entry
        // hands off to the existing helper and retires it. No native restart
        // is permitted in this VM, even if the preview is cancelled.
        if (terminal && !deferringRestart) kotlin.system.exitProcess(0)
    }
    private fun updateWindowSize() {
        bridge.windowSnapshot = if (Build.VERSION.SDK_INT >= 30) {
            windowManager.currentWindowMetrics.bounds.let { intArrayOf(it.width(), it.height()) }
        } else {
            resources.displayMetrics.let { intArrayOf(it.widthPixels, it.heightPixels) }
        }
    }
    // JNI instance methods; the keep rules preserve their names and exact descriptors.
    fun checkConfigurationNeeded(): Boolean {
        val needed = bridge.checkConfigurationNeeded()
        configured = !needed
        // Destruction can precede this first query. Valid configuration may
        // transfer the entry now, before native quit ends the process. A real
        // recovery hold keeps the existing saved-state/manual-restart policy.
        prepareRestart()
        return needed
    }
    private fun decideRestart(requested: Boolean) {
        Log.i("ES-DE-Plus", "Frontend restart decision requested=$requested " +
            "configured=$configured helperStarted=${restartPrepared.get()}")
        restartRequested = requested
        prepareRestart()
    }
    private fun prepareRestart() {
        if (restartRequested && configured && restartPrepared.compareAndSet(false, true)) {
            // An entry alias can be forwarded while the recreation waits.
            // Use the session's latest entry, as on the ordinary restart path.
            FrontendRestartActivity.prepare(applicationContext, ConfiguratorSession.restartEntry())
            Log.i("ES-DE-Plus", "Frontend restart helper started configured=true")
            if (awaitingCommittedEntry) kotlin.system.exitProcess(0)
        }
    }
    fun checkEmulatorInstalled(packageName: String, activityName: String) = bridge.checkEmulatorInstalled(packageName, activityName)
    fun checkNeedResourceCopy(buildIdentifier: String) = bridge.checkNeedResourceCopy(buildIdentifier)
    fun checkRACoreInstalled(packageName: String, coreFile: String) = bridge.checkRACoreInstalled(packageName, coreFile)
    fun getBatteryStatus() = bridge.getBatteryStatus()
    fun getBluetoothStatus() = bridge.getBluetoothStatus()
    fun getCellularStatus() = bridge.getCellularStatus()
    fun getCreateSystemDirectories() = bridge.getCreateSystemDirectories()
    fun getExternalDirectory() = bridge.getExternalDirectory()
    fun getInstalledApps(gamesOnly: Boolean, includeMedia: Boolean) = bridge.getInstalledApps(gamesOnly, includeMedia)
    fun getInternalDirectory() = bridge.getInternalDirectory()
    fun getWifiStatus() = bridge.getWifiStatus()
    fun getWindowSize() = bridge.getWindowSize()
    open fun getDeviceInfo() = bridge.getDeviceInfo()
    fun getInternalDataDirectory() = bridge.getInternalDataDirectory()
    fun getAppDataDirectory() = bridge.getAppDataDirectory()
    fun getROMDirectory() = bridge.getROMDirectory()
    fun launchGame(base: Array<String>, strings: Array<String>, lists: Array<String>, integers: Array<String>,
                   booleans: Array<String>, flags: Array<String>, otherScreen: Boolean) =
        bridge.launchGame(base, strings, lists, integers, booleans, flags, otherScreen)
    fun setupFontFiles() = bridge.setupFontFiles()
    fun setupLocalizationFiles() = bridge.setupLocalizationFiles()
    fun setupResources(buildIdentifier: String) = bridge.setupResources(buildIdentifier)
    fun startConfigurator() = bridge.startConfigurator()
    fun getPdfPageInfo(path: String): String? = org.esdeplus.frontend.bridge.PdfManual.pageInfo(path)
    fun renderPdfPage(path: String, page: Int, width: Int, height: Int): ByteArray? =
        org.esdeplus.frontend.bridge.PdfManual.render(path, page, width, height)
    fun onNativeFrontendResume() = bridge.onNativeFrontendResume()
    companion object {
        private var deferredRestart: DeferredRestart? = null
        private var live: WeakReference<MainActivity>? = null
        fun liveInstance(): MainActivity? = live?.get()?.takeUnless { it.isDestroyed }
        internal fun destructionRequested(): Boolean = live?.get()?.destroying == true
        @JvmStatic external fun nativeSetHold(hold: Boolean)
        @JvmStatic external fun nativeWaitForConfiguration()
        @JvmStatic external fun nativeSetHomeApp(home: Boolean)
        @JvmStatic external fun nativeSetResetTouchOverlay(reset: Boolean)
    }
}
