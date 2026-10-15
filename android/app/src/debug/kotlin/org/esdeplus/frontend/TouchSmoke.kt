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
import java.io.File
import org.json.JSONArray
import org.libsdl.app.SDLSurface

/** Inject complete physical-pointer streams into this app's own SDL window only. */
class TouchSmoke : Instrumentation() {
    private var script = ""
    private var menu = false
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        script = arguments?.getString("steps").orEmpty()
        menu = arguments?.getString("menu") == "true"
        start()
    }

    override fun onStart() {
        val result = Bundle()
        val record = StringBuilder()
        var active = emptyList<Pointer>()
        var downTime = 0L
        var surface: SDLSurface? = null
        try {
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
                if (surface != null && log.isFile && log.readText().contains("Application startup time:")) break
                SystemClock.sleep(100)
            }
            check(surface != null && log.isFile && log.readText().contains("Application startup time:")) {
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
