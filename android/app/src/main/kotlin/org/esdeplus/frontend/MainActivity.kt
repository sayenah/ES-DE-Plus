// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using SDL release-2.32.10 and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Intent
import android.os.Bundle
import android.os.Build
import android.util.Log
import android.view.KeyEvent
import android.content.res.Configuration
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicBoolean
import org.libsdl.app.SDLActivity

open class MainActivity : SDLActivity() {
    @Volatile private var destroying = false
    @Volatile private var configured = false
    @Volatile private var restartRequested = false
    private var visibleForRestart = false
    private val restartPrepared = AtomicBoolean(false)
    private val bridge by lazy { NativeBridge(applicationContext, recoverStartup = true) }
    override fun getLibraries(): Array<String> = arrayOf("SDL2", "main")
    override fun onCreate(savedInstanceState: Bundle?) {
        live = WeakReference(this)
        Log.i("ES-DE-Plus", "Creating sole SDL activity task=$taskId")
        ConfiguratorSession.recordEntry(intent)
        super.onCreate(savedInstanceState)
        // SDL's JNI bindings are now ready; prepare cancellation before
        // onResume can start the native thread and its configuration query.
        if (!SDLActivity.mBrokenLibraries) ConfiguratorSession.registerNative()
        updateWindowSize()
        window.decorView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> updateWindowSize() }
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
    override fun onConfigurationChanged(configuration: Configuration) {
        super.onConfigurationChanged(configuration)
        updateWindowSize()
        Log.i("ES-DE-Plus", "SDL activity configuration handled task=$taskId")
    }
    override fun onResume() {
        super.onResume()
        // Re-present a pending startup screen after backgrounding or unlock;
        // user interaction never expires and HOME is still set only by entry.
        if (ConfiguratorSession.configuring) ConfiguratorSession.open(applicationContext)
        else bridge.checkStorageOnResume()
    }
    // Framework recreation retires the old native process and restores
    // the recorded entry. Cached native settings/paths never switch in place.
    internal val nativePathsSelected: Boolean get() = bridge.pathsSelected
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
    override fun onStart() {
        super.onStart()
        visibleForRestart = true
    }
    override fun onStop() {
        // Framework relaunch sets changingConfigurations before stopping a
        // visible activity. Retain that pre-relaunch visibility, but clear it
        // on an ordinary stop behind a game; later background relaunch must
        // leave the game in front until the user enters the frontend again.
        if (!isChangingConfigurations) visibleForRestart = false
        super.onStop()
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
        destroying = true
        val terminal = !ConfiguratorSession.configuring && !SDLActivity.mBrokenLibraries
        val destruction = "Destroying SDL activity held=${ConfiguratorSession.configuring} " +
            "finishing=$isFinishing changingConfigurations=$isChangingConfigurations " +
            "configurationChanges=0x${changingConfigurations.toString(16)} task=$taskId " +
            "visibleForRestart=$visibleForRestart"
        if (BuildConfig.DEBUG) Log.i("ES-DE-Plus", destruction, Throwable("SDL destruction caller"))
        else Log.i("ES-DE-Plus", destruction)
        // A visible activity's non-finishing relaunch retains a foreground
        // owner while this process retires. The private Java activity waits for
        // actual process death; it cannot conceal a native quit/join stall.
        restartRequested = terminal && visibleForRestart && isChangingConfigurations && !isFinishing
        prepareRestart()
        // Task clear can destroy the root before pausing the configurator.
        // Save its scalar snapshot without calling a retained Activity.
        if (ConfiguratorSession.configuring) ConfiguratorSession.persistPendingDraft(applicationContext)
        // Every destruction retires this native process, including Android's
        // local relaunch after package/resource updates. SDL and the frontend
        // cannot initialise a second main over their retained native globals.
        // Startup/held quit polls may end it before the Java join returns.
        super.onDestroy()
        Log.i("ES-DE-Plus", "SDL activity destroy join returned")
        live = null
        if (terminal) kotlin.system.exitProcess(0)
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
    private fun prepareRestart() {
        if (restartRequested && configured && restartPrepared.compareAndSet(false, true))
            FrontendRestartActivity.prepare(applicationContext, ConfiguratorSession.restartEntry())
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
        private var live: WeakReference<MainActivity>? = null
        fun liveInstance(): MainActivity? = live?.get()?.takeUnless { it.isDestroyed }
        internal fun destructionRequested(): Boolean = live?.get()?.destroying == true
        @JvmStatic external fun nativeSetHold(hold: Boolean)
        @JvmStatic external fun nativeWaitForConfiguration()
        @JvmStatic external fun nativeSetHomeApp(home: Boolean)
        @JvmStatic external fun nativeSetResetTouchOverlay(reset: Boolean)
    }
}
