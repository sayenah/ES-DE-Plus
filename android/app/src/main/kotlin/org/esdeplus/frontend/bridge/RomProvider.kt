// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using the platform ContentProvider API.
package org.esdeplus.frontend.bridge

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import java.io.File
import java.util.Locale

class RomProvider : ContentProvider() {
    override fun onCreate() = true
    private fun file(uri: Uri) = RomTransport(requireNotNull(context)).providerFile(uri)
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        require(mode == "r") { "ROM provider is read-only" }
        val selected = file(uri)
        val descriptor = ParcelFileDescriptor.open(selected, ParcelFileDescriptor.MODE_READ_ONLY)
        try {
            // Recheck the opened object as well as the path to catch a replaced
            // ancestor/symlink between canonicalisation and open.
            val opened = File("/proc/self/fd/${descriptor.fd}").canonicalFile
            require(opened == selected && file(uri) == opened)
            return descriptor
        } catch (error: Exception) { descriptor.close(); throw error }
    }
    override fun getType(uri: Uri): String = MimeTypeMap.getSingleton()
        .getMimeTypeFromExtension(file(uri).extension.lowercase(Locale.ROOT)) ?: "application/octet-stream"
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
                       selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val selected = file(uri)
        val columns = (projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE))
            .filter { it == OpenableColumns.DISPLAY_NAME || it == OpenableColumns.SIZE }.toTypedArray()
        return MatrixCursor(columns).apply {
            addRow(columns.map { if (it == OpenableColumns.DISPLAY_NAME) selected.name else selected.length() })
        }
    }
    override fun insert(uri: Uri, values: ContentValues?): Uri = throw SecurityException("ROM provider is read-only")
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int =
        throw SecurityException("ROM provider is read-only")
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int =
        throw SecurityException("ROM provider is read-only")
}
