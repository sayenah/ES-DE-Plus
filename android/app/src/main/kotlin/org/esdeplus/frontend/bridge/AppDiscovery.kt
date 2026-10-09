// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using public PackageManager and drawable APIs.
package org.esdeplus.frontend.bridge

import android.app.UiModeManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.Drawable
import android.util.Log
import java.io.File
import java.security.MessageDigest

class AppDiscovery(private val context: Context) {
    private val pm = context.packageManager

    @Suppress("DEPRECATION")
    fun target(packageName: String, activityName: String): Intent {
        require(packageName.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+")))
        val intent = if (activityName.isNotEmpty()) {
            val name = if (activityName.startsWith('.')) packageName + activityName else activityName
            require(name.matches(Regex("[A-Za-z_][A-Za-z0-9_.$]*")))
            Intent(Intent.ACTION_MAIN).setComponent(ComponentName(packageName, name))
        } else {
            val tv = context.getSystemService(UiModeManager::class.java).currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
            (if (tv) pm.getLeanbackLaunchIntentForPackage(packageName) ?: pm.getLaunchIntentForPackage(packageName)
             else pm.getLaunchIntentForPackage(packageName) ?: pm.getLeanbackLaunchIntentForPackage(packageName))
                ?: error("No launchable activity in $packageName")
        }
        val component = intent.component ?: error("Package launch intent has no component")
        require(component.packageName == packageName)
        validate(pm.getActivityInfo(component, 0))
        return intent.setPackage(packageName)
    }

    private fun validate(info: ActivityInfo) {
        val component = ComponentName(info.packageName, info.name)
        fun enabled(setting: Int, manifest: Boolean) = setting == PackageManager.COMPONENT_ENABLED_STATE_ENABLED ||
            (setting == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && manifest)
        require(enabled(pm.getApplicationEnabledSetting(info.packageName), info.applicationInfo.enabled) &&
            enabled(pm.getComponentEnabledSetting(component), info.enabled) && info.exported)
        require(info.permission.isNullOrEmpty() || context.checkSelfPermission(info.permission) == PackageManager.PERMISSION_GRANTED)
    }

    fun installed(packageName: String, activityName: String): Boolean = try {
        target(packageName, activityName); true
    } catch (error: Exception) { false }

    @Suppress("DEPRECATION")
    fun inventory(gamesOnly: Boolean, includeMedia: Boolean): Array<String> {
        val entries = sortedMapOf<String, ActivityInfo>()
        for (category in listOf(Intent.CATEGORY_LAUNCHER, Intent.CATEGORY_LEANBACK_LAUNCHER)) {
            for (resolved in pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(category), 0)) {
                val info = resolved.activityInfo ?: continue
                if (info.packageName == context.packageName) continue
                try {
                    validate(info)
                    val game = info.applicationInfo.category == ApplicationInfo.CATEGORY_GAME ||
                        info.applicationInfo.flags and ApplicationInfo.FLAG_IS_GAME != 0
                    if (!gamesOnly || game) entries[ComponentName(info.packageName, info.name).flattenToString()] = info
                } catch (error: Exception) { Log.w("ES-DE-Plus", "Ignoring unavailable app ${info.packageName}", error) }
            }
        }
        val temp = File(StorageModel(context).appData(), "importer_temp")
        val result = mutableListOf<String>()
        for ((component, info) in entries) {
            try {
                val name = filename(info.loadLabel(pm).toString(), component)
                // Artwork is optional; a bad drawable never removes an otherwise launchable app.
                try { png(info.loadIcon(pm), File(temp, "icons/$name.png")) }
                catch (error: Exception) {
                    Log.w("ES-DE-Plus", "Cannot load app icon, using platform default: $component", error)
                    png(pm.defaultActivityIcon, File(temp, "icons/$name.png"))
                }
                if (includeMedia) {
                    try {
                        val artwork = info.loadBanner(pm) ?: info.loadLogo(pm)
                        if (artwork != null) png(artwork, File(temp, "media/$name.png"))
                    } catch (error: Exception) { Log.w("ES-DE-Plus", "Cannot stage app artwork: $component", error) }
                }
                result.add(name); result.add(component)
            } catch (error: Exception) { Log.w("ES-DE-Plus", "Cannot inventory app: $component", error) }
        }
        return result.toTypedArray()
    }

    companion object {
        fun filename(label: String, component: String): String {
            val clean = label.replace(Regex("[\\p{Cc}\\p{Cf}/\\\\:*?\"<>|]"), "_").trim(' ', '.').ifEmpty { "App" }
            val stem = StringBuilder()
            var bytes = 0
            for (point in clean.codePoints().toArray()) {
                val character = String(Character.toChars(point))
                val size = character.toByteArray(Charsets.UTF_8).size
                if (bytes + size > 160) break
                stem.append(character)
                bytes += size
            }
            val hash = MessageDigest.getInstance("SHA-256").digest(component.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
            return "$stem [$hash]"
        }

        private fun png(drawable: Drawable, file: File) {
            check(file.parentFile!!.mkdirs() || file.parentFile!!.isDirectory)
            val width = drawable.intrinsicWidth.coerceIn(1, 512)
            val height = drawable.intrinsicHeight.coerceIn(1, 512)
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            try {
                drawable.setBounds(0, 0, width, height)
                drawable.draw(Canvas(bitmap))
                file.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
            } finally { bitmap.recycle() }
        }
    }
}
