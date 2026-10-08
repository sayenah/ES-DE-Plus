// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using SDL release-2.32.10 and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Intent
import android.os.Bundle
import android.os.Build
import android.util.Log
import android.view.KeyEvent
import org.libsdl.app.SDLActivity

class MainActivity : SDLActivity() {
    private val bridge by lazy { NativeBridge(applicationContext, recoverStartup = true) }
    override fun getLibraries(): Array<String> = arrayOf("SDL2", "main")
    override fun loadLibraries() {
        super.loadLibraries()
        ConfiguratorSession.registerNative()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        ConfiguratorSession.recordEntry(intent)
        super.onCreate(savedInstanceState)
        updateWindowSize()
        window.decorView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> updateWindowSize() }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.i("ES-DE-Plus", "SDL entry reused via onNewIntent")
        setIntent(intent)
        ConfiguratorSession.recordEntry(intent)
        if (ConfiguratorSession.configuring) ConfiguratorSession.open(applicationContext)
    }
    override fun onResume() {
        super.onResume()
        // Re-present a pending startup screen after backgrounding or unlock;
        // user interaction never expires and HOME is still set only by entry.
        if (ConfiguratorSession.configuring) ConfiguratorSession.open(applicationContext)
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
        val terminal = isFinishing && !ConfiguratorSession.configuring && !SDLActivity.mBrokenLibraries
        // SDL first joins/stops its native thread. Only terminal Activity exit
        // then ends the VM, flushing native atexit logs and resetting globals
        // for the next launch; recreation and pending configuration keep it.
        super.onDestroy()
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
    fun checkConfigurationNeeded() = bridge.checkConfigurationNeeded()
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
    fun getDeviceInfo() = bridge.getDeviceInfo()
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
    fun onNativeFrontendResume() = bridge.onNativeFrontendResume()
    companion object {
        @JvmStatic external fun nativeSetHold(hold: Boolean)
        @JvmStatic external fun nativeSetHomeApp(home: Boolean)
        @JvmStatic external fun nativeSetResetTouchOverlay(reset: Boolean)
    }
}
