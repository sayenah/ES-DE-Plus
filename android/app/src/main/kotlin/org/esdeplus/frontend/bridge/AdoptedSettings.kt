// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from Settings.cpp and FileData.cpp's open formats.
package org.esdeplus.frontend.bridge

import android.util.Xml
import org.xmlpull.v1.XmlPullParser
import java.io.File
import java.io.IOException
import java.io.StringReader
import java.nio.charset.Charset

// Read only after destination consent. Native Settings remains the reader/writer
// of record; this preflight prevents an inaccessible media override falling
// through to native startup's best-effort directory creation.
internal object AdoptedSettings {
    fun settingsFile(root: File): File {
        val current = File(root, "settings/es_settings.xml")
        return if (current.exists()) current else File(root, "es_settings.xml")
    }

    fun mediaDirectory(root: File): File? {
        val file = settingsFile(root)
        if (!file.exists()) return null
        val bytes = file.readBytes()
        fun prefix(vararg values: Int) = bytes.size >= values.size &&
            values.indices.all { bytes[it].toInt() and 255 == values[it] }
        // Match pugixml's XML encoding autodetection before wrapping the
        // intentionally flat upstream settings fragments for the SDK parser.
        val encoding = when {
            prefix(255, 254, 0, 0) || prefix(60, 0, 0, 0) -> "UTF-32LE"
            prefix(0, 0, 254, 255) || prefix(0, 0, 0, 60) -> "UTF-32BE"
            prefix(255, 254) || prefix(60, 0) -> "UTF-16LE"
            prefix(254, 255) || prefix(0, 60) -> "UTF-16BE"
            else -> "UTF-8"
        }
        val contents = String(bytes, Charset.forName(encoding)).removePrefix("\uFEFF")
            .replaceFirst(Regex("^\\s*<\\?xml[^?]*\\?>"), "")
        val parser = Xml.newPullParser()
        parser.setInput(StringReader("<esdeplus>$contents</esdeplus>"))
        var nested: String? = null
        var flat: String? = null
        var inSettings = false
        var sawSettings = false
        while (parser.nextToken() != XmlPullParser.END_DOCUMENT) {
            if (parser.eventType == XmlPullParser.DOCDECL)
                throw IOException("Settings must not contain a document type declaration")
            if (parser.depth == 2 && parser.name == "settings") {
                if (parser.eventType == XmlPullParser.START_TAG) {
                    inSettings = !sawSettings
                    sawSettings = true
                }
                if (parser.eventType == XmlPullParser.END_TAG) inSettings = false
            }
            if (parser.eventType == XmlPullParser.START_TAG && parser.name == "string" &&
                parser.getAttributeValue(null, "name") == "MediaDirectory") {
                if (parser.depth == 2) flat = parser.getAttributeValue(null, "value").orEmpty()
                if (parser.depth == 3 && inSettings) nested = parser.getAttributeValue(null, "value").orEmpty()
            }
        }
        val value = flat ?: nested ?: return null
        if (value.isEmpty()) return null
        // FileSystemUtil::expandHomePath replaces every ~ on Android. Its
        // executable path stays empty because main skips parseArguments there.
        val expanded = value.replace("~", root.path).replace("%ESPATH%", "")
        return File(expanded)
    }
}
