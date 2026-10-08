// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using public Android storage APIs.
package org.esdeplus.frontend.bridge

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.storage.StorageManager
import android.provider.DocumentsContract
import android.system.Os
import android.system.OsConstants
import java.io.File
import java.io.IOException

class StorageModel(private val context: Context) {
    data class Configuration(val mode: String, val roms: String, val tree: String,
                             val createSystems: Boolean)
    private val preferences = context.getSharedPreferences("storage", Context.MODE_PRIVATE)
    private val grants = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION

    fun externalFiles(): File = context.getExternalFilesDir(null)
        ?: throw IOException("App-owned storage is unavailable. Reconnect the storage and retry.")
    fun appData(): File = File(externalFiles(), "ES-DE-Plus")
    fun ownedROMs(): File = File(externalFiles(), "ROMs")

    fun broadAccess(): Boolean = if (Build.VERSION.SDK_INT >= 30) {
        Environment.isExternalStorageManager()
    } else {
        Environment.isExternalStorageLegacy() &&
            context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED &&
            context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }

    // Exercise the same filesystem access the native frontend needs, under the
    // application's UID. A URI grant alone never establishes POSIX access.
    fun verifyDirectory(directory: File, create: Boolean = false): File {
        if (create && !directory.isDirectory && !directory.mkdirs())
            throw IOException("Cannot create $directory. Restore access and retry.")
        val canonical = directory.canonicalFile
        if (!canonical.isDirectory || !Os.access(canonical.path,
                OsConstants.R_OK or OsConstants.W_OK or OsConstants.X_OK) || canonical.list() == null)
            throw IOException("Cannot read and write $directory. Restore access and retry.")
        val probe = File.createTempFile(".esdeplus-access-", ".tmp", canonical)
        try {
            val bytes = byteArrayOf(69, 83, 68, 69)
            probe.outputStream().use { it.write(bytes); it.flush() }
            if (!probe.readBytes().contentEquals(bytes)) throw IOException("Read/write check failed: $directory")
        } finally {
            if (!probe.delete()) throw IOException("Cannot remove access check: $probe")
        }
        return canonical
    }

    // SDK-owned app paths and StorageManager's current-user volume list agree
    // before any mapping is accepted. No /storage/<UUID> or user-0 guesswork.
    private fun volumeRoot(volumeId: String): File {
        val manager = context.getSystemService(StorageManager::class.java)
        val volume = manager.storageVolumes.singleOrNull {
            if (volumeId == "primary") it.isPrimary else it.uuid?.equals(volumeId, true) == true
        } ?: throw IOException("The selected current-user volume is unavailable.")
        if (volume.state != Environment.MEDIA_MOUNTED)
            throw IOException("The selected volume is not mounted for read/write access.")
        val suffix = "/Android/data/${context.packageName}/files"
        val roots = context.getExternalFilesDirs(null).filterNotNull().mapNotNull { owned ->
            val current = manager.getStorageVolume(owned)
            if (current == null || current.isPrimary != volume.isPrimary || current.uuid != volume.uuid) null
            else owned.canonicalPath.takeIf { it.endsWith(suffix) }?.removeSuffix(suffix)?.let(::File)
        }
        val root = roots.singleOrNull()?.canonicalFile
            ?: throw IOException("Cannot verify this volume for the current Android user.")
        if (Build.VERSION.SDK_INT >= 30 && volume.directory?.canonicalFile != root)
            throw IOException("The selected volume mount has changed.")
        return root
    }

    internal fun resolveTree(uri: Uri): File {
        if (uri.scheme != "content" || uri.authority != "com.android.externalstorage.documents" ||
            !DocumentsContract.isTreeUri(uri) || uri.pathSegments.size != 2 ||
            uri.pathSegments.first() != "tree" || uri.query != null || uri.fragment != null)
            throw IOException("Choose a local folder from this device's external-storage provider.")
        val id = DocumentsContract.getTreeDocumentId(uri)
        val parts = id.split(':', limit = 2)
        if (parts.size != 2 || parts[0].isEmpty()) throw IOException("Invalid storage tree.")
        val relative = parts[1]
        val segments = relative.split('/')
        if (relative.isEmpty() || segments.any { it.isEmpty() || it == "." || it == ".." ||
                it.contains('\\') || it.contains('\u0000') })
            throw IOException("Choose a folder inside the volume, not its root.")
        // The application never adopts or opens official application data.
        if (segments.any { it.equals("ES-DE", true) || it.equals(".emulationstation", true) } ||
            segments.first().equals("Android", true))
            throw IOException("Choose a ROM folder outside Android and official ES-DE application data.")
        val root = volumeRoot(parts[0])
        val result = File(root, relative).canonicalFile
        if (!result.path.startsWith(root.path + "/")) throw IOException("Folder escapes the selected volume.")
        val resolved = result.relativeTo(root).invariantSeparatorsPath.split('/')
        if (resolved.first().equals("Android", true) || resolved.any {
                it.equals("ES-DE", true) || it.equals(".emulationstation", true) })
            throw IOException("Choose a ROM folder outside Android and official ES-DE application data.")
        return result
    }

