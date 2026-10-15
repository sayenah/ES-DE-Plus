// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Android SDK multi-pointer injection; no test framework.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.graphics.Bitmap
import java.io.File
import org.json.JSONArray
import org.libsdl.app.SDLSurface
import org.esdeplus.frontend.bridge.StorageModel

/** Inject complete physical-pointer streams into this app's own SDL window only. */
class TouchSmoke : Instrumentation() {
    private var script = ""
    private var menu = false
    private var asset = ""
    private var mode = ""
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        script = arguments?.getString("steps").orEmpty()
        menu = arguments?.getString("menu") == "true"
        asset = arguments?.getString("asset").orEmpty()
        mode = arguments?.getString("mode").orEmpty()
        start()
    }

    override fun onStart() {
        val result = Bundle()
        val record = StringBuilder()
        var active = emptyList<Pointer>()
        var downTime = 0L
        var surface: SDLSurface? = null
        try {
            if (mode == "kid-prepare" || mode == "kid-restore") {
                val gamelist = File(StorageModel(targetContext).appData(), "gamelists/nes/gamelist.xml")
                val backup = File(targetContext.cacheDir, "touch-kid-gamelist-backup")
                val state = targetContext.getSharedPreferences("touch-smoke-fixture", 0)
                if (mode == "kid-prepare") {
                    check(!state.contains("path")) { "Unrestored touch fixture" }
                    if (gamelist.exists()) gamelist.copyTo(backup, overwrite = true)
                    check(state.edit().putString("path", gamelist.absolutePath)
                        .putBoolean("existed", gamelist.exists()).commit())
                    check(gamelist.parentFile!!.mkdirs() || gamelist.parentFile!!.isDirectory)
                    gamelist.writeText("<gameList><game><path>./Smoke Alpha.nes</path><kidgame>true</kidgame></game>" +
                        "<game><path>./Smoke Beta.nes</path><kidgame>true</kidgame></game></gameList>")
                } else if (state.contains("path")) {
                    check(state.getString("path", "") == gamelist.absolutePath)
                    if (state.getBoolean("existed", false)) backup.copyTo(gamelist, overwrite = true)
                    else check(!gamelist.exists() || gamelist.delete())
                    check(state.edit().clear().commit())
                    backup.delete()
                }
                result.putString("stream", "PASS: $mode controlled gamelist fixture\n")
                finish(-1, result)
                return
            }
            val fixture = File(StorageModel(targetContext).appData(), "resources/graphics/overlay/button_a.svg")
            val invalid = "ES-DE-Plus controlled invalid overlay SVG fixture"
            if (asset.isNotEmpty()) {
                check(asset == "invalid" || asset == "restore")
                check(!fixture.exists() || fixture.readText() == invalid) { "Refuse to replace an unfamiliar asset" }
                if (asset == "restore") {
                    check(!fixture.exists() || fixture.delete())
                    result.putString("stream", "PASS: overlay asset fixture restored\n")
                    finish(-1, result)
                    return
                }
                check(fixture.parentFile!!.mkdirs() || fixture.parentFile!!.isDirectory)
                fixture.writeText(invalid)
                record.append("FIXTURE: invalid app-data resource override ${fixture.absolutePath}\n")
            }
            val previousLog = File(StorageModel(targetContext).appData(), "logs/es_log.txt")
                .takeIf { it.isFile }?.readText().orEmpty()
            val activity = startActivitySync(Intent(targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            fun find(view: View): SDLSurface? {
                if (view is SDLSurface) return view
                if (view is ViewGroup) for (i in 0 until view.childCount) {
                    val found = find(view.getChildAt(i))
                    if (found != null) return found
                }
                return null
            }
            val deadline = SystemClock.elapsedRealtime() + 60_000
            val log = File(activity.getAppDataDirectory(), "logs/es_log.txt")
            while (SystemClock.elapsedRealtime() < deadline) {
                runOnMainSync { surface = find(activity.window.decorView) }
                if (surface != null && log.isFile && log.readText() != previousLog &&
                    log.readText().contains("Application startup time:")) break
                SystemClock.sleep(100)
            }
            check(surface != null && log.isFile && log.readText() != previousLog &&
                log.readText().contains("Application startup time:")) {
                "Frontend did not become ready for owned-window touch injection"
            }
            SystemClock.sleep(1200) // Initial gestures are outside foreground blocking.
            if (menu) {
                sendKeyDownUpSync(KeyEvent.KEYCODE_ESCAPE)
                SystemClock.sleep(500)
            }
            val steps = JSONArray(script)
            check(steps.length() in 1..256)
            for (i in 0 until steps.length()) {
                val step = steps.getJSONObject(i)
                SystemClock.sleep(step.optLong("wait", 0).also { check(it in 0..5000) })
                val actionName = step.getString("action")
                if (actionName == "background") {
                    targetContext.startActivity(Intent(android.provider.Settings.ACTION_SETTINGS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    val until = SystemClock.elapsedRealtime() + 5000
                    while (SystemClock.elapsedRealtime() < until) {
                        var focused = true
                        runOnMainSync { focused = activity.hasWindowFocus() }
                        if (!focused) break
                        SystemClock.sleep(10)
                    }
                    record.append("LIFECYCLE: background with ${active.size} held pointers\n")
                    continue
                }
                if (actionName == "resume") {
                    val before = log.readText().split("InputOverlay: restored (resume)").size
                    targetContext.startActivity(Intent(targetContext, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
                    val until = SystemClock.elapsedRealtime() + 10_000
                    var ready = false
                    while (!ready && SystemClock.elapsedRealtime() < until) {
                        runOnMainSync { ready = activity.hasWindowFocus() }
                        ready = ready && log.readText().split("InputOverlay: restored (resume)").size > before
                        if (!ready) SystemClock.sleep(5)
                    }
                    check(ready) { "No explicit native foreground signal" }
                    record.append("LIFECYCLE: resumed; next event wait=${step.optLong("wait", 0)}\n")
                    continue
                }
                val points = step.getJSONArray("pointers")
                val pointers = (0 until points.length()).map { n ->
                    val p = points.getJSONObject(n)
                    Pointer(p.getInt("id"), p.getDouble("x").toFloat(), p.getDouble("y").toFloat())
                }
                check(pointers.size in 1..12 && pointers.map { it.id }.toSet().size == pointers.size)
                check(pointers.all { it.id in 0..31 && it.x.isFinite() && it.y.isFinite() &&
                    it.x in 0f..1f && it.y in 0f..1f })
                val ids = pointers.map { it.id }.toSet()
                val oldIds = active.map { it.id }.toSet()
                val changed = step.optInt("changed", pointers.first().id)
                val index = pointers.indexOfFirst { it.id == changed }
                val action = when (actionName) {
                    "down" -> {
                        check(active.isEmpty() && pointers.size == 1)
                        downTime = SystemClock.uptimeMillis()
                        MotionEvent.ACTION_DOWN
                    }
                    "pointer-down" -> {
                        check(index >= 0 && changed !in oldIds && ids == oldIds + changed)
                        MotionEvent.ACTION_POINTER_DOWN or (index shl MotionEvent.ACTION_POINTER_INDEX_SHIFT)
                    }
                    "move" -> { check(ids == oldIds); MotionEvent.ACTION_MOVE }
                    "pointer-up" -> {
                        check(index >= 0 && pointers.size > 1 && ids == oldIds)
                        MotionEvent.ACTION_POINTER_UP or (index shl MotionEvent.ACTION_POINTER_INDEX_SHIFT)
                    }
                    "up" -> { check(pointers.size == 1 && ids == oldIds); MotionEvent.ACTION_UP }
                    "cancel" -> { check(ids == oldIds); MotionEvent.ACTION_CANCEL }
                    else -> error("Unsupported touch action: $actionName")
                }
                var focused = false
                runOnMainSync { focused = activity.hasWindowFocus() && !activity.isFinishing }
                check(focused) { "Pointer injection refused outside the owned frontend window" }
                send(surface!!, pointers, action, downTime)
                record.append("INJECT $i $actionName changed=$changed ${pointers.joinToString()}\n")
                active = when (actionName) {
                    "up", "cancel" -> emptyList()
                    "pointer-up" -> pointers.filter { it.id != changed }
                    else -> pointers
                }
            }
            check(active.isEmpty()) { "Incomplete injection stream" }
            SystemClock.sleep(500)
            uiAutomation.takeScreenshot()?.let { bitmap ->
                File(targetContext.cacheDir, "touch-last.png").outputStream().use {
                    check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
                bitmap.recycle()
            }
            record.append("PASS: complete Android multi-pointer stream injected\n")
            result.putString("stream", record.toString())
            finish(-1, result)
        } catch (error: Throwable) {
            if (active.isNotEmpty() && surface != null) {
                try { send(surface!!, active, MotionEvent.ACTION_CANCEL, downTime) }
                catch (cancelError: Throwable) { record.append("CANCEL FAILED: $cancelError\n") }
            }
            result.putString("stream", "$record\nFAIL: $error\n${error.stackTraceToString()}")
            finish(0, result)
        }
    }

    private data class Pointer(val id: Int, val x: Float, val y: Float)

    private fun send(surface: SDLSurface, pointers: List<Pointer>, action: Int, downTime: Long) {
        val origin = IntArray(2)
        var width = 0
        var height = 0
        runOnMainSync {
            surface.getLocationOnScreen(origin)
            width = surface.width
            height = surface.height
        }
        check(width > 0 && height > 0)
        val properties = pointers.map { p -> MotionEvent.PointerProperties().apply {
            id = p.id; toolType = MotionEvent.TOOL_TYPE_FINGER
        } }.toTypedArray()
        val coordinates = pointers.map { p -> MotionEvent.PointerCoords().apply {
            x = origin[0] + p.x * width; y = origin[1] + p.y * height
            pressure = if ((action and MotionEvent.ACTION_MASK) == MotionEvent.ACTION_UP) 0f else 1f
            size = 1f
        } }.toTypedArray()
        val event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action,
            pointers.size, properties, coordinates, 0, 0, 1f, 1f, 0, 0,
            InputDevice.SOURCE_TOUCHSCREEN, 0)
        try { sendPointerSync(event) } finally { event.recycle() }
    }
}
