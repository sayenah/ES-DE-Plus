// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using the Android SDK activity creation hook.
package org.esdeplus.frontend

import android.app.Activity
import android.app.ActivityManager
import android.app.AppComponentFactory
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View

class FrontendActivityFactory : AppComponentFactory() {
    override fun instantiateActivity(loader: ClassLoader, className: String, intent: Intent?): Activity {
        // HOME and standard tasks can each request a new instance despite
        // singleTask. Intercept before SDLActivity.onCreate resets global state.
        if (className == MainActivity::class.java.name && MainActivity.liveInstance() != null)
            return FrontendRedirectActivity()
        return super.instantiateActivity(loader, className, intent)
    }
}

class FrontendRedirectActivity : Activity() {
    private var forwarded = false
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        // Allow Android to attach/focus a real window before removing this
        // HOME task. Finishing in onCreate aborts its window transition and
        // can leave the resumed owner without an input-focused window.
        setContentView(View(this))
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (forwarded) MainActivity.liveInstance()?.receiveEntry(intent)
    }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || forwarded) return
        forwarded = true
        val frontend = MainActivity.liveInstance()
        if (frontend != null) {
            frontend.receiveEntry(intent)
            val task = getSystemService(ActivityManager::class.java).appTasks
                .firstOrNull { it.taskInfo.taskId == frontend.taskId }
            Log.i("ES-DE-Plus", "Focused redirect forwarding entry to sole SDL activity task=${frontend.taskId}")
            if (taskId != frontend.taskId) finishAndRemoveTask() else finish()
            task?.moveToFront()
        } else {
            // The original can finish between creation and this callback.
            startActivity(Intent(intent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            finish()
        }
    }
}
