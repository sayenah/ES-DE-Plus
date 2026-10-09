// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using public storage, URI and grant APIs.
package org.esdeplus.frontend.bridge

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.os.storage.StorageManager
import android.provider.DocumentsContract
import java.io.File
import java.security.MessageDigest

class RomTransport(private val context: Context) {
    private val storage = StorageModel(context)
    fun root(): File = storage.validate(storage.load() ?: error("Storage is not configured"))

    fun file(path: String): File = fileInside(root(), path)

    fun raw(path: String): String {
        root()  // Revoked/unavailable selected storage remains a visible launch failure.
        require(path.startsWith('/') && !path.contains('\u0000'))
        return File(path).absolutePath
    }

    fun provider(path: String): Uri {
        val file = file(path)
        val root = root()
        return Uri.Builder().scheme("content").authority(context.packageName + ".roms")
            .appendPath("rom").appendPath(rootIdentity(root)).appendPath(file.relativeTo(root).invariantSeparatorsPath).build()
    }

    fun providerFile(uri: Uri): File {
        require(uri.scheme == "content" && uri.authority == context.packageName + ".roms" &&
            uri.query == null && uri.fragment == null && uri.pathSegments.size == 3 && uri.pathSegments[0] == "rom")
        val root = root()
        // A grant from an earlier directory selection must not expose a file
        // with the same relative name in a newly selected ROM directory.
        require(uri.pathSegments[1] == rootIdentity(root))
        val relative = uri.pathSegments[2]
        require(relative.split('/').none { it.isEmpty() || it == "." || it == ".." || it.contains('\\') || it.contains('\u0000') })
        return file(File(root, relative).path)
    }

    private fun rootIdentity(root: File): String = MessageDigest.getInstance("SHA-256")
        .digest(root.path.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    @Suppress("DEPRECATION")
    fun saf(path: String): Uri {
        val file = File(raw(path)).canonicalFile
        require(file.exists() && file.canRead())
        val manager = context.getSystemService(StorageManager::class.java)
        val volume = manager.getStorageVolume(file) ?: error("ROM volume is unavailable")
        require(volume.state == Environment.MEDIA_MOUNTED)
        val root = storage.volumeRoot(if (volume.isPrimary) "primary" else volume.uuid ?: error("Unknown volume ID"))
        require(file.path.startsWith(root.path + "/"))
        val relative = file.relativeTo(root).invariantSeparatorsPath
        require(listOf("Android/data", "Android/obb").none {
            relative.equals(it, true) || relative.startsWith("$it/", true)
        }) { "External-storage SAF cannot expose Android/data or Android/obb ROMs" }
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

    companion object {
        // Both URI creation and every provider open use this same boundary.
        // Its caller supplies only the independently validated selected root.
        fun fileInside(root: File, path: String): File {
            require(path.startsWith('/') && !path.contains('\u0000'))
            val canonicalRoot = root.canonicalFile
            val candidate = File(path).canonicalFile
            require(candidate.path.startsWith(canonicalRoot.path + "/") && candidate.isFile && candidate.canRead()) {
                "ROM is not a readable file inside the selected ROM directory"
            }
            return candidate
        }
    }
}
