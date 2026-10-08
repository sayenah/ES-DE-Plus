// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Platform instrumentation; no test framework dependency.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.content.ContextWrapper
import android.content.Intent
import android.os.Bundle
import java.io.File

class RuntimeSmoke : Instrumentation() {
    private var provisionOnly = false
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        provisionOnly = arguments?.getString("mode") == "provision"
        start()
    }
    override fun onStart() {
        val result = Bundle()
        try {
            if (provisionOnly) {
                // Create ordinary SDK-owned directories before adb pushes files.
                // MainActivity is not launched and no resources/marker are installed.
                val bridge = NativeBridge(targetContext)
                bridge.getAppDataDirectory()
                val roms = File(bridge.getROMDirectory(), "nes")
                check(roms.mkdirs() || roms.isDirectory)
                result.putString("stream", "PROVISIONED: ${roms.absolutePath}\n")
                finish(-1, result)
                return
            }
            val activity = startActivitySync(Intent(targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            val deadline = System.nanoTime() + 60_000_000_000L
            while (!File(targetContext.filesDir, "resources-installed").isFile) {
                check(System.nanoTime() < deadline) { "Resource installation did not commit" }
                Thread.sleep(100)
            }
            val directory = File(activity.getROMDirectory(), "nes/Smoke\uD83D\uDE80")
            check(directory.mkdirs() || directory.isDirectory)
            val game = File(directory, "Game\uD83D\uDE80.nes")
            game.writeBytes(byteArrayOf(0))
            check(nativeProbe(directory.absolutePath, game.absolutePath)) { "Native bridge probe failed" }
            // A real file blocks directory creation in an isolated application-data root.
            val sandbox = File(targetContext.cacheDir, "resource-failure-probe")
            sandbox.deleteRecursively()
            check(File(sandbox, "resources").mkdirs())
            File(sandbox, "resources/fonts").writeText("Directory obstruction")
            val blockedContext = object : ContextWrapper(targetContext) {
                override fun getFilesDir(): File = sandbox
            }
            val blocked = NativeBridge(blockedContext)
            blocked.setupFontFiles()
            check(blocked.setupResources("runtime-probe")) { "Font failure reported success" }
            check(!File(sandbox, "resources-installed").exists())
            sandbox.deleteRecursively()
            result.putString("stream", "PASS: descriptors, CheckJNI 10000 calls, Unicode directory/file, sentinels, roots, real font-copy failure\n")
            finish(-1, result)
        } catch (error: Throwable) {
            result.putString("stream", "FAIL: ${error.stackTraceToString()}\n")
            finish(0, result)
        }
    }
    companion object { @JvmStatic external fun nativeProbe(directory: String, game: String): Boolean }
}
