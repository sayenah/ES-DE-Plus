// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using Android SDK APIs.
// App-UID fixture preparation/restoration for the search entry touch-session checks.
package org.esdeplus.frontend

import android.content.Context
import android.graphics.Bitmap
import java.io.File
import org.esdeplus.frontend.bridge.StorageModel
import org.json.JSONObject

internal object SearchEntrySmokeFixtures {
    private val paths = listOf("gamelists/nes/gamelist.xml", "settings/es_input.xml",
        "collections/custom-SearchEntrySmoke.cfg", "downloaded_media/nes/screenshots/Smoke Alpha.png")

    fun run(context: Context, request: String): String {
        val data = JSONObject(request)
        val operation = data.getString("operation")
        val root = StorageModel(context).appData().canonicalFile
        val state = context.getSharedPreferences("search-entry-smoke-fixtures", 0)
        fun file(index: Int) = File(root, paths[index])
        fun backup(index: Int) = File(context.cacheDir, "search-entry-original-$index")
        fun restore(index: Int) {
            if (state.getBoolean("exists-$index", false)) {
                check(file(index).parentFile!!.mkdirs() || file(index).parentFile!!.isDirectory)
                backup(index).copyTo(file(index), overwrite = true)
                check(file(index).readBytes().contentEquals(backup(index).readBytes()))
            } else check(!file(index).exists() || file(index).delete())
        }
        if (operation == "prepare") {
            check(!state.contains("root")) { "An earlier search fixture still needs restoration" }
            val editor = state.edit().putString("root", root.path)
            for (index in paths.indices) {
                editor.putBoolean("exists-$index", file(index).exists())
                if (file(index).exists()) file(index).copyTo(backup(index), overwrite = true)
            }
            check(editor.commit())
            val image = file(3)
            check(image.parentFile!!.mkdirs() || image.parentFile!!.isDirectory)
            val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(0xff3070c0.toInt())
            try {
                image.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
            } finally { bitmap.recycle() }
        } else {
            check(state.getString("root", "") == root.path) { "Fixture root changed" }
            when (operation) {
                "write" -> {
                    val index = paths.indexOf(data.getString("relative"))
                    check(index in 0..2) { "Only the three named text fixtures may be written" }
                    check(file(index).parentFile!!.mkdirs() || file(index).parentFile!!.isDirectory)
                    val contents = data.getString("contents")
                    file(index).writeText(contents)
                    check(file(index).readText() == contents)
                }
                "restore-one" -> {
                    val index = paths.indexOf(data.getString("relative"))
                    check(index in paths.indices)
                    restore(index)
                }
                "restore" -> {
                    for (index in paths.indices) restore(index)
                    check(state.edit().clear().commit())
                    for (index in paths.indices) backup(index).delete()
                }
                else -> error("Unknown fixture operation")
            }
        }
        return "PASS: search entry fixture $operation under frontend UID\n"
    }
}
