// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using SDL release-2.32.10 and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Context
import android.view.SurfaceHolder
import org.libsdl.app.SDLSurface

internal class WindowSurface(context: Context, private val refreshWindow: (Int, Int) -> Unit) :
    SDLSurface(context) {
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        // Refresh full window bounds before SDL queues SIZE_CHANGED. The
        // callback dimensions describe the inset surface and are diagnostic only.
        refreshWindow(width, height)
        super.surfaceChanged(holder, format, width, height)
    }
}
