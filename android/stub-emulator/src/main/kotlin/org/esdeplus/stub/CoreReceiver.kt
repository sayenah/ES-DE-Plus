// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Public broadcast contract simulated independently;
// no RetroArch implementation code is incorporated.
package org.esdeplus.stub

import android.app.BroadcastOptions
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper

class CoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "com.retroarch.QUERY_INSTALLED_CORES") return
        val mode = context.getSharedPreferences("query", Context.MODE_PRIVATE).getString("mode", "valid")
        if (mode == "none") return
        val pending = goAsync()
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                val response = Intent(if (mode == "unrelated") "org.esdeplus.stub.UNRELATED"
                    else "com.retroarch.INSTALLED_CORES_RESULT")
                when (mode) {
                    "malformed" -> response.putExtra("CORES", "wrong type")
                    "oversized" -> response.putExtra("CORES", Array(4097) { "test" })
                    "absent" -> response.putExtra("CORES", arrayOf("other"))
                    else -> response.putExtra("CORES", arrayOf("test"))
                }
                if (Build.VERSION.SDK_INT >= 34 && mode != "anonymous")
                    context.sendBroadcast(response, null, BroadcastOptions.makeBasic().setShareIdentityEnabled(true).toBundle())
                else context.sendBroadcast(response)
            } finally { pending.finish() }
        }, if (mode == "late") 1200 else 0)
    }
}
