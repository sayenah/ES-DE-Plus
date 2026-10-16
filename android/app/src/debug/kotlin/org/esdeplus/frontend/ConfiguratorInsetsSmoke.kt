// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using Android SDK layout instrumentation.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.app.UiAutomation
import android.content.Intent
import android.graphics.Rect
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.Button
import android.widget.ScrollView

object ConfiguratorInsetsSmoke {
    private fun contains(safe: Rect, control: Rect) = !control.isEmpty && safe.contains(control)

    fun run(test: Instrumentation, rotation: Int): String {
        check(rotation in 0..1)
        check(contains(Rect(10, 20, 90, 80), Rect(10, 20, 90, 80)))
        check(!contains(Rect(10, 20, 90, 80), Rect(9, 20, 90, 80)))
        check(!contains(Rect(10, 20, 90, 80), Rect(10, 20, 90, 81)))
        // A Settings write did not rotate the API36 guest. Use the SDK's
        // rotation operation and require the real display/configuration below.
        // This probe owns its automation; the host never dumps accessibility.
        val automation = test.getUiAutomation(UiAutomation.FLAG_DONT_USE_ACCESSIBILITY)
        check(automation.setRotation(rotation))
        try {
            val activity = test.startActivitySync(Intent(test.targetContext, ConfiguratorActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as ConfiguratorActivity
            val evidence = StringBuilder("PASS: inset oracle rejects bar overlap positive controls\n")
            fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
                (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
            fun stage(name: String) {
                test.waitForIdleSync()
                val scroll = views(activity.window.decorView).filterIsInstance<ScrollView>().single()
                for (edge in listOf(View.FOCUS_UP, View.FOCUS_DOWN)) {
                    test.runOnMainSync { scroll.fullScroll(edge) }
                    // Wait for layout, not an arbitrary animation delay. Keep the
                    // assertion on real geometry; no inset or bounds substitutions.
                    val deadline = SystemClock.uptimeMillis() + 10_000
                    var ready = false
                    var record = ""
                    while (!ready && SystemClock.uptimeMillis() < deadline) {
                        test.runOnMainSync {
                            val decor = activity.window.decorView
                            val insets = decor.rootWindowInsets
                            if (insets != null && scroll.isLaidOut && !scroll.isLayoutRequested) {
                                val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                                val origin = IntArray(2).also { decor.getLocationOnScreen(it) }
                                val bounds = Rect(origin[0] + safe.left, origin[1] + safe.top,
                                    origin[0] + decor.width - safe.right, origin[1] + decor.height - safe.bottom)
                                val controls = views(scroll).filterIsInstance<Button>()
                                val control = if (edge == View.FOCUS_UP) controls.first() else controls.last()
                                val location = IntArray(2).also { control.getLocationOnScreen(it) }
                                val actual = Rect(location[0], location[1], location[0] + control.width, location[1] + control.height)
                                record = "$name edge=$edge orientation=${activity.resources.configuration.orientation} " +
                                    "rotation=${activity.display?.rotation} expectedRotation=$rotation density=${activity.resources.displayMetrics.density} insets=$safe cutout=${insets.displayCutout} " +
                                    "safe=$bounds control=${control.text} bounds=$actual scrollY=${scroll.scrollY}"
                                ready = contains(bounds, actual) && activity.display?.rotation == rotation &&
                                    activity.resources.configuration.orientation == (if (rotation == 0) 1 else 2)
                            }
                        }
                        if (!ready) SystemClock.sleep(50)
                    }
                    check(ready) { "Configurator control overlaps system bars/cutout: $record" }
                    evidence.appendLine("PASS: $record")
                }
            }
            stage("permission")
            test.runOnMainSync { activity.findViewById<Button>(R.string.direct_mode).performClick() }
            stage("data")
            test.runOnMainSync { activity.findViewById<Button>(R.string.scoped_mode).performClick() }
            stage("scoped-roms")
            return evidence.toString()
        } finally { check(automation.setRotation(UiAutomation.ROTATION_UNFREEZE)) }
    }
}
