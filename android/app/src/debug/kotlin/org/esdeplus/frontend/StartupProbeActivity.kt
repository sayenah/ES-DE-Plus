// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Debug-only Activity scheduling seam; real JNI results.
package org.esdeplus.frontend

import android.app.Activity
import java.util.function.Consumer

// Instrumentation substitutes this instance for the same MainActivity component.
// Its device-info call follows native window creation and precedes the first
// getCreateSystemDirectories call, even when no resource copy is needed.
class StartupProbeActivity : MainActivity() {
    override fun getDeviceInfo(): String {
        val result = super.getDeviceInfo()
        beforeDeviceInfo?.accept(this)
        return result
    }
    companion object {
        @JvmField var beforeDeviceInfo: Consumer<Activity>? = null
    }
}
