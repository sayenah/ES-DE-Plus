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
                    else "com.retroarch.INSTALLED_CORES_RESULT").addFlags(Intent.FLAG_RECEIVER_FOREGROUND)
                when (mode) {
                    "malformed", "anonymous-malformed" -> response.putExtra("CORES", "wrong type")
                    "oversized" -> response.putExtra("CORES", Array(4097) { "a_libretro.so" })
                    "absent", "anonymous-absent", "late" -> response.putExtra("CORES", arrayOf("other_libretro_android.so"))
                    else -> response.putExtra("CORES", arrayOf("test_libretro_android.so", "snes9x_libretro.so"))
                }
                android.util.Log.i("ESDEPlus-recipient", "Core broadcast mode=$mode count=${response.getStringArrayExtra("CORES")?.size}")
                if (Build.VERSION.SDK_INT >= 34 && mode?.startsWith("anonymous") != true)
                    context.sendBroadcast(response, null, BroadcastOptions.makeBasic().setShareIdentityEnabled(true).toBundle())
                else context.sendBroadcast(response)
            } finally { pending.finish() }
        }, if (mode == "late") 1200 else 0)
    }
}
