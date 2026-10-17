// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Shell-only, back-opted-in CI game.
package org.esdeplus.stub

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

class PredictiveBackActivity : Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        // Keep the platform's default Back callback: a custom callback would
        // consume Back instead of previewing the previous task/HOME.
        setContentView(TextView(this).apply { text = "Predictive Back game: cancel keeps this game in front" })
    }
}
