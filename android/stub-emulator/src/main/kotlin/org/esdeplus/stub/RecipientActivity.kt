// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Unprivileged platform-only CI recipient.
package org.esdeplus.stub

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Process
import android.util.Log
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

open class RecipientActivity : Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        observe(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        observe(intent)
    }

    private fun observe(intent: Intent) {
        val control = intent.getStringExtra("queryMode")
        if (control != null) {
            check(getSharedPreferences("query", MODE_PRIVATE).edit().putString("mode", control).commit())
            val result = JSONObject().put("queryMode", control).put("uid", Process.myUid())
            if (control == "phone-off" || control == "restore-launchers") {
                val state = if (control == "phone-off") android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                    else android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DEFAULT
                for (name in listOf("RecipientActivity", "CollisionOne", "CollisionTwo"))
                    packageManager.setComponentEnabledSetting(android.content.ComponentName(packageName, "$packageName.$name"),
                        state, android.content.pm.PackageManager.DONT_KILL_APP)
                val states = JSONObject()
                for (name in listOf("RecipientActivity", "CollisionOne", "CollisionTwo"))
                    states.put(name, packageManager.getComponentEnabledSetting(android.content.ComponentName(packageName, "$packageName.$name")))
                result.put("componentStates", states)
            }
            File(filesDir, "control.json").writeText(result.toString())
            Log.i("ESDEPlus-recipient", "Query mode configured=$control $result")
            if (control == "storage-permission" && android.os.Build.VERSION.SDK_INT >= 30) {
                startActivity(Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:$packageName")))
            }
            intent.getStringExtra("replyPackage")?.let {
                sendBroadcast(Intent("org.esdeplus.stub.OBSERVATION").setPackage(it)
                    .putExtra("json", result.toString()))
            }
            finish(); return
        }
        val observation = JSONObject().put("uid", Process.myUid()).put("component", intent.component?.flattenToString())
            .put("action", intent.action).put("mime", intent.type).put("data", intent.dataString)
            .put("flags", intent.flags).put("categories", JSONArray(intent.categories?.sorted().orEmpty()))
        val extras = JSONObject()
        intent.extras?.keySet()?.sorted()?.forEach { name ->
            @Suppress("DEPRECATION") val value = intent.extras?.get(name)
            extras.put(name, JSONObject().put("type", value?.javaClass?.name)
                .put("value", if (value is Array<*>) JSONArray(value.toList()) else value))
        }
        observation.put("extras", extras)
        val value = intent.dataString ?: intent.getStringExtra("ROM") ?: intent.getStringExtra("bootPath")
        if (value != null) {
            try {
                val uri = Uri.parse(value)
                val bytes = if (uri.scheme == "content") contentResolver.openInputStream(uri)!!.use { it.readBytes() }
                    else File(value).readBytes()
                observation.put("sha256", MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) })
                if (uri.authority?.endsWith(".roms") == true) {
                    observation.put("uriLastSegment", uri.lastPathSegment)
                    observation.put("mimeFromProvider", contentResolver.getType(uri))
                    contentResolver.query(uri, null, null, null, null)!!.use { cursor ->
                        check(cursor.moveToFirst())
                        observation.put("displayName", cursor.getString(cursor.getColumnIndexOrThrow("_display_name")))
                        observation.put("size", cursor.getLong(cursor.getColumnIndexOrThrow("_size")))
                    }
                    contentResolver.query(uri, arrayOf("_size", "document_id", "_display_name"), null, null, null)!!.use { cursor ->
                        check(cursor.moveToFirst())
                        observation.put("projectionColumns", JSONArray(cursor.columnNames.toList()))
                        observation.put("projectedName", cursor.getString(cursor.getColumnIndexOrThrow("_display_name")))
                        observation.put("projectedSize", cursor.getLong(cursor.getColumnIndexOrThrow("_size")))
                    }
                    fun denied(name: String, action: () -> Unit) {
                        try { action(); observation.put(name, false) }
                        catch (error: Exception) { observation.put(name, true) }
                    }
                    denied("writeDenied") { contentResolver.openFileDescriptor(uri, "rw")!!.close() }
                    denied("deleteDenied") { contentResolver.delete(uri, null, null) }
                    denied("insertDenied") { contentResolver.insert(uri, ContentValues()) }
                    denied("updateDenied") { contentResolver.update(uri, ContentValues(), null, null) }
                    intent.getStringArrayExtra("deniedUris")?.forEachIndexed { i, candidate ->
                        denied("boundary$i") { contentResolver.openInputStream(Uri.parse(candidate))!!.close() }
                    }
                }
            } catch (error: Exception) { observation.put("readError", error.javaClass.name + ": " + error.message) }
        }
        File(filesDir, "observation.json").writeText(observation.toString())
        Log.i("ESDEPlus-recipient", observation.toString())
        intent.getStringExtra("replyPackage")?.let { recipient ->
            sendBroadcast(Intent("org.esdeplus.stub.OBSERVATION").setPackage(recipient).putExtra("json", observation.toString()))
        }
        setContentView(TextView(this).apply { text = "ES-DE Plus recipient\n$observation" })
    }
}
class PrivateActivity : RecipientActivity()
class ProtectedActivity : RecipientActivity()
class DisabledActivity : RecipientActivity()
