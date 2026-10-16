// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Debug-only scheduling of SDL's real native-return race.
package org.esdeplus.frontend

import android.os.Looper
import android.util.Log

class ForcedRelaunchActivity : MainActivity() {
    private var widened = false
    override fun isFinishing(): Boolean {
        val snapshot = super.isFinishing()
        if (!widened && !snapshot && MainActivity.destructionRequested() &&
            Thread.currentThread() == Looper.getMainLooper().thread) {
            widened = true
            // On the unfixed host, cancellation is already live when its log
            // reads isFinishing. Let SDL finish naturally before that read
            // returns, preserving the value it actually read. The fixed host
            // snapshots/decides before cancellation, so never enters this seam.
            val deadline = System.nanoTime() + 5_000_000_000L
            while (!super.isFinishing()) {
                check(System.nanoTime() < deadline) { "SDL did not finish after copy cancellation" }
                Thread.sleep(1)
            }
            Log.i("ES-DE-Plus-Probe", "ASSETS actual SDL finish followed the destruction snapshot")
        }
        return snapshot
    }
}
