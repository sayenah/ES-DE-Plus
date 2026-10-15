// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Android SDK multi-pointer injection; no test framework.
package org.esdeplus.frontend

import android.app.Activity
import android.app.Application
import android.app.Instrumentation
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import org.esdeplus.frontend.bridge.StorageModel
import org.json.JSONArray
import org.json.JSONObject
import org.libsdl.app.SDLActivity
import org.libsdl.app.SDLSurface

private fun findSurface(view: View): SDLSurface? {
    if (view is SDLSurface) return view
    if (view is ViewGroup) for (i in 0 until view.childCount) {
        val found = findSurface(view.getChildAt(i))
        if (found != null) return found
    }
    return null
}

/** Inject complete physical-pointer streams into this app's own SDL window only. */
class TouchSmoke : Instrumentation() {
    // Read the live View without restarting instrumentation/the frontend. An
    // accessibility rectangle can be clipped by a parent after fullscreen resize.
    class SurfaceGeometry : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val activity = SDLActivity.getContext() as? MainActivity
            val surface = activity?.let { findSurface(it.window.decorView) }
            if (activity == null || surface == null || !activity.hasWindowFocus() ||
                surface.width <= 0 || surface.height <= 0) {
                resultData = "FAIL: no owned focused SDL surface"
                return
            }
            val origin = IntArray(2)
            surface.getLocationOnScreen(origin)
            val frame = surface.holder.surfaceFrame
            val geometry = JSONObject().put("x", origin[0]).put("y", origin[1])
                .put("width", surface.width).put("height", surface.height)
                .put("bufferWidth", frame.width()).put("bufferHeight", frame.height())
            File(context.cacheDir, "touch-surface-geometry.json").writeText(geometry.toString())
            resultData = "PASS: owned surface geometry recorded"
        }
    }
    private val resumed = AtomicBoolean(false)
    private val lifecycle = object : Application.ActivityLifecycleCallbacks {
        override fun onActivityResumed(activity: Activity) {
            if (activity is MainActivity) resumed.set(true)
        }
        override fun onActivityPaused(activity: Activity) {
            if (activity is MainActivity) resumed.set(false)
        }
        override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) {}
        override fun onActivityStarted(activity: Activity) {}
        override fun onActivityStopped(activity: Activity) {}
        override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) {}
        override fun onActivityDestroyed(activity: Activity) {}
    }
    private var script = ""
    private var menu = ""
    private var asset = ""
    private var mode = ""
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        script = arguments?.getString("steps").orEmpty()
        menu = arguments?.getString("menu").orEmpty()
        asset = arguments?.getString("asset").orEmpty()
        mode = arguments?.getString("mode").orEmpty()
        start()
    }

    override fun onStart() {
        val result = Bundle()
        val record = StringBuffer()
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
            (targetContext.applicationContext as Application).registerActivityLifecycleCallbacks(lifecycle)
            val activity = startActivitySync(Intent(targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            val deadline = SystemClock.elapsedRealtime() + 60_000
            val log = File(activity.getAppDataDirectory(), "logs/es_log.txt")
            while (SystemClock.elapsedRealtime() < deadline) {
                runOnMainSync { surface = findSurface(activity.window.decorView) }
                if (surface != null && log.isFile && log.readText() != previousLog &&
                    log.readText().contains("Application startup time:")) break
                SystemClock.sleep(100)
            }
            check(surface != null && log.isFile && log.readText() != previousLog &&
                log.readText().contains("Application startup time:")) {
                "Frontend did not become ready for owned-window touch injection"
            }
            fun traceAndroidDelivery() {
                runOnMainSync {
                    val target = checkNotNull(surface)
                    target.setOnTouchListener { view, event ->
                        record.append("ANDROID action=${event.actionMasked} source=${event.source} device=${event.deviceId} " +
                            (0 until event.pointerCount).joinToString { n ->
                                "id=${event.getPointerId(n)} x=${event.getX(n)} y=${event.getY(n)} pressure=${event.getPressure(n)}"
                            } + "\n")
                        target.onTouch(view, event)
                    }
                }
            }
            traceAndroidDelivery()
            SystemClock.sleep(1200) // Initial gestures are outside foreground blocking.
            if (menu.isNotEmpty()) {
                check(menu == "true" || menu == "sound" || menu == "importer")
                // Sound settings: start on Video volume. Up selects Navigation
                // volume; Right must keep advancing it during a stationary hold.
                val keys = if (menu == "importer") listOf(KeyEvent.KEYCODE_ESCAPE) +
                    List(7) { KeyEvent.KEYCODE_DPAD_DOWN } +
                    listOf(KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_ENTER)
                    else if (menu == "sound") listOf(KeyEvent.KEYCODE_ESCAPE,
                    KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_DPAD_DOWN,
                    KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_DPAD_DOWN)
                    else listOf(KeyEvent.KEYCODE_ESCAPE)
                for (key in keys) {
                    val offset = log.readText().length
                    sendKeyDownUpSync(key)
                    val by = SystemClock.elapsedRealtime() + 20_000
                    while (SystemClock.elapsedRealtime() < by &&
                        !Regex("Window::logInput\\(Keyboard\\): .*value=0").containsMatchIn(log.readText().substring(offset)))
                        SystemClock.sleep(20)
                    check(Regex("Window::logInput\\(Keyboard\\): .*value=0").containsMatchIn(log.readText().substring(offset)))
                }
                SystemClock.sleep(500)
            }
            val steps = JSONArray(script)
            check(steps.length() in 1..256)
            val injectionOffset = log.readText().length
            val expectedUps = mutableMapOf<Int, Int>()
            val cancelledFingers = mutableSetOf<Int>()
            fun heldControls(text: String): Set<Int> {
                val held = mutableSetOf<Int>()
                Regex("Window::logInput\\(Touch\\): Button (\\d+), isMappedTo=.*?value=([01])")
                    .findAll(text).forEach { match ->
                        val id = match.groupValues[1].toInt()
                        if (match.groupValues[2] == "1") check(held.add(id)) { "Duplicate press $id" }
                        else check(held.remove(id)) { "Orphan release $id" }
                    }
                return held
            }
            fun snapshot(name: String) {
                check(name.matches(Regex("[a-z0-9-]{1,32}")))
                var focused = false
                runOnMainSync { focused = activity.hasWindowFocus() }
                check(focused) { "Screenshot requires the owned window" }
                val bitmap = checkNotNull(uiAutomation.takeScreenshot()) { "No owned-window screenshot" }
                File(targetContext.cacheDir, "touch-$name.png").outputStream().use {
                    check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
                bitmap.recycle()
                record.append("SNAPSHOT $name at ${SystemClock.uptimeMillis()}\n")
            }
            for (i in 0 until steps.length()) {
                val step = steps.getJSONObject(i)
                SystemClock.sleep(step.optLong("wait", 0).also { check(it in 0..5000) })
                val actionName = step.getString("action")
                if (actionName == "snapshot") {
                    val held = step.getInt("held")
                    val by = SystemClock.elapsedRealtime() + 20_000
                    while (SystemClock.elapsedRealtime() < by &&
                        held !in heldControls(log.readText().substring(injectionOffset))) SystemClock.sleep(20)
                    check(held in heldControls(log.readText().substring(injectionOffset)))
                    snapshot(step.getString("name"))
                    continue
                }
                if (actionName == "inventory") {
                    check(menu == "importer")
                    val by = SystemClock.elapsedRealtime() + 20_000
                    while (SystemClock.elapsedRealtime() < by &&
                        !log.readText().substring(injectionOffset).contains("InputOverlay: importer cancellation boundary"))
                        SystemClock.sleep(5)
                    val observed = log.readText().substring(injectionOffset)
                    check(observed.contains("InputOverlay: importer cancellation boundary")) {
                        "Real importer did not reach its first blocking render: $observed"
                    }
                    check(heldControls(observed).isEmpty()) { "Importer retained accepted holds" }
                    snapshot("importer-cancelled")
                    record.append("INVENTORY: cancellation boundary observed; physical pointers remain down\n")
                    continue
                }
                if (actionName == "background") {
                    targetContext.startActivity(Intent(android.provider.Settings.ACTION_SETTINGS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    val until = SystemClock.elapsedRealtime() + 5000
                    var lostFocus = false
                    while (SystemClock.elapsedRealtime() < until) {
                        var focused = true
                        runOnMainSync { focused = activity.hasWindowFocus() }
                        if (!focused) { lostFocus = true; break }
                        SystemClock.sleep(10)
                    }
                    check(lostFocus) { "Settings did not take focus" }
                    record.append("LIFECYCLE: focus loss cancels consumer holds; ${active.size} physical pointers still down\n")
                    // Focus loss cancels the consumer, but InputDispatcher may
                    // retain the physical stream. Lift it in our window after
                    // returning before beginning any new DOWN.
                    cancelledFingers += active.map { it.id }
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
                        ready = ready && resumed.get() &&
                            log.readText().split("InputOverlay: restored (resume)").size > before
                        if (!ready) SystemClock.sleep(5)
                    }
                    check(ready) { "No explicit native foreground signal" }
                    traceAndroidDelivery() // SDL reinstalls its listener on resume.
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
                val ending = when (actionName) {
                    "up", "pointer-up" -> listOf(changed)
                    "cancel" -> pointers.map { it.id }
                    else -> emptyList()
                }
                for (id in ending) if (!cancelledFingers.remove(id))
                    expectedUps[id] = (expectedUps[id] ?: 0) + 1
                record.append("INJECT $i $actionName changed=$changed ${pointers.joinToString()}\n")
                active = when (actionName) {
                    "up", "cancel" -> emptyList()
                    "pointer-up" -> pointers.filter { it.id != changed }
                    else -> pointers
                }
            }
            check(active.isEmpty()) { "Incomplete injection stream" }
            // sendPointerSync waits for Android dispatch, not SDL's native poll or
            // a software-rendered frame. Observe native completion before teardown.
            val completedBy = SystemClock.elapsedRealtime() + 20_000
            var observed = ""
            var complete = false
            while (!complete && SystemClock.elapsedRealtime() < completedBy) {
                val current = log.readText()
                check(current.length >= injectionOffset) { "Native log epoch replaced during injection" }
                observed = current.substring(injectionOffset)
                val ups = Regex("InputOverlay: event type=up finger=(\\d+) ").findAll(observed)
                    .groupingBy { it.groupValues[1].toInt() }.eachCount()
                complete = expectedUps.all { (id, count) -> (ups[id] ?: 0) >= count } &&
                    heldControls(observed).isEmpty()
                if (!complete) SystemClock.sleep(20)
            }
            check(complete) { "Native pointer stream did not drain: expected $expectedUps UPs\n${observed.takeLast(8000)}" }
            if (menu == "sound") {
                val offset = log.readText().length
                sendKeyDownUpSync(KeyEvent.KEYCODE_DEL) // Save through GuiSettings.
                val by = SystemClock.elapsedRealtime() + 20_000
                while (SystemClock.elapsedRealtime() < by &&
                    !Regex("Window::logInput\\(Keyboard\\): .*value=0").containsMatchIn(log.readText().substring(offset)))
                    SystemClock.sleep(20)
                check(Regex("Window::logInput\\(Keyboard\\): .*value=0").containsMatchIn(log.readText().substring(offset)))
            }
            snapshot("last")
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
        } finally {
            (targetContext.applicationContext as Application).unregisterActivityLifecycleCallbacks(lifecycle)
        }
    }

    private data class Pointer(val id: Int, val x: Float, val y: Float)

    private fun send(surface: SDLSurface, pointers: List<Pointer>, action: Int, downTime: Long) {
        val origin = IntArray(2)
        var width = 0
        var height = 0
        var viewWidth = 0
        var viewHeight = 0
        var focused = false
        runOnMainSync {
            surface.getLocationOnScreen(origin)
            // Match the public SDLSurface.onTouch normalization (surfaceChanged
            // buffer dimensions), independently of a clipped View's bounds.
            width = surface.holder.surfaceFrame.width()
            height = surface.holder.surfaceFrame.height()
            viewWidth = surface.width
            viewHeight = surface.height
            focused = surface.hasWindowFocus()
        }
        check(focused && width > 0 && height > 0) { "No owned focused SDL surface" }
        check(pointers.all { it.x * width < viewWidth && it.y * height < viewHeight }) {
            "Pointer target lies beyond the owned View"
        }
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
