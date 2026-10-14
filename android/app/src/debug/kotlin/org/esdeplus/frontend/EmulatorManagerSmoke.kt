// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Debug-only ZIP and user-data evidence fixtures.
package org.esdeplus.frontend

import android.content.Context
import org.esdeplus.frontend.bridge.RomTransport
import org.esdeplus.frontend.bridge.StorageModel
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

object EmulatorManagerSmoke {
    fun fixture(context: Context, mode: String): String {
        val data = StorageModel(context).appData()
        val root = RomTransport(context).root()
        val directory = File(root, "ps3")
        val lower = File(directory, "ESDEPlus Manager Test.zip")
        val upper = File(directory, "ESDEPlus Upper Test.ZIP")
        val gamelist = File(data, "gamelists/ps3/gamelist.xml")
        when (mode) {
            "emulator-manager-prepare" -> {
                check(!lower.exists() && !upper.exists() && !gamelist.exists())
                check(directory.mkdirs() || directory.isDirectory)
                ZipOutputStream(lower.outputStream()).use {
                    it.putNextEntry(ZipEntry("original-bytes.rom"))
                    it.write(byteArrayOf(69, 83, 68, 69, 0, -1, 42))
                    it.closeEntry()
                }
                upper.writeBytes(lower.readBytes())
                check(!File(directory, "original-bytes.rom").exists())
            }
            "emulator-manager-read" -> Unit
            "emulator-manager-cleanup" -> {
                for (file in listOf(lower, upper)) {
                    if (file.exists()) {
                        check(file.readBytes().take(2) == listOf<Byte>(80, 75))
                        check(file.delete())
                    }
                }
                if (gamelist.exists()) {
                    check(gamelist.readText().contains("EMUPLUS TEST"))
                    check(gamelist.delete())
                }
                check(!File(directory, "original-bytes.rom").exists())
            }
            else -> error("Unknown emulator-manager fixture mode")
        }
        fun contents(relative: String): String? = File(data, relative).let { if (it.exists()) it.readText() else null }
        val output = JSONObject().put("dataRoot", data.path).put("root", root.path).put("file", lower.path).put("upper", upper.path)
            .put("sha256", if (lower.exists()) MessageDigest.getInstance("SHA-256").digest(lower.readBytes())
                .joinToString("") { "%02x".format(it) } else "")
            .put("systems", contents("custom_systems/es_systems.xml") ?: JSONObject.NULL)
            .put("rules", contents("custom_systems/es_find_rules.xml") ?: JSONObject.NULL)
            .put("gamelist", contents("gamelists/ps3/gamelist.xml") ?: JSONObject.NULL)
            .put("extracted", File(directory, "original-bytes.rom").exists())
        check(!output.getBoolean("extracted"))
        return "PASS: emulator-manager fixture at selected roots; no extraction\nEMULATOR_MANAGER_JSON=$output\n"
    }
}
