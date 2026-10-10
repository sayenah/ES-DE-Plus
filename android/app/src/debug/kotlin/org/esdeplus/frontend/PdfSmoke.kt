// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Real JNI/pixel assertions and viewer fault controls.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.content.Intent
import android.os.SystemClock
import java.io.File
import org.esdeplus.frontend.bridge.PdfManual

internal object PdfSmoke {
    init { System.loadLibrary("es-pdf-convert") }
    @JvmStatic external fun nativeProcess(path: String, mode: String, page: Int, width: Int, height: Int): ByteArray?

    private fun rejected(action: () -> Unit) {
        try { action() } catch (expected: IllegalStateException) { return }
        error("PDF assertion positive control escaped")
    }
    private fun pixel(bytes: ByteArray, width: Int, x: Int, y: Int, expected: IntArray) {
        val offset = (y * width + x) * 4
        val actual = (0..3).map { bytes[offset + it].toInt() and 255 }
        check(actual.zip(expected.toList()).all { (a, b) -> kotlin.math.abs(a - b) <= 8 }) {
            "BGRA probe at $x,$y: $actual expected ${expected.toList()} tolerance 8"
        }
    }
    private fun contract(root: File): String {
        val valid = File(root, "Manual spaces \uD83D\uDE80.pdf").absolutePath
        val expected = "1;portrait;240;320\n2;portrait;240;320\n3;portrait;320;240\n4;portrait;240;320\n5;portrait;320;240\n"
        fun metadata(value: String?) { check(value == expected) { "Metadata: $value" } }
        metadata(nativeProcess(valid, "-fileinfo", 0, 0, 0)?.toString(Charsets.US_ASCII))
        rejected { metadata(expected.replace("3;", "8;")) }
        fun raster(value: ByteArray?) { check(value?.size == 240 * 320 * 4) }
        val bytes = nativeProcess(valid, "-convert", 1, 240, 320)!!
        raster(bytes)
        rejected { raster(bytes.copyOf(bytes.size - 1)) }
        // PDF uses a bottom-left origin; D-008 pixels start at the top-left.
        pixel(bytes, 240, 25, 25, intArrayOf(0, 0, 255, 255))
        pixel(bytes, 240, 215, 295, intArrayOf(255, 0, 0, 255))
        pixel(bytes, 240, 25, 295, intArrayOf(0, 255, 0, 255))
        pixel(bytes, 240, 120, 160, intArrayOf(255, 255, 255, 255))
        pixel(bytes, 240, 80, 240, intArrayOf(255, 0, 255, 255)) // embedded RGB image
        rejected { pixel(bytes, 240, 25, 25, intArrayOf(255, 0, 0, 255)) }
        rejected { pixel(bytes, 240, 25, 295, intArrayOf(0, 0, 255, 255)) }
        fun opaque(value: ByteArray) { check(value.indices.filter { it % 4 == 3 }.all { value[it] == (-1).toByte() }) }
        opaque(bytes)
        rejected { opaque(bytes.clone().also { it[3] = 0 }) }
        fun text(value: ByteArray) {
            val ink = (45 until 70).sumOf { y -> (48 until 225).count { x ->
                val offset = (y * 240 + x) * 4
                (0..2).all { (value[offset + it].toInt() and 255) < 100 }
            } }
            check(ink > 100) { "Text ink unreadable: $ink" }
        }
        text(bytes)
        rejected { text(ByteArray(bytes.size) { (-1).toByte() }) }
        val probes = listOf(Triple(240, 320, 25 to 25), Triple(320, 240, 295 to 25),
                            Triple(240, 320, 215 to 295), Triple(320, 240, 25 to 215))
        for ((i, probe) in probes.withIndex()) {
            val (w, h, point) = probe
            val rendered = nativeProcess(valid, "-convert", i + 2, w, h)!!
            check(rendered.size == w * h * 4)
            pixel(rendered, w, point.first, point.second, intArrayOf(0, 0, 255, 255))
        }
        val before = File("/proc/self/fd").list()!!.size
        fun failure(path: String, mode: String = "-fileinfo", page: Int = 0, w: Int = 0, h: Int = 0) {
            check(nativeProcess(path, mode, page, w, h) == null) { "Expected failure: $path $mode $page $w $h" }
        }
        for (name in listOf("missing.pdf", "password.pdf", "zero.pdf", "malformed.pdf", "unreadable.pdf"))
            failure(File(root, name).absolutePath)
        failure("content://unsupported/manual.pdf")
        failure(valid, "unknown")
        failure(valid, "-fileinfo", 1)
        for ((page, w, h) in listOf(Triple(0, 1, 1), Triple(6, 1, 1), Triple(1, 0, 1),
                                  Triple(1, -1, 1), Triple(1, 4097, 1), Triple(1, 4096, 4096)))
            failure(valid, "-convert", page, w, h)
        // The largest permitted raster and a one-pixel-over byte limit have the same sides.
        check(nativeProcess(valid, "-convert", 1, 4096, 2048)?.size == 32 * 1024 * 1024)
        failure(valid, "-convert", 1, 4096, 2049)
        for (point in listOf(0, 1, 2)) {
            PdfManual.beforeCall = { if (it == point) throw java.io.IOException("Injected PDF failure at $point") }
            try { failure(valid, if (point == 0) "-fileinfo" else "-convert", point, if (point == 0) 0 else 240, if (point == 0) 0 else 320) }
            finally { PdfManual.beforeCall = null }
        }
        check(File("/proc/self/fd").list()!!.size == before) { "Renderer descriptor leak" }
        rejected { failure(valid) }
        // Concurrent calls also exercise the global open/render/close lock.
        val threads = (1..4).map { Thread { repeat(5) { check(nativeProcess(valid, "-convert", 1, 24, 32)?.size == 3072) } } }
        threads.forEach { it.start() }; threads.forEach { it.join() }
        return "PASS: D-008 real JNI metadata/BGRA/rows/white/aspect/crop/rotations/text/image; invalid/password/malformed/zero/unreadable/limits/injected failures; descriptors/serialisation; positive controls rejected"
    }

