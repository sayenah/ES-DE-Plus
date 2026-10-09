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
    private var storageOnly = false
    private var ownedAction: String? = null
    private var ownedDirectory: String? = null
    private var followupMode: String? = null
    private var userFileArguments: Bundle? = null
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        provisionOnly = arguments?.getString("mode") == "provision"
        storageOnly = arguments?.getString("mode") == "storage"
        followupMode = arguments?.getString("mode")
        if (followupMode in listOf("write-user-file", "remove-user-file")) userFileArguments = arguments
        if (arguments?.getString("mode") == "owned-fixture") {
            ownedAction = arguments.getString("action")
            ownedDirectory = arguments.getString("directory")
        }
        start()
    }
    override fun onStart() {
        val result = Bundle()
        try {
            if (userFileArguments != null) {
                result.putString("stream", LaunchSmoke.userFile(targetContext,
                    userFileArguments!!.getString("relative")!!,
                    if (followupMode == "write-user-file") userFileArguments!!.getString("contents")!! else null))
                finish(-1, result)
                return
            }
            if (followupMode == "launch-probe") {
                result.putString("stream", LaunchSmoke.run(targetContext))
                finish(-1, result)
                return
            }
            if (followupMode == "revoke-tree") {
                result.putString("stream", LaunchSmoke.revokeTree(targetContext))
                finish(-1, result)
                return
            }
            if (followupMode == "retained-configurator") {
                // Deterministically reproduce a retained configurator below a
                // new SDL activity. No timing retry, native quit injection or
                // storage preference is involved.
                val configurator = startActivitySync(Intent(targetContext, ConfiguratorActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ConfiguratorActivity
                val activity = startActivitySync(Intent(targetContext, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
                fun heldHost(live: MainActivity?, focused: Boolean) {
                    check(live === activity && !activity.isDestroyed && !activity.isFinishing &&
                        configurator.taskId == activity.taskId && ConfiguratorSession.configuring && focused) {
                        "Retained configurator destroyed, duplicated or obscured the new SDL host"
                    }
                }
                var focused = false
                val deadline = System.nanoTime() + 60_000_000_000L
                while (!focused && System.nanoTime() < deadline) {
                    runOnMainSync { focused = configurator.hasWindowFocus() && ConfiguratorSession.configuring }
                    Thread.sleep(100)
                }
                runOnMainSync {
                    heldHost(MainActivity.liveInstance(), focused)
                    rejectedCheck { heldHost(null, focused) }
                    rejectedCheck { heldHost(MainActivity.liveInstance(), false) }
                }
                // Also observe stability beyond the transition that used to
                // destroy the new SDL activity and end the process.
                Thread.sleep(2000)
                runOnMainSync { heldHost(MainActivity.liveInstance(), configurator.hasWindowFocus()) }
                result.putString("stream", "PASS: retained configurator reorders above the same live SDL host; positive controls rejected\n")
                finish(-1, result)
                return
            }
            if (followupMode == "configurator-session") {
                val storage = org.esdeplus.frontend.bridge.StorageModel(targetContext)
                val saved = storage.load() ?: error("Real configurator must save first")
                val session = ConfiguratorSession.session(targetContext)
                val draft = Bundle().apply {
                    putString("session", session)
                    putString("mode", "scoped")
                    putString("typedPath", "unsaved-session-text")
                }
                ConfiguratorSession.rememberDraft(draft)
                ConfiguratorSession.saveDraft(targetContext, draft)
                fun restored(id: String) {
                    check(ConfiguratorSession.loadDraft(targetContext, id)?.getString("typedPath") == "unsaved-session-text")
                }
                restored(session)
                rejectedCheck { restored("different-session") }
                fun cleared() { check(ConfiguratorSession.loadDraft(targetContext, session) == null) }
                rejectedCheck { cleared() }
                fun noConfiguration(needed: Boolean) { check(!needed) }
                rejectedCheck { noConfiguration(true) }
                noConfiguration(NativeBridge(targetContext, recoverStartup = true).checkConfigurationNeeded())
                cleared()
                val fresh = ConfiguratorSession.session(targetContext)
                fun distinct(id: String) { check(id != session) }
                distinct(fresh)
                rejectedCheck { distinct(session) }
                // A late pause from the retired screen cannot resurrect its
                // abandoned draft over this new configurator session.
                ConfiguratorSession.saveDraft(targetContext, draft)
                cleared()
                fun unchanged(selection: org.esdeplus.frontend.bridge.StorageModel.Configuration?) {
                    check(selection == saved)
                }
                unchanged(storage.load())
                rejectedCheck { unchanged(saved.copy(mode = "unsaved-mode")) }
                result.putString("stream", "PASS: session-matched draft only; no-config startup clears abandoned draft; positive controls rejected\n")
                finish(-1, result)
                return
            }
            if (ownedAction != null) {
                check(ownedDirectory in listOf("ES-DE-Plus", "ROMs"))
                val root = targetContext.getExternalFilesDir(null) ?: error("SDK-owned volume unavailable")
                val directory = File(root, ownedDirectory!!)
                val saved = File(root, ownedDirectory + ".smoke-saved")
                when (ownedAction) {
                    "block" -> {
                        check(!saved.exists() && directory.isDirectory)
                        check(directory.renameTo(saved))
                        directory.writeText("Directory obstruction")
                    }
                    "restore" -> {
                        check(saved.isDirectory && directory.isFile)
                        check(directory.delete() && saved.renameTo(directory))
                    }
                    "edit-systems" -> {
                        check(ownedDirectory == "ROMs")
                        val removed = File(directory, "3do")
                        check(removed.isDirectory && removed.deleteRecursively())
                        File(directory, "nes/systeminfo.txt").writeText("user-scoped-metadata\n")
                    }
                    "verify-systems" -> {
                        check(ownedDirectory == "ROMs")
                        check(!File(directory, "3do").exists()) { "Deleted system folder was regenerated" }
                        check(File(directory, "nes/systeminfo.txt").readText() == "user-scoped-metadata\n") {
                            "User system metadata was overwritten"
                        }
                    }
                    else -> error("Unknown owned fixture action")
                }
                result.putString("stream", "PASS: SDK-context owned fixture $ownedAction $ownedDirectory; no preferences changed\n")
                finish(-1, result)
                return
            }
            if (storageOnly) {
                val storage = org.esdeplus.frontend.bridge.StorageModel(targetContext)
                val selected = storage.load() ?: error("Real configurator has not saved a selection")
                check(selected.mode == "direct")
                storage.validate(selected)
                // Exercise loss of the SDK's current-user volume mapping using
                // the real persisted selection; no preferences/grants are injected.
                val missingVolume = org.esdeplus.frontend.bridge.StorageModel(object : ContextWrapper(targetContext) {
                    override fun getExternalFilesDirs(type: String?): Array<File?> = emptyArray()
                })
                try { missingVolume.validate(selected); error("Unavailable volume was substituted") }
                catch (expected: java.io.IOException) { /* Required recoverable refusal. */ }
                check(storage.load() == selected)
                storage.validate(selected)
                result.putString("stream", "PASS: real persisted direct selection rejects unavailable current-user SDK volume mapping; no substitution or preference changes\n")
                finish(-1, result)
                return
            }
            if (provisionOnly) {
                // Create ordinary SDK-owned directories before adb pushes files.
                // MainActivity is not launched and no resources/marker are installed.
                val storage = org.esdeplus.frontend.bridge.StorageModel(targetContext)
                storage.verifyDirectory(storage.appData(), true)
                val roms = File(storage.ownedROMs(), "nes")
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
            try {
                check(nativeProbe(directory.absolutePath, game.absolutePath)) { "Native bridge probe failed" }
            } finally {
                check(game.delete())
                check(directory.delete())
            }
            // Same-size corruption stays untouched on the cheap normal-start
            // path; explicit installation verifies hashes and repairs it. A size
            // mismatch selects repair even with a committed marker.
            val catalog = File(targetContext.filesDir, "resources/locale/en_US/LC_MESSAGES/en_US.mo")
            val original = catalog.readBytes()
            val identifier = File(targetContext.filesDir, "resources-installed").readLines().first()
            try {
                val changed = original.clone().also { it[0] = (it[0].toInt() xor 1).toByte() }
                catalog.writeBytes(changed)
                val normal = NativeBridge(targetContext)
                normal.setupFontFiles()
                normal.setupLocalizationFiles()
                check(!normal.checkNeedResourceCopy(identifier)) { "Normal start hashes installed files" }
                check(catalog.readBytes().contentEquals(changed)) { "Normal start re-read/hashed catalog contents" }
                check(!normal.setupResources(identifier)) { "Explicit hash repair failed" }
                check(catalog.readBytes().contentEquals(original))
                catalog.appendBytes(byteArrayOf(0))
                val repair = NativeBridge(targetContext)
                check(repair.checkNeedResourceCopy(identifier)) { "Size mismatch was not detected" }
                repair.setupFontFiles()
                repair.setupLocalizationFiles()
                check(!repair.setupResources(identifier))
                check(catalog.readBytes().contentEquals(original))
            } finally { catalog.writeBytes(original) }
            val storage = org.esdeplus.frontend.bridge.StorageModel(targetContext)
            for (uri in listOf(
                "content://unsupported.provider/tree/primary%3AROMs",
                "content://com.android.externalstorage.documents/tree/primary%3A..%2Fescape",
                "content://com.android.externalstorage.documents/tree/primary%3AES-DE",
                "content://com.android.externalstorage.documents/tree/unavailable-volume%3AROMs",
                "content://com.android.externalstorage.documents/tree/primary%3AAndroid%2Fdata",
                "content://com.android.externalstorage.documents/tree/primary%3AROMs/document/primary%3Aother")) {
                try { storage.resolveTree(android.net.Uri.parse(uri)); error("Unsafe tree was accepted: $uri") }
                catch (expected: java.io.IOException) { /* Real trust-boundary refusal. */ }
            }
            val unavailable = NativeBridge(object : ContextWrapper(targetContext) {
                override fun getExternalFilesDir(type: String?): File? = null
            })
            for (query in listOf(unavailable::getAppDataDirectory, unavailable::getROMDirectory)) {
                try { query(); error("Unavailable storage silently selected another directory") }
                catch (expected: java.io.IOException) { /* Required loud failure. */ }
            }
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
            result.putString("stream", "PASS: descriptors, CheckJNI 10000 calls, Unicode directory/file, sentinels, roots, real font-copy failure, cheap normal start, explicit hash/size repair, unavailable-storage rejection\n")
            finish(-1, result)
        } catch (error: Throwable) {
            result.putString("stream", "FAIL: ${error.stackTraceToString()}\n")
            finish(0, result)
        }
    }
    private fun rejectedCheck(action: () -> Unit) {
        try { action() }
        catch (expected: IllegalStateException) { return }
        error("Positive control escaped its production assertion")
    }
    companion object { @JvmStatic external fun nativeProbe(directory: String, game: String): Boolean }
}
