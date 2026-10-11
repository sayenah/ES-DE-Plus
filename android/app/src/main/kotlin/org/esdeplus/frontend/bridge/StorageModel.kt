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
import android.util.Log
import org.esdeplus.frontend.R
import java.io.File
import java.io.IOException

class StorageModel(private val context: Context) {
    data class Configuration(val mode: String, val roms: String, val tree: String,
                             val createSystems: Boolean)
    private val preferences = context.getSharedPreferences("storage", Context.MODE_PRIVATE)
    private val grants = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION

    private fun failure(id: Int, vararg values: Any) = IOException(context.getString(id, *values))

    fun externalFiles(): File = context.getExternalFilesDir(null)
        ?: throw failure(R.string.owned_storage_unavailable)
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
    fun verifyDirectory(directory: File, create: Boolean = false, readOnly: Boolean = false): File {
        if (create && !directory.isDirectory && !directory.mkdirs())
            throw failure(R.string.directory_create_failed, directory)
        val canonical = directory.canonicalFile
        val access = OsConstants.R_OK or OsConstants.X_OK or (if (readOnly) 0 else OsConstants.W_OK)
        if (!canonical.isDirectory || !Os.access(canonical.path, access) || canonical.list() == null)
            throw failure(R.string.directory_access_failed, directory)
        if (readOnly) return canonical
        val probe = File.createTempFile(".esdeplus-access-", ".tmp", canonical)
        try {
            val bytes = byteArrayOf(69, 83, 68, 69)
            probe.outputStream().use { it.write(bytes); it.flush() }
            if (!probe.readBytes().contentEquals(bytes)) throw failure(R.string.directory_probe_failed, directory)
        } finally {
            if (!probe.delete()) throw failure(R.string.directory_probe_remove_failed, probe)
        }
        return canonical
    }

    // SDK-owned app paths and StorageManager's current-user volume list agree
    // before any mapping is accepted. No /storage/<UUID> or user-0 guesswork.
    internal fun volumeRoot(volumeId: String, readOnly: Boolean = false): File {
        val manager = context.getSystemService(StorageManager::class.java)
        val volume = manager.storageVolumes.singleOrNull {
            if (volumeId == "primary") it.isPrimary else it.uuid?.equals(volumeId, true) == true
        } ?: throw failure(R.string.volume_unavailable)
        if (volume.state != Environment.MEDIA_MOUNTED && !(readOnly && volume.state == Environment.MEDIA_MOUNTED_READ_ONLY))
            throw failure(R.string.volume_not_mounted)
        val suffix = "/Android/data/${context.packageName}/files"
        val roots = context.getExternalFilesDirs(null).filterNotNull().mapNotNull { owned ->
            val current = manager.getStorageVolume(owned)
            if (current == null || current.isPrimary != volume.isPrimary || current.uuid != volume.uuid) null
            else owned.canonicalPath.takeIf { it.endsWith(suffix) }?.removeSuffix(suffix)?.let(::File)
        }
        val root = roots.singleOrNull()?.canonicalFile
            ?: throw failure(R.string.volume_user_unverified)
        if (Build.VERSION.SDK_INT >= 30 && volume.directory?.canonicalFile != root)
            throw failure(R.string.volume_mount_changed)
        return root
    }

    internal fun resolveTree(uri: Uri, readOnly: Boolean = false): File {
        if (uri.scheme != "content" || uri.authority != "com.android.externalstorage.documents" ||
            !DocumentsContract.isTreeUri(uri) || uri.pathSegments.size != 2 ||
            uri.pathSegments.first() != "tree" || uri.query != null || uri.fragment != null)
            throw failure(R.string.local_provider_required)
        val id = DocumentsContract.getTreeDocumentId(uri)
        val parts = id.split(':', limit = 2)
        if (parts.size != 2 || parts[0].isEmpty()) throw failure(R.string.invalid_tree)
        val relative = parts[1]
        val segments = relative.split('/')
        if (relative.isEmpty() || segments.any { it.isEmpty() || it == "." || it == ".." ||
                it.contains('\\') || it.contains('\u0000') })
            throw failure(R.string.tree_root_refused)
        // The application never adopts or opens official application data.
        if (segments.any { it.equals("ES-DE", true) || it.equals(".emulationstation", true) } ||
            segments.first().equals("Android", true))
            throw failure(R.string.official_data_refused)
        val root = volumeRoot(parts[0], readOnly)
        val result = File(root, relative).canonicalFile
        if (!result.path.startsWith(root.path + "/")) throw failure(R.string.tree_escape_refused)
        val resolved = result.relativeTo(root).invariantSeparatorsPath.split('/')
        if (resolved.first().equals("Android", true) || resolved.any {
                it.equals("ES-DE", true) || it.equals(".emulationstation", true) })
            throw failure(R.string.official_data_refused)
        return result
    }

    fun acceptTree(uri: Uri, flags: Int): File {
        if (!broadAccess()) throw failure(R.string.direct_not_granted)
        if ((flags and grants) != grants || flags and Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION == 0)
            throw failure(R.string.persistent_access_required)
        val directory = verifyDirectory(resolveTree(uri))
        try {
            context.contentResolver.takePersistableUriPermission(uri, flags and grants)
            verifyGrant(uri)
        } catch (error: Exception) {
            releaseUnselectedGrants()
            throw error
        }
        return directory
    }

