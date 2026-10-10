// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from D-008 and public Android PdfRenderer documentation.
package org.esdeplus.frontend.bridge

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import android.util.Log
import java.io.File
import org.esdeplus.frontend.BuildConfig

internal object PdfManual {
    // Debug instrumentation injects exceptions at the actual consumer boundary;
    // the hook has no file/device-specific behaviour and is removed in release.
    @Volatile internal var beforeCall: ((Int) -> Unit)? = null

    private inline fun <T> withDocument(path: String, operation: (PdfRenderer) -> T): T? {
        return try {
            require(path.startsWith('/') && '\u0000' !in path)
            val file = File(path)
            require(file.isFile && file.canRead())
            val descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
            val renderer = try { PdfRenderer(descriptor) }
            catch (error: Throwable) { descriptor.close(); throw error }
            // PdfRenderer owns the descriptor after successful construction.
            renderer.use { require(it.pageCount > 0); operation(it) }
        } catch (error: Exception) {
            Log.e("ES-DE-Plus", "PDF conversion failed", error)
            null
        } catch (error: OutOfMemoryError) {
            Log.e("ES-DE-Plus", "PDF raster allocation failed", error)
            null
        }
    }

    @Synchronized fun pageInfo(path: String): String? = withDocument(path) { renderer ->
        if (BuildConfig.DEBUG) beforeCall?.invoke(0)
        buildString {
            for (index in 0 until renderer.pageCount) {
                renderer.openPage(index).use { page ->
                    require(page.width > 0 && page.height > 0)
                    append(index + 1).append(";portrait;").append(page.width)
                        .append(';').append(page.height).append('\n')
                }
            }
        }
    }

    @Synchronized fun render(path: String, number: Int, width: Int, height: Int): ByteArray? {
        if (number < 1 || width !in 1..4096 || height !in 1..4096 ||
            width.toLong() * height * 4 > 32 * 1024 * 1024) return null
        return withDocument(path) { renderer ->
            require(number <= renderer.pageCount)
            if (BuildConfig.DEBUG) beforeCall?.invoke(number)
            renderer.openPage(number - 1).use { page ->
                val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                try {
                    bitmap.eraseColor(Color.WHITE)
                    page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    val bytes = ByteArray(width * height * 4)
                    // Explicit channel extraction avoids native-endian bitmap assumptions.
                    val row = IntArray(width)
                    for (y in 0 until height) {
                        bitmap.getPixels(row, 0, width, 0, y, width, 1)
                        for (x in 0 until width) {
                            val pixel = row[x]
                            val offset = (y * width + x) * 4
                            bytes[offset] = Color.blue(pixel).toByte()
                            bytes[offset + 1] = Color.green(pixel).toByte()
                            bytes[offset + 2] = Color.red(pixel).toByte()
                            bytes[offset + 3] = 255.toByte()
                        }
                    }
                    if (BuildConfig.DEBUG) Log.d("ES-DE-Plus", "PDF rendered page=$number size=${width}x$height")
                    bytes
                } finally { bitmap.recycle() }
            }
        }
    }
}
