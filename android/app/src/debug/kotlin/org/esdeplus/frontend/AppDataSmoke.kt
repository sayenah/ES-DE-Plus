// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Authored fixtures from Settings.cpp and USERGUIDE.md.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.content.ContextWrapper
import android.content.Intent
import android.os.FileObserver
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.EditText
import org.esdeplus.frontend.bridge.StorageModel
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList

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
        val events = CopyOnWriteArrayList<String>()
        val observers = mutableListOf<FileObserver>()
        fun observe(file: File) {
            observers += object : FileObserver(file, FileObserver.ALL_EVENTS) {
                override fun onEvent(event: Int, path: String?) { events.add("${file.name}:$event:$path") }
            }.also { it.startWatching() }
        }
        fun hash(root: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            root.walkTopDown().sortedBy { it.path }.forEach {
                digest.update(it.relativeTo(root).path.toByteArray())
                if (it.isFile) digest.update(it.readBytes())
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
        var configurator: ConfiguratorActivity? = null
        try {
            val candidate = File(sandbox, "ES-DE").apply { check(mkdir()) }
            val settings = File(candidate, "settings/es_settings.xml")
            check(settings.parentFile!!.mkdir())
            settings.writeText("<string name=\"ROMDirectory\" value=\"/conflicting-roms\" />\n" +
                "<string name=\"MediaDirectory\" value=\"\" />\n")
            observe(candidate)
            observe(settings.parentFile!!)
            observe(settings)
            // Both evidence mechanisms have positive controls using actual reads
            // and writes. Never accept a quiet observer that cannot see access.
            val originalHash = hash(candidate)
            settings.readText()
            Thread.sleep(300)
            check(events.isNotEmpty()) { "FileObserver positive control saw no real reads" }
            settings.appendText("\n")
            check(hash(candidate) != originalHash) { "Tree hash positive control did not detect a write" }
            settings.writeText(settings.readText().removeSuffix("\n"))
            val before = hash(candidate)
            Thread.sleep(300)
            events.clear()
            configurator = probe.startActivitySync(Intent(context, ConfiguratorActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ConfiguratorActivity
            probe.runOnMainSync {
                configurator!!.findViewById<Button>(R.string.change_data_folder).performClick()
                configurator!!.findViewById<EditText>(R.string.data_path_hint).setText(candidate.path)
                configurator!!.findViewById<Button>(R.string.confirm_data_folder).performClick()
            }
            probe.waitForIdleSync()
            val dialog = probe.uiAutomation.rootInActiveWindow ?: error("Consent dialog missing")
            check(dialog.findAccessibilityNodeInfosByText("Concurrent use").isNotEmpty())
            val cancel = dialog.findAccessibilityNodeInfosByText("Cancel").single { it.text?.toString()?.equals("Cancel", true) == true }
            check(cancel.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            probe.waitForIdleSync()
            Thread.sleep(300)
            val beforeHash = events.toList()
            observers.forEach { it.stopWatching() }
            check(beforeHash.isEmpty()) { "Pre-consent access: $beforeHash" }
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
                }
                file.writeText("<string name=\"MediaDirectory\" value=\"${sandbox.path}/missing-media\"/>")
                rejected { storage.validateDataContents(candidate) }
                check(!File(sandbox, "missing-media").exists())
                file.writeText("<string name=\"MediaDirectory\" value=\"\"/>")
            }
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
                "obstructed themes, unavailable volume and overlap guards.\n"
        } finally {
            observers.forEach { it.stopWatching() }
            configurator?.let { probe.runOnMainSync { it.finish() } }
            check(sandbox.deleteRecursively())
        }
    }
}