    private fun verifyGrant(uri: Uri) {
        if (context.contentResolver.persistedUriPermissions.none {
                it.uri == uri && it.isReadPermission && it.isWritePermission })
            throw failure(R.string.tree_access_revoked)
    }

    // Missing picker fallback is an explicitly typed path, still resolved through
    // the same current-user volume list and access checks. Never invent a URI grant.
    fun acceptPath(path: String, readOnly: Boolean = false): File {
        if (!broadAccess()) throw failure(R.string.direct_not_granted)
        if (!path.startsWith('/') || path.contains('\u0000')) throw failure(R.string.absolute_path_required)
        val manager = context.getSystemService(StorageManager::class.java)
        val candidate = File(path).canonicalFile
        val volume = manager.getStorageVolume(candidate) ?: throw failure(R.string.unknown_volume)
        val root = volumeRoot(if (volume.isPrimary) "primary" else volume.uuid
            ?: throw failure(R.string.unknown_volume_id), readOnly)
        if (!candidate.path.startsWith(root.path + "/")) throw failure(R.string.folder_inside_volume)
        val relative = candidate.relativeTo(root).invariantSeparatorsPath
        val uri = DocumentsContract.buildTreeDocumentUri("com.android.externalstorage.documents",
            "${if (volume.isPrimary) "primary" else volume.uuid}:$relative")
        if (resolveTree(uri, readOnly) != candidate) throw failure(R.string.folder_mapping_changed)
        return verifyDirectory(candidate, readOnly = readOnly)
    }

    fun load(): Configuration? {
        if (!preferences.contains("mode")) return null
        return Configuration(preferences.getString("mode", "")!!,
            preferences.getString("roms", "")!!, preferences.getString("tree", "")!!,
            preferences.getBoolean("createSystems", false))
    }

    // Consume durably before the native caller creates folders. Later starts
    // must not regenerate user-deleted systems or overwrite systeminfo files.
    @Synchronized fun consumeCreateSystemDirectories(): Boolean {
        if (!preferences.getBoolean("createSystems", false)) return false
        if (!preferences.edit().putBoolean("createSystems", false).commit())
            throw failure(R.string.configuration_save_failed)
        Log.i("ES-DE-Plus", "System-folder creation request consumed")
        return true
    }

    fun releaseUnselectedGrants(pendingTree: String = "") {
        val keep = setOf(load()?.tree.orEmpty(), pendingTree)
        for (permission in context.contentResolver.persistedUriPermissions) {
            if (permission.uri.toString() in keep) continue
            val flags = (if (permission.isReadPermission) Intent.FLAG_GRANT_READ_URI_PERMISSION else 0) or
                (if (permission.isWritePermission) Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0)
            try {
                context.contentResolver.releasePersistableUriPermission(permission.uri, flags)
                Log.i("ES-DE-Plus", "Released unselected persisted tree grant")
            } catch (error: SecurityException) {
                // A provider can revoke a grant between enumeration/release.
                Log.w("ES-DE-Plus", "Persisted tree grant is no longer available", error)
            }
        }
        Log.i("ES-DE-Plus", "Persisted tree grant count=${context.contentResolver.persistedUriPermissions.size}")
    }

    fun validate(configuration: Configuration, readOnly: Boolean = false): File {
        // Setup still verifies writes to app data and ROMs. Sharing/launching
        // only reads the already configured directories and never provisions them.
        verifyDirectory(appData(), create = !readOnly, readOnly = readOnly)
        val roms = when (configuration.mode) {
            "scoped" -> {
                if (configuration.roms != ownedROMs().canonicalPath || configuration.tree.isNotEmpty())
                    throw failure(R.string.owned_location_changed)
                verifyDirectory(ownedROMs(), create = !readOnly, readOnly = readOnly)
            }
            "direct" -> {
                if (configuration.tree.isEmpty()) acceptPath(configuration.roms, readOnly)
                else {
                    if (!broadAccess()) throw failure(R.string.direct_access_revoked)
                    val uri = Uri.parse(configuration.tree)
                    verifyGrant(uri)
                    val mapped = resolveTree(uri, readOnly)
                    if (mapped.path != configuration.roms) throw failure(R.string.selected_folder_changed)
                    verifyDirectory(mapped, readOnly = readOnly)
                }
            }
            else -> throw failure(R.string.storage_mode_required)
        }
        return roms
    }

    fun problem(): String? = try {
        val config = load() ?: throw failure(R.string.storage_choice_required)
        validate(config)
        null
    } catch (error: Exception) { error.message ?: context.getString(R.string.storage_validation_failed) }

    fun save(configuration: Configuration) {
        validate(configuration)
        if (!preferences.edit().putString("mode", configuration.mode)
                .putString("roms", configuration.roms).putString("tree", configuration.tree)
                .putBoolean("createSystems", configuration.createSystems).commit())
            throw failure(R.string.configuration_save_failed)
        Log.i("ES-DE-Plus", "Storage configuration committed mode=${configuration.mode}")
        releaseUnselectedGrants()
    }
}
