// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using public storage, URI and grant APIs.
package org.esdeplus.frontend.bridge

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.storage.StorageManager
import android.provider.DocumentsContract
import java.io.File

class RomTransport(private val context: Context) {
    private val storage = StorageModel(context)
    fun root(): File = storage.validate(storage.load() ?: error("Storage is not configured"))

    fun file(path: String): File {
        require(path.startsWith('/') && !path.contains('\u0000'))
        val root = root()
        val candidate = File(path).canonicalFile
        require(candidate.path.startsWith(root.path + "/") && candidate.isFile && candidate.canRead()) {
            "ROM is not a readable file inside the selected ROM directory"
        }
        return candidate
    }

    fun provider(path: String): Uri {
        val file = file(path)
        return Uri.Builder().scheme("content").authority(context.packageName + ".roms")
            .appendPath("rom").appendPath(file.relativeTo(root()).invariantSeparatorsPath).build()
    }

    fun providerFile(uri: Uri): File {
        require(uri.scheme == "content" && uri.authority == context.packageName + ".roms" &&
            uri.query == null && uri.fragment == null && uri.pathSegments.size == 2 && uri.pathSegments[0] == "rom")
        val relative = uri.pathSegments[1]
        require(relative.split('/').none { it.isEmpty() || it == "." || it == ".." || it.contains('\\') || it.contains('\u0000') })
        return file(File(root(), relative).path)
    }

    @Suppress("DEPRECATION")
    fun saf(path: String): Uri {
        val file = file(path)
        val manager = context.getSystemService(StorageManager::class.java)
        val volume = manager.getStorageVolume(file) ?: error("ROM volume is unavailable")
        require(volume.state == Environment.MEDIA_MOUNTED)
        val suffix = "/Android/data/${context.packageName}/files"
        val roots = context.getExternalFilesDirs(null).filterNotNull().mapNotNull { owned ->
            val mapped = manager.getStorageVolume(owned)
            if (mapped == null || mapped.isPrimary != volume.isPrimary || mapped.uuid != volume.uuid) null
            else owned.canonicalPath.takeIf { it.endsWith(suffix) }?.removeSuffix(suffix)?.let(::File)
        }
        val root = roots.singleOrNull()?.canonicalFile ?: error("Current-user volume cannot be verified")
        if (Build.VERSION.SDK_INT >= 30) require(volume.directory?.canonicalFile == root)
        require(file.path.startsWith(root.path + "/"))
        val relative = file.relativeTo(root).invariantSeparatorsPath
        require(!relative.startsWith("Android/", true)) { "External-storage SAF cannot expose app-owned Android/data ROMs" }
        val id = "${if (volume.isPrimary) "primary" else volume.uuid ?: error("Unknown volume ID")}:$relative"
        val grant = context.contentResolver.persistedUriPermissions.firstOrNull {
            if (!it.isReadPermission || it.uri.authority != "com.android.externalstorage.documents" ||
                !DocumentsContract.isTreeUri(it.uri)) false
            else {
                val tree = DocumentsContract.getTreeDocumentId(it.uri)
                id == tree || id.startsWith(tree.trimEnd('/') + "/")
            }
        }
        return if (grant != null) DocumentsContract.buildDocumentUriUsingTree(grant.uri, id)
            else DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", id)
    }

    fun holdsReadGrant(uri: Uri): Boolean {
        val id = DocumentsContract.getDocumentId(uri)
        return context.contentResolver.persistedUriPermissions.any {
            if (!it.isReadPermission || it.uri.authority != uri.authority || !DocumentsContract.isTreeUri(it.uri)) false
            else {
                val tree = DocumentsContract.getTreeDocumentId(it.uri)
                (id == tree || id.startsWith(tree.trimEnd('/') + "/")) &&
                    context.checkUriPermission(uri, android.os.Process.myPid(), android.os.Process.myUid(),
                        Intent.FLAG_GRANT_READ_URI_PERMISSION) == android.content.pm.PackageManager.PERMISSION_GRANTED
            }
        }
    }
}
