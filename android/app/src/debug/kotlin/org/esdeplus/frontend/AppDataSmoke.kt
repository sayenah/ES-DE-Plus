// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Authored fixtures from Settings.cpp and USERGUIDE.md.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.content.ContextWrapper
import android.content.Intent
import android.os.FileObserver
import android.os.SystemClock
import android.system.Os
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.EditText
import org.esdeplus.frontend.bridge.StorageModel
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

internal object AppDataSmoke {
    private fun rejected(action: () -> Unit) {
        try { action() } catch (_: IOException) { return }
        error("Invalid storage passed validation")
    }

    fun run(probe: Instrumentation): String {
        val context = probe.targetContext
        val storage = StorageModel(context)
        val accepted = storage.load() ?: error("Select storage through the real configurator first")
        check(accepted.mode == "direct" && storage.broadAccess())
        val sandbox = File(storage.defaultData().parentFile, "ESDEPlusAppDataProbes")
        check(!sandbox.exists()) { "Probe directory already exists; refusing to overwrite it" }
        check(sandbox.mkdir())
        val events = CopyOnWriteArrayList<Triple<File, Int, String?>>()
        val observers = mutableListOf<FileObserver>()
        val barrierDirectory = File(context.cacheDir, "prf-consent-event-barrier").apply { check(mkdir()) }
        val barrierName = "event-barrier"
        val barrier = AtomicReference<CountDownLatch>()
        fun observe(file: File) {
            observers += object : FileObserver(file, FileObserver.ALL_EVENTS) {
                override fun onEvent(event: Int, path: String?) { events.add(Triple(file, event, path)) }
            }.also { it.startWatching() }
        }
        // Android dispatches this process's FileObservers from one inotify
        // queue/thread. A private-directory barrier drains earlier candidate
        // events without adding any control writes inside the candidate.
        observers += object : FileObserver(barrierDirectory, FileObserver.DELETE) {
            override fun onEvent(event: Int, path: String?) {
                if (path == barrierName && event and FileObserver.DELETE != 0) barrier.get()?.countDown()
            }
        }.also { it.startWatching() }
        fun drain() {
            val pending = CountDownLatch(1)
            barrier.set(pending)
            val marker = File(barrierDirectory, barrierName)
            marker.writeBytes(byteArrayOf(0))
            check(marker.delete())
            check(pending.await(10, TimeUnit.SECONDS)) { "Consent observer event barrier timed out" }
        }
        fun hash(root: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            root.walkTopDown().sortedBy { it.path }.forEach {
                digest.update(it.relativeTo(root).path.toByteArray())
                if (it.isFile) digest.update(it.readBytes())
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
        fun noAccess(observed: List<Triple<File, Int, String?>>) {
            check(observed.isEmpty()) { "Pre-consent access: $observed" }
        }
        fun rejectsAccess(observed: List<Triple<File, Int, String?>>) {
            try { noAccess(observed) }
            catch (_: IllegalStateException) { return }
            error("No-access assertion accepted an actual access control")
        }
        var configurator: ConfiguratorActivity? = null
        try {
            val candidate = File(sandbox, "ES-DE").apply { check(mkdir()) }
            val settings = File(candidate, "settings/es_settings.xml")
            check(settings.parentFile!!.mkdir())
            val contents = "<string name=\"ROMDirectory\" value=\"/conflicting-roms\" />\n" +
                "<string name=\"MediaDirectory\" value=\"\" />\n"
            settings.writeText(contents)
            observe(candidate)
            observe(settings.parentFile!!)
            // Watch the file itself as well: the shared-storage mount need not
            // deliver its reads as named child events on the parent directory.
            observe(settings)
            // Both evidence mechanisms have positive controls using actual reads
            // and writes. Never accept a quiet observer that cannot see access.
            val originalHash = hash(candidate)
            drain()
            events.clear()
            check(settings.readText() == contents)
            drain()
            val readEvents = events.toList()
            // Some shared-storage mounts report open/close but not ACCESS for
            // a real file read. Every event remains forbidden during consent;
            // require its exact-file OPEN, then prove the same no-access
            // assertion rejects it. Opening alone is already forbidden access;
            // all events, including ACCESS where delivered, remain monitored.
            check(readEvents.any { it.first == settings && it.third == null && it.second and FileObserver.OPEN != 0 }) {
                "FileObserver positive control missed the actual settings read: $readEvents"
            }
            rejectsAccess(readEvents)
            events.clear()
            check(candidate.list()?.contains("settings") == true)
            drain()
            val enumerationEvents = events.toList()
            check(events.any { it.first == candidate && it.third == null && it.second and FileObserver.OPEN != 0 }) {
                "FileObserver positive control saw no directory enumeration: $enumerationEvents"
            }
            rejectsAccess(enumerationEvents)
            settings.appendText("\n")
            check(hash(candidate) != originalHash) { "Tree hash positive control did not detect a write" }
            settings.writeText(contents)
            val before = hash(candidate)
            drain()
            events.clear()
            // Accessibility window publication is asynchronous even after the
            // app's main queue is idle. Connect before opening the UI, and
            // require the actual app window/text rather than its first snapshot.
            val automation = probe.uiAutomation
            fun windowWithText(text: String): AccessibilityNodeInfo {
                val deadline = SystemClock.uptimeMillis() + 10_000
                do {
                    val root = automation.rootInActiveWindow
                    if (root?.packageName?.toString() == context.packageName &&
                        root.findAccessibilityNodeInfosByText(text).isNotEmpty()) return root
                    SystemClock.sleep(50)
                } while (SystemClock.uptimeMillis() < deadline)
                error("Timed out waiting for app accessibility window: $text")
            }
            configurator = probe.startActivitySync(Intent(context, ConfiguratorActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ConfiguratorActivity
            probe.runOnMainSync {
                configurator!!.findViewById<Button>(R.string.change_data_folder).performClick()
                configurator!!.findViewById<EditText>(R.string.data_path_hint).setText(candidate.path)
                configurator!!.findViewById<Button>(R.string.confirm_data_folder).performClick()
            }
            probe.waitForIdleSync()
            val dialog = windowWithText("Concurrent use")
            val cancel = dialog.findAccessibilityNodeInfosByText("Cancel").single { it.text?.toString()?.equals("Cancel", true) == true }
            check(cancel.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            probe.waitForIdleSync()
            // Cancelling the warning after changing the destination must not
            // retain the old folder's consent or permit saving the new draft.
            probe.runOnMainSync {
                configurator!!.findViewById<Button>(R.string.continue_frontend).performClick()
            }
            probe.waitForIdleSync()
            windowWithText("Choose and confirm the application-data folder")
            drain()
            val beforeHash = events.toList()
            observers.forEach { it.stopWatching() }
            noAccess(beforeHash)
            check(hash(candidate) == before) { "Cancelling changed the destination tree" }
            check(storage.load() == accepted) { "Cancel changed accepted configuration" }
            probe.runOnMainSync { configurator!!.finish() }
            configurator = null
            ConfiguratorSession.clearDraft(context)

            // Structural checks do not inspect either the renamed or legacy name.
            for (name in listOf("Renamed", ".emulationstation")) {
                val destination = File(sandbox, name)
                check(storage.structuralPath(destination.path, data = true) == destination)
                check(!destination.exists())
            }
            for (path in listOf(storage.defaultData().parent!!,
                    File(storage.defaultData().parentFile, "Android/data/other").path,
                    File(sandbox, "../escape").path, "/storage/unavailable-volume/data")) {
                rejected { storage.structuralPath(path, data = true) }
            }
            rejected { storage.acceptPath(candidate.path) }
            rejected { storage.disjoint(candidate, candidate) }
            rejected { storage.disjoint(candidate, File(candidate, "ROMs")) }
            rejected { storage.disjoint(File(candidate, "data"), candidate) }
            storage.disjoint(candidate, File(sandbox, "ROMs"))
            // A real alias proves that equal filesystem objects can have
            // different path spellings. Neither root is accepted configuration.
            val aliases = File(context.cacheDir, "prf-overlap-aliases").apply { check(mkdir()) }
            val target = File(aliases, "target").apply { check(mkdir()) }
            val alias = File(aliases, "alias")
            try {
                Os.symlink(target.path, alias.path)
                storage.disjoint(alias, target)  // Positive control for the weaker spelling check.
                rejected { storage.verifyDisjoint(alias, target) }
                rejected { storage.verifyDisjoint(File(alias, "child"), target) }
                rejected { storage.verifyDisjoint(target, File(alias, "child")) }
                storage.verifyDisjoint(candidate, target)
                // SDK-owned paths are absolute, but need not be canonical.
                // Keep the existing scoped layout valid through such an alias.
                val canonicalRoot = target.canonicalFile
                val scopedData = File(canonicalRoot, "ES-DE-Plus").apply { check(mkdir()) }
                val scopedROMs = File(canonicalRoot, "ROMs").apply { check(mkdir()) }
                try {
                    val scoped = StorageModel(object : ContextWrapper(context) {
                        override fun getExternalFilesDir(type: String?): File? = alias
                    })
                    check(scoped.validate(StorageModel.Configuration("scoped", scopedROMs.path, "", false,
                        scopedData.path)) == scopedROMs)
                } finally { check(scopedData.delete()); check(scopedROMs.delete()) }
            } finally { check(alias.delete()); check(target.delete()); check(aliases.delete()) }

            storage.confirmData(candidate.path)
            // Current settings, legacy settings and both upstream XML encodings.
            val media = File(sandbox, "Media override").apply { check(mkdir()) }
            for (legacy in listOf(false, true)) {
                val file = if (legacy) File(candidate, "es_settings.xml") else settings
                if (legacy) check(settings.delete())
                for (wrapped in listOf(false, true)) {
                    val values = "<string name=\"ROMDirectory\" value=\"/conflicting-roms\"/>" +
                        "<string name=\"MediaDirectory\" value=\"${media.path}\"/>"
                    file.writeText("<?xml version=\"1.0\"?>\n" + if (wrapped) "<settings>$values</settings>" else values)
                    check(storage.validateDataContents(candidate) == media.path)
                    check(file.readText().contains("/conflicting-roms"))
                    for (encoding in listOf("UTF-8", "UTF-16LE", "UTF-16BE", "UTF-32LE", "UTF-32BE")) {
                        file.writeBytes(("<?xml version=\"1.0\"?>" + values).toByteArray(java.nio.charset.Charset.forName(encoding)))
                        check(storage.validateDataContents(candidate) == media.path)
                    }
                }
                file.writeText("<string name=\"MediaDirectory\" value=\"${sandbox.path}/missing-media\"/>")
                rejected { storage.validateDataContents(candidate) }
                check(!File(sandbox, "missing-media").exists())
                file.writeText("<string name=\"MediaDirectory\" value=\"%ESPATH%${media.path}\"/>")
                check(storage.validateDataContents(candidate) == media.path)
                val homeMedia = File(candidate, "media").apply { mkdirs() }
                file.writeText("<string name=\"MediaDirectory\" value=\"~/media\"/>")
                check(storage.validateDataContents(candidate) == homeMedia.path)
                val readonly = File(context.cacheDir, "prf-readonly-media").apply { check(mkdir()) }
                try {
                    file.writeText("<string name=\"MediaDirectory\" value=\"${readonly.path}\"/>")
                    check(readonly.setWritable(false, false))
                    rejected { storage.validateDataContents(candidate) }
                    check(readonly.setWritable(true, true))
                    check(storage.validateDataContents(candidate) == readonly.path)
                } finally { readonly.setWritable(true, true); check(readonly.delete()) }
                file.writeText("<string name=\"MediaDirectory\" value=\"\"/>")
            }
            val selectedSettings = File(candidate, "es_settings.xml")
            selectedSettings.writeText("<settings><string name=\"MediaDirectory\" value=\"${media.path}\"/></settings>" +
                "<settings><string name=\"MediaDirectory\" value=\"${sandbox.path}/ignored\"/></settings>")
            check(storage.validateDataContents(candidate) == media.path)
            selectedSettings.writeText("<string name=\"MediaDirectory\" value=\"${media.path}\"/>" +
                "<settings><string name=\"MediaDirectory\" value=\"${sandbox.path}/ignored\"/></settings>")
            check(storage.validateDataContents(candidate) == media.path)
            selectedSettings.writeText("<string name=\"MediaDirectory\" value=\"\"/>")
            val obstruction = File(candidate, "themes")
            obstruction.writeText("obstructed required directory")
            rejected { storage.validateDataContents(candidate) }
            check(obstruction.delete())
            val missing = accepted.copy(data = File(sandbox, "missing-root").path)
            rejected { storage.validate(missing) }
            check(!File(missing.data).exists())
            val unavailable = StorageModel(object : ContextWrapper(context) {
                override fun getExternalFilesDirs(type: String?): Array<File?> = emptyArray()
            })
            rejected { unavailable.validate(accepted) }
            check(storage.load() == accepted)
            return "PASS: real consent cancellation has no FileObserver access and identical tree hash; " +
                "both positive controls; accepted configuration unchanged; renamed/legacy destinations, " +
                "flat/wrapped and legacy-root settings, conflicting ROM, media overrides, missing media/root, " +
                "obstructed themes, unavailable volume and overlap guards.\n" +
                "Settings read rejected by no-access assertion: $readEvents\n" +
                "Directory enumeration rejected by no-access assertion: $enumerationEvents\n"
        } finally {
            observers.forEach { it.stopWatching() }
            configurator?.let { probe.runOnMainSync { it.finish() } }
            check(sandbox.deleteRecursively())
            check(barrierDirectory.delete())
        }
    }
}
