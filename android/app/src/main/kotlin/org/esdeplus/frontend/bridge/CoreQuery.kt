// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using Android broadcasts and the public RetroArch wire contract.
// RetroArch source was consulted only for action names, CORES type and core-name suffix semantics.
package org.esdeplus.frontend.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.ReentrantLock

class CoreQuery(private val context: Context) {
    fun query(packageName: String, coreFile: String): Int {
        val started = SystemClock.elapsedRealtimeNanos()
        val deadline = started + TimeUnit.MILLISECONDS.toNanos(900)
        if (!packageName.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+")) ||
            !coreFile.matches(Regex("[A-Za-z0-9_+-]+_libretro_android\\.so"))) return -2
        var locked = false
        var registered = false
        var thread: HandlerThread? = null
        val result = AtomicInteger(-1)
        val uncertainAbsence = java.util.concurrent.atomic.AtomicBoolean(false)
        val delivered = CountDownLatch(1)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(receiving: Context, intent: Intent) {
                if (SystemClock.elapsedRealtimeNanos() >= deadline) return
                val value = try {
                    reply(intent, coreFile, if (Build.VERSION.SDK_INT >= 34) sentFromPackage else null,
                        packageName, Build.VERSION.SDK_INT >= 34)
                } catch (error: Exception) { -2 }
                if (SystemClock.elapsedRealtimeNanos() >= deadline) return
                // The public reply has no request identifier. After a failed
                // query, a later empty list might belong to that old request;
                // never let it veto a different game launch in this process.
                val safe = if (value == 0 && uncertainAbsence.get()) -2 else value
                if (result.compareAndSet(-1, safe)) delivered.countDown()
            }
        }
        try {
            locked = lock.tryLock((deadline - SystemClock.elapsedRealtimeNanos()).coerceAtLeast(0), TimeUnit.NANOSECONDS)
            if (!locked) { result.set(-2); return -2 }
            uncertainAbsence.set(packageName in uncertainPackages)
            @Suppress("DEPRECATION")
            val info = context.packageManager.getApplicationInfo(packageName, 0)
            if (!info.enabled) { result.set(-2); return -2 }
            thread = HandlerThread("ESDEPlus-core-replies").apply { start() }
            val handler = Handler(thread.looper)
            val filter = IntentFilter(RESULT)
            if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(receiver, filter, null, handler, Context.RECEIVER_EXPORTED)
            else {
                @Suppress("DEPRECATION")
                context.registerReceiver(receiver, filter, null, handler)
            }
            registered = true
            Log.i("ES-DE-Plus", "Core query registered before dispatch: $packageName")
            if (SystemClock.elapsedRealtimeNanos() >= deadline) return -1
            context.sendBroadcast(Intent(QUERY).setPackage(packageName).addFlags(Intent.FLAG_INCLUDE_STOPPED_PACKAGES))
            delivered.await((deadline - SystemClock.elapsedRealtimeNanos()).coerceAtLeast(0), TimeUnit.NANOSECONDS)
            return result.get()
        } catch (error: InterruptedException) {
            Thread.currentThread().interrupt()
            result.set(-2)
            return -2
        } catch (error: Exception) {
            Log.w("ES-DE-Plus", "Optional core query unavailable: $packageName", error)
            result.set(-2)
            return -2
        } finally {
            try { if (registered) context.unregisterReceiver(receiver) }
            finally {
                thread?.quit()
                if (locked && result.get() < 0) uncertainPackages.add(packageName)
                if (locked) lock.unlock()
                Log.i("ES-DE-Plus", "Core query cleanup: $packageName result=${result.get()} elapsedMs=${TimeUnit.NANOSECONDS.toMillis(SystemClock.elapsedRealtimeNanos() - started)}")
            }
        }
    }

    companion object {
        const val QUERY = "com.retroarch.QUERY_INSTALLED_CORES"
        const val RESULT = "com.retroarch.INSTALLED_CORES_RESULT"
        private val lock = ReentrantLock()
        // Accessed only by the serialized waiter while it owns lock.
        private val uncertainPackages = mutableSetOf<String>()
        fun reply(intent: Intent, coreFile: String, sender: String?, expected: String, requireSender: Boolean): Int {
            if (intent.action != RESULT || (requireSender && sender != expected)) return -2
            val cores = intent.getStringArrayExtra("CORES") ?: return -2
            if (cores.size > 4096 || cores.any { it == null || it.length !in 1..128 ||
                    !it.matches(Regex("[A-Za-z0-9_+-]+")) } || cores.sumOf { it.length } > 65536) return -2
            val name = coreFile.removeSuffix("_libretro_android.so")
            return if (name in cores) 1 else 0
        }
    }
}
