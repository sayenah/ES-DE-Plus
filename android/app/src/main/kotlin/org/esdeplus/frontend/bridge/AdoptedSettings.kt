// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from Settings.cpp and FileData.cpp's open formats.
package org.esdeplus.frontend.bridge

import android.system.Os
import android.util.Xml
import org.xmlpull.v1.XmlPullParser
import java.io.File
import java.io.IOException
import java.io.StringReader

// Read only after destination consent. Native Settings remains the reader/writer
// of record; this preflight prevents an inaccessible media override falling
// through to native startup's best-effort directory creation.
internal object AdoptedSettings {
    fun mediaDirectory(root: File): File? {
        val current = File(root, "settings/es_settings.xml")
        val file = if (current.exists()) current else File(root, "es_settings.xml")
        if (!file.exists()) return null
        val contents = file.readText().removePrefix("\uFEFF")
            .replaceFirst(Regex("^\\s*<\\?xml[^?]*\\?>"), "")
        val parser = Xml.newPullParser()
        parser.setInput(StringReader("<esdeplus>$contents</esdeplus>"))
        var nested: String? = null
        var flat: String? = null
        var inSettings = false
        while (parser.nextToken() != XmlPullParser.END_DOCUMENT) {
            if (parser.eventType == XmlPullParser.DOCDECL)
                throw IOException("Settings must not contain a document type declaration")
            if (parser.depth == 2 && parser.name == "settings") {
                if (parser.eventType == XmlPullParser.START_TAG) inSettings = true
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
        // Match FileData::getMediaDirectory: ~ is the selected application data
        // home on Android; %ESPATH% is the native executable's directory.
        val expanded = (if (value == "~" || value.startsWith("~/")) root.path + value.drop(1) else value)
            .replace("%ESPATH%", File(Os.readlink("/proc/self/exe")).parent.orEmpty())
        return File(expanded)
    }
}
