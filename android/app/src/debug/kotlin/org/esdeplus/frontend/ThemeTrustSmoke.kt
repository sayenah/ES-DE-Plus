// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. SDK-only theme storage evidence and fixture input.
package org.esdeplus.frontend

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.storage.StorageManager
import java.io.File
import org.esdeplus.frontend.bridge.StorageModel

@android.annotation.TargetApi(31)
object ThemeTrustSmoke {
    fun volumes(context: Context): String {
        val manager = context.getSystemService(StorageManager::class.java)
        return manager.storageVolumes.joinToString("\n") {
            "VOLUME primary=${it.isPrimary} removable=${it.isRemovable} " +
                "state=${it.state} uuid=${it.uuid} directory=${it.directory}"
        } + "\nPASS: app-context storage volumes\n"
    }

    fun clipboard(context: Context, path: String): String {
        check(path.startsWith('/') && '\u0000' !in path)
        // Clipboard input preserves Unicode through the ordinary EditText paste
        // action. It neither inspects the destination nor accepts configuration.
        context.getSystemService(ClipboardManager::class.java)
            .setPrimaryClip(ClipData.newPlainText("ES-DE-Plus fixture path", path))
        return "PASS: fixture path clipboard prepared\n"
    }

    fun restoreOrigin(context: Context): String {
        val root = File(StorageModel(context).appData(), "themes").canonicalFile
        val record = File(context.filesDir, "theme-trust.remote-race-path")
        val backup = File(context.filesDir, "theme-trust.remote-race-backup")
        val target = File(record.readText())
        check(target.path.startsWith(root.path + "/"))
        val parts = target.path.removePrefix(root.path + "/").split('/')
        check(parts.size == 3 && parts[0].matches(Regex("[A-Za-z0-9][A-Za-z0-9._-]*")) &&
            parts[1] == ".git" && parts[2] == "config")
        check(target.canonicalPath == target.absolutePath && target.isFile)
        val bytes = backup.readBytes()
        target.writeBytes(bytes)
        check(target.readBytes().contentEquals(bytes))
        check(record.delete() && backup.delete())
        return "PASS: actual theme origin fixture restored under app UID\n"
    }
}
