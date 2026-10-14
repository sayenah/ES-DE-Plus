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
                             val createSystems: Boolean, val data: String = "")
    private val preferences = context.getSharedPreferences("storage", Context.MODE_PRIVATE)
    private val grants = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION

    private fun failure(id: Int, vararg values: Any) = IOException(context.getString(id, *values))

    fun externalFiles(): File = context.getExternalFilesDir(null)
        ?: throw failure(R.string.owned_storage_unavailable)
    fun privateData(): File = File(externalFiles(), "ES-DE-Plus")
    fun appData(): File {
        val config = load() ?: throw failure(R.string.storage_choice_required)
        return dataDirectory(config)
    }
    fun defaultData(): File = File(volumeRoot("primary"), "ES-DE-Plus")
    private fun dataDirectory(config: Configuration): File = when (config.mode) {
        "scoped" -> privateData().also {
            if (config.data != it.path) throw failure(R.string.data_folder_required)
        }
        "direct" -> {
            if (config.data.isEmpty()) throw failure(R.string.data_folder_required)
            structuralPath(config.data, data = true)
        }
        else -> throw failure(R.string.storage_mode_required)
    }
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

    internal fun resolveTree(uri: Uri, readOnly: Boolean = false, data: Boolean = false): File {
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
        // ROMs never use an official data directory. Data destinations require consent in the UI.
        if ((!data && segments.any { it.equals("ES-DE", true) || it.equals(".emulationstation", true) }) ||
            segments.first().equals("Android", true))
            throw failure(R.string.official_data_refused)
        val root = volumeRoot(parts[0], readOnly)
        return File(root, relative)
    }

    // Lexical mapping only: no canonicalisation, stat, listing, settings read or
    // access probe at the candidate. The exact mapped path is shown for consent.
    fun structuralPath(path: String, data: Boolean = false, readOnly: Boolean = false): File {
        if (!broadAccess()) throw failure(R.string.direct_not_granted)
        if (!path.startsWith('/') || path.contains('\u0000') || path.contains('\\'))
            throw failure(R.string.absolute_path_required)
        val primary = volumeRoot("primary", readOnly)
        val mapped = if (path == "/sdcard" || path.startsWith("/sdcard/"))
            primary.path + path.removePrefix("/sdcard") else path
        val candidate = File(mapped)
        val manager = context.getSystemService(StorageManager::class.java)
        val roots = manager.storageVolumes.mapNotNull { volume ->
            try { volumeRoot(if (volume.isPrimary) "primary" else volume.uuid ?: return@mapNotNull null, readOnly) }
            catch (_: IOException) { null }
        }
        val root = roots.singleOrNull { candidate.path.startsWith(it.path + "/") }
            ?: throw failure(R.string.folder_inside_volume)
        val relative = candidate.path.removePrefix(root.path + "/")
        val uri = DocumentsContract.buildTreeDocumentUri("com.android.externalstorage.documents",
            "${manager.getStorageVolume(root)?.let { if (it.isPrimary) "primary" else it.uuid }}:$relative")
        return resolveTree(uri, readOnly, data)
    }

    // Run only for an already confirmed/accepted path. Resolve symlinks then
    // reapply the same volume/Android/ROM guards to their actual destination.
    private fun inspectedPath(path: String, data: Boolean = false, readOnly: Boolean = false): File {
        val lexical = structuralPath(path, data, readOnly)
        val canonical = lexical.canonicalFile
        if (structuralPath(canonical.path, data, readOnly) != canonical)
            throw failure(R.string.folder_mapping_changed)
        return canonical
    }

    fun disjoint(data: File, roms: File) {
        if (data == roms || data.path.startsWith(roms.path + "/") || roms.path.startsWith(data.path + "/"))
            throw failure(R.string.overlapping_folders)
    }

    // This is the only shared-data provisioning entry point. The configurator
    // invokes it in the positive action of the exact-destination consent dialog.
    fun confirmData(destination: String, roms: String = ""): File {
        val directory = inspectedPath(destination, data = true)
        if (roms.isNotEmpty()) disjoint(directory, File(roms).canonicalFile)
        verifyDirectory(directory, create = true)
        validateDataContents(directory)
        Log.i("ES-DE-Plus", "Application-data destination confirmed: $directory")
        return directory
    }

    fun validateDataContents(directory: File, readOnly: Boolean = false): String? {
        for (name in listOf("settings", "logs", "gamelists", "downloaded_media", "collections", "themes",
                "custom_systems", "scripts", "screensavers", "controllers")) {
            val child = File(directory, name)
            if (child.exists()) verifyDirectory(child, readOnly = readOnly)
        }
        for (name in listOf("settings/es_settings.xml", "es_settings.xml", "settings/es_input.xml", "es_input.xml")) {
            val child = File(directory, name)
            if (child.exists() && (!child.isFile || !Os.access(child.path,
                    OsConstants.R_OK or (if (readOnly) 0 else OsConstants.W_OK))))
                throw failure(R.string.directory_access_failed, child)
        }
        val media = try { AdoptedSettings.mediaDirectory(directory) }
            catch (error: Exception) { throw failure(R.string.invalid_adopted_settings) } ?: return null
        try { verifyDirectory(media, readOnly = readOnly) }
        catch (error: Exception) { throw failure(R.string.media_unavailable, media) }
        return media.path
    }

    fun acceptTree(uri: Uri, flags: Int): File {
        if (!broadAccess()) throw failure(R.string.direct_not_granted)
        if ((flags and grants) != grants || flags and Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION == 0)
            throw failure(R.string.persistent_access_required)
        val directory = verifyDirectory(inspectedPath(resolveTree(uri).path))
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
        return verifyDirectory(inspectedPath(path, readOnly = readOnly), readOnly = readOnly)
    }

    fun load(): Configuration? {
        if (!preferences.contains("mode")) return null
        return Configuration(preferences.getString("mode", "")!!,
            preferences.getString("roms", "")!!, preferences.getString("tree", "")!!,
            preferences.getBoolean("createSystems", false), preferences.getString("data",
                if (preferences.getString("mode", "") == "scoped") privateData().path else "")!!)
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
        // Validation never creates a missing root or substitutes another root.
        if (configuration.mode == "direct" && !broadAccess()) throw failure(R.string.direct_access_revoked)
        val selectedData = dataDirectory(configuration)
        val data = if (configuration.mode == "direct") inspectedPath(selectedData.path, data = true,
            readOnly = readOnly) else selectedData.canonicalFile
        if (data.path != configuration.data) throw failure(R.string.selected_folder_changed)
        verifyDirectory(data, readOnly = readOnly)
        validateDataContents(data, readOnly)
        val roms = when (configuration.mode) {
            "scoped" -> {
                if (configuration.roms != ownedROMs().canonicalPath || configuration.tree.isNotEmpty())
                    throw failure(R.string.owned_location_changed)
                verifyDirectory(ownedROMs(), readOnly = readOnly)
            }
            "direct" -> {
                if (configuration.tree.isEmpty()) acceptPath(configuration.roms, readOnly)
                else {
                    if (!broadAccess()) throw failure(R.string.direct_access_revoked)
                    val uri = Uri.parse(configuration.tree)
                    verifyGrant(uri)
                    val mapped = inspectedPath(resolveTree(uri, readOnly).path, readOnly = readOnly)
                    if (mapped.path != configuration.roms) throw failure(R.string.selected_folder_changed)
                    verifyDirectory(mapped, readOnly = readOnly)
                }
            }
            else -> throw failure(R.string.storage_mode_required)
        }
        disjoint(data, roms)
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
                .putString("data", configuration.data)
                .putBoolean("createSystems", configuration.createSystems).commit())
            throw failure(R.string.configuration_save_failed)
        Log.i("ES-DE-Plus", "Storage configuration committed mode=${configuration.mode}")
        releaseUnselectedGrants()
    }
}
