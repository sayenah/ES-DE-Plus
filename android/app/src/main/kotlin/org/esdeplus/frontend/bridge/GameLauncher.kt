// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from INSTALL.md and the open C++ launch caller.
package org.esdeplus.frontend.bridge

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import java.io.File

class GameLauncher(private val context: Context) {
    fun intent(base: Array<String>, strings: Array<String>, lists: Array<String>, integers: Array<String>,
               booleans: Array<String>, flags: Array<String>): Intent {
        require(base.size == 8)
        val intent = AppDiscovery(context).target(base[0], base[1])
        val transport = RomTransport(context)
        val rom = base[7]
        val grantUris = mutableListOf<Uri>()
        fun expand(value: String, data: Boolean): String {
            if (value.contains("%ROMPROVIDER%")) {
                require(data && value == "%ROMPROVIDER%") { "ROM provider is supported only as Intent data" }
                val uri = transport.provider(rom)
                grantUris.add(uri)
                return uri.toString()
            }
            var result = value
            if (result.contains("%ROMSAF%")) {
                val uri = transport.saf(rom)
                if (transport.holdsReadGrant(uri)) grantUris.add(uri)
                result = result.replace("%ROMSAF%", uri.toString())
            }
            if (result.contains("%ROM%")) result = result.replace("%ROM%", transport.raw(rom))
            result = result.replace("%BASENAME%", File(rom).nameWithoutExtension)
            return result
        }
        if (base[2].isNotEmpty()) intent.action = base[2]
        if (base[3].isNotEmpty()) intent.addCategory(base[3])
        if (base[5].isNotEmpty()) {
            val data = Uri.parse(expand(base[5], true))
            if (base[4].isEmpty()) intent.data = data
            else intent.setDataAndType(data, base[4])
        } else if (base[4].isNotEmpty()) intent.setDataAndType(null, base[4])
        fun pairs(values: Array<String>, put: (String, String) -> Unit) {
            require(values.size % 2 == 0)
            for (i in values.indices step 2) {
                require(values[i].isNotEmpty())
                put(values[i], values[i + 1])
            }
        }
        pairs(strings) { key, value -> intent.putExtra(key, expand(value, false)) }
        pairs(lists) { key, value ->
            require(!value.contains("%ROM%") && !value.contains("%ROMSAF%") && !value.contains("%ROMPROVIDER%"))
            intent.putExtra(key, stringArray(value))
        }
        pairs(integers) { key, value -> intent.putExtra(key, expand(value, false).toInt()) }
        pairs(booleans) { key, value ->
            intent.putExtra(key, when (expand(value, false)) {
                "true", "1" -> true
                "false", "0" -> false
                else -> error("Invalid boolean extra: $key")
            })
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        for (flag in flags) intent.addFlags(when (flag) {
            "%ACTIVITY_CLEAR_TASK%" -> Intent.FLAG_ACTIVITY_CLEAR_TASK
            "%ACTIVITY_CLEAR_TOP%" -> Intent.FLAG_ACTIVITY_CLEAR_TOP
            "%ACTIVITY_NO_HISTORY%" -> Intent.FLAG_ACTIVITY_NO_HISTORY
            else -> error("Unsupported activity flag: $flag")
        })
        if (grantUris.isNotEmpty()) {
            val distinct = grantUris.distinct()
            intent.clipData = ClipData.newRawUri("ROM", distinct.first()).apply {
                distinct.drop(1).forEach { addItem(ClipData.Item(it)) }
            }
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return intent
    }

    fun launch(base: Array<String>, strings: Array<String>, lists: Array<String>, integers: Array<String>,
               booleans: Array<String>, flags: Array<String>, otherScreen: Boolean): Int = try {
        if (otherScreen) Log.i("ES-DE-Plus", "Launch on other screen is deferred; using the default display")
        val intent = intent(base, strings, lists, integers, booleans, flags)
        context.startActivity(intent)
        Log.i("ES-DE-Plus", "Activity launch accepted: ${intent.component}; recipient file access is not confirmed")
        0
    } catch (error: Exception) {
        Log.e("ES-DE-Plus", "Game launch refused", error)
        -1
    }

    companion object {
        fun stringArray(value: String): Array<String> {
            val result = mutableListOf<String>()
            val item = StringBuilder()
            var i = 0
            while (i < value.length) {
                val c = value[i++]
                if (c == '\\' && i < value.length && value[i] == ',') item.append(value[i++])
                else if (c == '\\' && i + 1 < value.length && value[i] == '\\' && value[i + 1] == ',') {
                    // INSTALL.md's XML example represents an escaped comma
                    // with two backslashes. Accept that spelling as well.
                    item.append(','); i += 2
                }
                else if (c == ',') { result.add(item.toString()); item.clear() }
                else item.append(c)
            }
            result.add(item.toString())
            return result.toTypedArray()
        }
    }
}
