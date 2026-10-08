// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the open C++ contract and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Context
import android.os.Build
import android.os.Environment
import android.util.AtomicFile
import android.util.Log
import java.io.File
import java.io.IOException
import java.security.MessageDigest

class NativeBridge(private val context: Context) {
    @Volatile var windowSize: IntArray = intArrayOf(0, 0)
    private var earlyCopyFailed = false
    private val firstRun = !File(context.filesDir, "resources-installed").isFile
    private val tag = "ES-DE-Plus"
    private val marker get() = File(context.filesDir, "resources-installed")
    private val entries by lazy {
        context.assets.open("resource-manifest.tsv").bufferedReader().useLines { lines ->
            lines.map { line ->
                val parts = line.split('\t', limit = 2)
                require(parts.size == 2 && parts[0].matches(Regex("[a-f0-9]{64}")))
                val path = parts[1]
                require(!path.startsWith('/') && path.split('/').none { it == ".." || it.isEmpty() })
                Pair(parts[0], path)
            }.toList()
        }
    }
    private fun destination(path: String): File = File(context.filesDir,
        if (path.startsWith("themes/")) path else "resources/$path")
    private fun digest(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(65536)
            while (true) { val n = input.read(buffer); if (n < 0) break; md.update(buffer, 0, n) }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
    private fun installed(): Boolean = entries.all { (hash, path) ->
        val file = destination(path)
        file.isFile && digest(file) == hash
    }
    private fun writeAtomic(file: File, write: (java.io.OutputStream) -> Unit) {
        if (!file.parentFile!!.isDirectory && !file.parentFile!!.mkdirs())
            throw IOException("Cannot create ${file.parent}")
        val atomic = AtomicFile(file)
        val stream = atomic.startWrite()
        try { write(stream); atomic.finishWrite(stream) }
        catch (error: Throwable) { atomic.failWrite(stream); throw error }
    }
    private fun copyMatching(select: (String) -> Boolean) {
        entries.filter { select(it.second) }.forEach { (hash, path) ->
            val output = destination(path)
            if (!output.isFile || digest(output) != hash) {
                writeAtomic(output) { stream -> context.assets.open(path).use { it.copyTo(stream) } }
                if (digest(output) != hash) throw IOException("Resource verification failed: $path")
                Log.i(tag, "Installed resource: $path")
            }
        }
    }
    @Synchronized fun checkNeedResourceCopy(buildIdentifier: String): Boolean = try {
        val needed = !marker.isFile || marker.readText() != buildIdentifier || !installed()
        Log.i(tag, "Resource copy required=$needed build=$buildIdentifier")
        needed
    } catch (error: Exception) {
        Log.e(tag, "Resource inventory check failed", error); true
    }
    @Synchronized fun setupFontFiles() { copyEarly("fonts/") }
    @Synchronized fun setupLocalizationFiles() { copyEarly("locale/") }
    private fun copyEarly(prefix: String) {
        try { copyMatching { it.startsWith(prefix) } }
        catch (error: Exception) {
            earlyCopyFailed = true
            Log.e(tag, "Early resource copy failed: $prefix", error)
        }
    }
    @Synchronized fun setupResources(buildIdentifier: String): Boolean {
        if (earlyCopyFailed) return true
        return try {
            copyMatching { true }
            if (!installed()) throw IOException("Incomplete resource installation")
            writeAtomic(marker) { it.write(buildIdentifier.toByteArray(Charsets.UTF_8)) }
            Log.i(tag, "Resource installation committed build=$buildIdentifier")
            false
        } catch (error: Exception) {
            Log.e(tag, "Resource installation failed", error); true
        }
    }
    private fun externalFiles(): File = context.getExternalFilesDir(null)
        ?: throw IOException("App-specific external storage is unavailable")
    private fun directory(file: File): String {
        if (!file.isDirectory && !file.mkdirs()) throw IOException("Cannot create $file")
        return file.absolutePath
    }
    fun getAppDataDirectory(): String = directory(File(externalFiles(), "ES-DE-Plus"))
    fun getROMDirectory(): String = directory(File(externalFiles(), "ROMs"))
    fun getInternalDataDirectory(): String = context.filesDir.absolutePath
    fun getInternalDirectory(): String = context.filesDir.parentFile!!.parentFile!!.absolutePath
    @Suppress("DEPRECATION")
    fun getExternalDirectory(): String = Environment.getExternalStorageDirectory().absolutePath
    fun getCreateSystemDirectories(): Boolean = firstRun
    fun checkConfigurationNeeded(): Boolean = false
    fun checkEmulatorInstalled(packageName: String, activityName: String): Boolean = false
    fun checkRACoreInstalled(packageName: String, coreFile: String): Int = -2
    fun getInstalledApps(gamesOnly: Boolean, includeMedia: Boolean): Array<String> = emptyArray()
    fun launchGame(base: Array<String>, strings: Array<String>, lists: Array<String>, integers: Array<String>,
                   booleans: Array<String>, flags: Array<String>, otherScreen: Boolean): Int {
        Log.i(tag, "Game launching unavailable in this build")
        return -1
    }
    fun getWindowSize(): IntArray = windowSize.clone()
    fun getDeviceInfo(): String = "${Build.MANUFACTURER} ${Build.MODEL} API ${Build.VERSION.SDK_INT}"
    fun getBluetoothStatus(): Int = 0
    fun getWifiStatus(): Int = 0
    fun getCellularStatus(): Int = 0
    fun getBatteryStatus(): IntArray = intArrayOf(-1, -1)
    fun startConfigurator() { Log.i(tag, "configurator not available in this build") }
    fun onNativeFrontendResume() {}
}
