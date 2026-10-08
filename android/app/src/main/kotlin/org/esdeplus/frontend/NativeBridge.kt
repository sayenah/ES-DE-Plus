// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the open C++ contract and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Context
import android.os.Build
import android.os.Environment
import android.util.AtomicFile
import android.util.Log
import org.esdeplus.frontend.bridge.StorageModel
import java.io.File
import java.io.IOException
import java.security.MessageDigest

class NativeBridge(private val context: Context, private val recoverStartup: Boolean = false) {
    private val storage = StorageModel(context)
    @Volatile var windowSnapshot: IntArray = intArrayOf(0, 0)
    private var earlyCopyFailed = false
    private val tag = "ES-DE-Plus"
    private val marker get() = File(context.filesDir, "resources-installed")
    private data class Resource(val hash: String, val size: Long, val path: String)
    private val manifest by lazy {
        context.assets.open("resource-manifest.tsv").bufferedReader().use { it.readText() }
    }
    private val manifestHash by lazy {
        MessageDigest.getInstance("SHA-256").digest(manifest.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
    private val entries by lazy {
        manifest.lineSequence().filter { it.isNotEmpty() }.let { lines ->
            lines.map { line ->
                val parts = line.split('\t', limit = 3)
                require(parts.size == 3 && parts[0].matches(Regex("[a-f0-9]{64}")))
                val size = parts[1].toLong()
                require(size >= 0)
                val path = parts[2]
                require(!path.startsWith('/') && path.split('/').none { it == ".." || it.isEmpty() })
                Resource(parts[0], size, path)
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
    private fun installed(verifyHashes: Boolean = false): Boolean = entries.all { (hash, size, path) ->
        val file = destination(path)
        file.isFile && file.length() == size && (!verifyHashes || digest(file) == hash)
    }
    private fun currentManifest(): Boolean = marker.isFile &&
        marker.readLines().getOrNull(1) == manifestHash
    // On a normal start no installed resource contents are read. A new manifest,
    // missing marker/file or size mismatch selects installation/repair verification.
    private val verifyEarly by lazy { !currentManifest() || !installed() }
    private fun writeAtomic(file: File, write: (java.io.OutputStream) -> Unit) {
        if (!file.parentFile!!.isDirectory && !file.parentFile!!.mkdirs())
            throw IOException("Cannot create ${file.parent}")
        val atomic = AtomicFile(file)
        val stream = atomic.startWrite()
        try { write(stream); atomic.finishWrite(stream) }
        catch (error: Throwable) { atomic.failWrite(stream); throw error }
    }
    private fun copyMatching(verifyHashes: Boolean, select: (String) -> Boolean) {
        entries.filter { select(it.path) }.forEach { (hash, size, path) ->
            val output = destination(path)
            if (!output.isFile || output.length() != size || (verifyHashes && digest(output) != hash)) {
                writeAtomic(output) { stream -> context.assets.open(path).use { it.copyTo(stream) } }
                if (output.length() != size || digest(output) != hash) throw IOException("Resource verification failed: $path")
                Log.i(tag, "Installed resource: $path")
            }
        }
    }
    @Synchronized fun checkNeedResourceCopy(buildIdentifier: String): Boolean = try {
        val needed = !marker.isFile || marker.readText() != "$buildIdentifier\n$manifestHash" || !installed()
        Log.i(tag, "Resource copy required=$needed build=$buildIdentifier")
        needed
    } catch (error: Exception) {
        Log.e(tag, "Resource inventory check failed", error); true
    }
    @Synchronized fun setupFontFiles() { copyEarly("fonts/") }
    @Synchronized fun setupLocalizationFiles() { copyEarly("locale/") }
    private fun copyEarly(prefix: String) {
        while (true) {
            try { copyMatching(verifyEarly) { it.startsWith(prefix) }; return }
            catch (error: Exception) {
                Log.e(tag, "Early resource copy failed: $prefix", error)
                if (!recoverStartup) { earlyCopyFailed = true; return }
                ConfiguratorSession.awaitResourceRetry(context, error.message ?: "Resource copy failed")
            }
        }
    }
    @Synchronized fun setupResources(buildIdentifier: String): Boolean {
        if (earlyCopyFailed) return true
        while (true) {
            try {
                copyMatching(true) { true }
                if (!installed(true)) throw IOException("Incomplete resource installation")
                writeAtomic(marker) { it.write("$buildIdentifier\n$manifestHash".toByteArray(Charsets.UTF_8)) }
                Log.i(tag, "Resource installation committed build=$buildIdentifier")
                return false
            } catch (error: Exception) {
                Log.e(tag, "Resource installation failed", error)
                if (!recoverStartup) return true
                ConfiguratorSession.awaitResourceRetry(context, error.message ?: "Resource copy failed")
            }
        }
    }
    fun getAppDataDirectory(): String = storage.verifyDirectory(storage.appData(), true).path
    // FileData/createSystemDirectories require the final slash.
    fun getROMDirectory(): String = storage.validate(storage.load()
        ?: throw IOException("Storage has not been configured")).path + "/"
    fun getInternalDataDirectory(): String = context.filesDir.absolutePath
    fun getInternalDirectory(): String = context.filesDir.parentFile!!.parentFile!!.absolutePath
    @Suppress("DEPRECATION")
    fun getExternalDirectory(): String = Environment.getExternalStorageDirectory().absolutePath
    fun getCreateSystemDirectories(): Boolean = storage.load()?.createSystems ?: false
    fun checkConfigurationNeeded(): Boolean = storage.problem() != null
    fun checkEmulatorInstalled(packageName: String, activityName: String): Boolean = false
    fun checkRACoreInstalled(packageName: String, coreFile: String): Int = -2
    fun getInstalledApps(gamesOnly: Boolean, includeMedia: Boolean): Array<String> = emptyArray()
    fun launchGame(base: Array<String>, strings: Array<String>, lists: Array<String>, integers: Array<String>,
                   booleans: Array<String>, flags: Array<String>, otherScreen: Boolean): Int {
        Log.i(tag, "Game launching unavailable in this build")
        return -1
    }
    fun getWindowSize(): IntArray = windowSnapshot.clone()
    fun getDeviceInfo(): String = "${Build.MANUFACTURER} ${Build.MODEL} API ${Build.VERSION.SDK_INT}"
    fun getBluetoothStatus(): Int = 0
    fun getWifiStatus(): Int = 0
    fun getCellularStatus(): Int = 0
    fun getBatteryStatus(): IntArray = intArrayOf(-1, -1)
    fun startConfigurator() { ConfiguratorSession.open(context, storage.problem()) }
    fun onNativeFrontendResume() {}
}