    fun session(instrumentation: Instrumentation): String {
        val context = instrumentation.targetContext
        val root = File(context.cacheDir, "pdf-fixtures").apply { mkdirs() }
        File("/data/local/tmp/esde-pdf-fixtures").listFiles()!!.forEach { it.copyTo(File(root, it.name), overwrite = true) }
        File(root, "unreadable.pdf").apply {
            File(root, "Manual spaces \uD83D\uDE80.pdf").copyTo(this, overwrite = true)
            check(setReadable(false, false))
        }
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val media = File(activity.getAppDataDirectory(), "Manual spaces \uD83D\uDE80")
        val manual = File(media, "nes/manuals/Smoke Alpha.pdf")
        manual.parentFile!!.mkdirs()
        val cover = File(media, "nes/covers/Smoke Alpha.png")
        cover.parentFile!!.mkdirs()
        File(root, "cover.png").copyTo(cover, overwrite = true)
        File(root, "Manual spaces \uD83D\uDE80.pdf").copyTo(manual, overwrite = true)
        val command = File(context.cacheDir, "pdf-command")
        val result = File(context.cacheDir, "pdf-result")
        command.delete(); result.writeText("READY: ${media.absolutePath}")
        var previous = ""
        val deadline = SystemClock.elapsedRealtime() + 1_200_000
        try {
            while (SystemClock.elapsedRealtime() < deadline) {
                val requested = if (command.isFile) command.readText().trim() else ""
                if (requested.isNotEmpty() && requested != previous) {
                    previous = requested
                    val action = requested.substringAfter(':')
                    val value = when {
                        action == "contract" -> contract(root)
                        action.startsWith("fault=") -> {
                            val point = action.substringAfter('=').toInt()
                            PdfManual.beforeCall = { if (it == point) throw java.io.IOException("Injected PDF viewer failure at $point") }
                            "FAULT: $point"
                        }
                        action == "reset" -> { PdfManual.beforeCall = null; "RESET" }
                        action.startsWith("fixture=") -> {
                            val name = action.substringAfter('=')
                            if (name == "missing") manual.delete()
                            else File(root, if (name == "valid") "Manual spaces \uD83D\uDE80.pdf" else "$name.pdf").copyTo(manual, overwrite = true)
                            "FIXTURE: $name"
                        }
                        action == "stats" -> "STATS: fd=${File("/proc/self/fd").list()!!.size}"
                        action == "end" -> return "PASS: PDF viewer session completed"
                        else -> error("Unknown PDF smoke command")
                    }
                    result.writeText("$requested\n$value")
                }
                Thread.sleep(50)
            }
            error("PDF smoke session deadline")
        } finally { PdfManual.beforeCall = null }
    }
}
