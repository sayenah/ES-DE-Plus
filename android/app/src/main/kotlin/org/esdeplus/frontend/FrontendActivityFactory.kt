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
        // Ordinary forwarding must focus a real window before removing this
        // HOME task; moving an existing task cannot finish an aborted window
        // transition. A clear-task entry supplies a new helper window instead.
        setContentView(View(this))
        val frontend = MainActivity.liveInstance()
        if (frontend != null && intent.flags and Intent.FLAG_ACTIVITY_CLEAR_TASK != 0 &&
            intent.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0) {
            // A clear-task entry needs a new foreground owner, even if Android
            // destroys the old SDL host before this redirect gains focus.
            // The helper has its own window/VM; it never moves the clearing
            // task forward or starts native main before the old process retires.
            forwarded = true
            frontend.retireForEntry(intent)
            finish()
        }
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
            // Clear the orphan task so singleTask cannot deliver the launch
            // back to this redirect's ActivityRecord. Preserve the entry alias.
            val entry = Intent(intent).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            finish()
            startActivity(entry)
        }
    }
}
