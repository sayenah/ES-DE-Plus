// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using SDL release-2.32.10 and Android SDK APIs.
package org.esdeplus.frontend

import android.content.Context
import android.view.SurfaceHolder
import org.libsdl.app.SDLSurface

internal class WindowSurface(context: Context, private val publishSize: (Int, Int) -> Unit) :
    SDLSurface(context) {
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        // Publish before SDL queues SIZE_CHANGED: the native consumer reads
        // the volatile snapshot over JNI instead of using the event dimensions.
        publishSize(width, height)
        super.surfaceChanged(holder, format, width, height)
    }
}