    fun acceptTree(uri: Uri, flags: Int): File {
        if (!broadAccess()) throw IOException("Direct filesystem access has not been granted.")
        if ((flags and grants) != grants || flags and Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION == 0)
            throw IOException("The picker did not grant persistent read/write access.")
        val directory = verifyDirectory(resolveTree(uri))
        context.contentResolver.takePersistableUriPermission(uri, flags and grants)
        verifyGrant(uri)
        return directory
    }

    private fun verifyGrant(uri: Uri) {
        if (context.contentResolver.persistedUriPermissions.none {
                it.uri == uri && it.isReadPermission && it.isWritePermission })
            throw IOException("Folder access was revoked. Choose the folder again.")
    }

    // Missing picker fallback is an explicitly typed path, still resolved through
    // the same current-user volume list and access checks. Never invent a URI grant.
    fun acceptPath(path: String): File {
        if (!broadAccess()) throw IOException("Direct filesystem access has not been granted.")
        if (!path.startsWith('/') || path.contains('\u0000')) throw IOException("Enter an absolute folder path.")
        val manager = context.getSystemService(StorageManager::class.java)
        val candidate = File(path).canonicalFile
        val volume = manager.getStorageVolume(candidate) ?: throw IOException("Unknown storage volume.")
        val root = volumeRoot(if (volume.isPrimary) "primary" else volume.uuid
            ?: throw IOException("Unknown storage volume identifier."))
        if (!candidate.path.startsWith(root.path + "/")) throw IOException("Choose a folder inside the volume.")
        val relative = candidate.relativeTo(root).invariantSeparatorsPath
        val uri = DocumentsContract.buildTreeDocumentUri("com.android.externalstorage.documents",
            "${if (volume.isPrimary) "primary" else volume.uuid}:$relative")
        if (resolveTree(uri) != candidate) throw IOException("Folder mapping changed.")
        return verifyDirectory(candidate)
    }

    fun load(): Configuration? {
        if (!preferences.contains("mode")) return null
        return Configuration(preferences.getString("mode", "")!!,
            preferences.getString("roms", "")!!, preferences.getString("tree", "")!!,
            preferences.getBoolean("createSystems", true))
    }

    fun validate(configuration: Configuration): File {
        verifyDirectory(appData(), true)
        val roms = when (configuration.mode) {
            "scoped" -> {
                if (configuration.roms != ownedROMs().canonicalPath || configuration.tree.isNotEmpty())
                    throw IOException("App-owned storage location changed. Review the configuration.")
                verifyDirectory(ownedROMs(), true)
            }
            "direct" -> {
                if (configuration.tree.isEmpty()) acceptPath(configuration.roms)
                else {
                    if (!broadAccess()) throw IOException("Direct filesystem access was revoked.")
                    val uri = Uri.parse(configuration.tree)
                    verifyGrant(uri)
                    val mapped = resolveTree(uri)
                    if (mapped.path != configuration.roms) throw IOException("The selected volume or folder changed.")
                    verifyDirectory(mapped)
                }
            }
            else -> throw IOException("Choose a storage mode.")
        }
        return roms
    }

    fun problem(): String? = try {
        val config = load() ?: throw IOException("Choose how to store games before continuing.")
        validate(config)
        null
    } catch (error: Exception) { error.message ?: "Storage validation failed. Retry." }

    fun save(configuration: Configuration) {
        validate(configuration)
        if (!preferences.edit().putString("mode", configuration.mode)
                .putString("roms", configuration.roms).putString("tree", configuration.tree)
                .putBoolean("createSystems", configuration.createSystems).commit())
            throw IOException("Could not save configuration. Retry.")
    }
}
