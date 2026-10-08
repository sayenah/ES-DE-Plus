// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using plain Android views and public SDK APIs.
package org.esdeplus.frontend

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.net.Uri
import android.provider.Settings
import android.util.Log
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.esdeplus.frontend.bridge.StorageModel

class ConfiguratorActivity : Activity() {
    private lateinit var storage: StorageModel
    private lateinit var content: LinearLayout
    private var mode = ""
    private var path = ""
    private var tree = ""
    private var createSystems = true
    private var message: String? = null
    private var permissionPending = false
    private var resourceError = false

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        storage = StorageModel(applicationContext)
        val saved = storage.load()
        mode = state?.getString("mode") ?: saved?.mode ?: ""
        path = state?.getString("path") ?: saved?.roms ?: ""
        tree = state?.getString("tree") ?: saved?.tree ?: ""
        createSystems = state?.getBoolean("createSystems") ?: saved?.createSystems ?: true
        permissionPending = state?.getBoolean("permissionPending") ?: false
        resourceError = state?.getBoolean("resourceError") ?: (ConfiguratorSession.resourceFailure != null)
        message = state?.getString("message") ?: intent.getStringExtra("message") ?: storage.problem()
        Log.i("ES-DE-Plus", "Configurator created savedState=${state != null} mode=$mode")
        render()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        resourceError = ConfiguratorSession.resourceFailure != null
        message = intent.getStringExtra("message") ?: storage.problem()
        render()
    }

    override fun onSaveInstanceState(state: Bundle) {
        super.onSaveInstanceState(state)
        state.putString("mode", mode)
        state.putString("path", path)
        state.putString("tree", tree)
        state.putBoolean("createSystems", createSystems)
        state.putBoolean("permissionPending", permissionPending)
        state.putBoolean("resourceError", resourceError)
        state.putString("message", message)
    }

    private fun text(value: String) {
        content.addView(TextView(this).apply {
            text = value
            textSize = 18f
            setPadding(0, 8, 0, 8)
        })
    }
    private fun button(label: Int, action: () -> Unit): Button = Button(this).also {
        it.setText(label)
        it.isFocusable = true
        it.setOnClickListener { action() }
        content.addView(it)
    }
    private fun guarded(action: () -> Unit) {
        try { action() }
        catch (error: Exception) {
            message = error.message ?: getString(R.string.configuration_failed)
            render()
        }
    }

    private fun render() {
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 20, 32, 20)
        }
        setContentView(ScrollView(this).apply { addView(content) })
        text(getString(R.string.configure_title, getString(R.string.app_name)))
        message?.let(::text)
        if (resourceError) {
            text(getString(R.string.resource_failure))
            button(R.string.retry) {
                ConfiguratorSession.retryResources()
                returnToFrontend()
            }.requestFocus()
            return
        }
        text(getString(R.string.storage_choice))
        val scoped = button(R.string.scoped_mode) {
            guarded {
                mode = "scoped"
                path = storage.verifyDirectory(storage.ownedROMs(), true).path
                tree = ""
                message = null
                render()
            }
        }
        button(R.string.direct_mode) {
            mode = "direct"
            message = null
            render()
        }
        if (mode == "scoped") {
            text(getString(R.string.scoped_howto, path, path))
        } else if (mode == "direct") {
            text(getString(R.string.direct_explanation))
            if (!storage.broadAccess()) {
                button(R.string.grant_access) { requestAccess() }
            } else {
                button(R.string.choose_folder) { chooseFolder() }
                text(getString(R.string.direct_howto, path.ifEmpty { getString(R.string.no_folder) }))
                val input = EditText(this).apply {
                    hint = getString(R.string.path_hint)
                    setSingleLine(true)
                    setText(path)
                    contentDescription = getString(R.string.path_hint)
                }
                content.addView(input)
                button(R.string.use_path) {
                    guarded {
                        val selected = storage.acceptPath(input.text.toString())
                        path = selected.path
                        tree = ""
                        message = getString(R.string.path_selected)
                        render()
                    }
                }
            }
        }
        content.addView(CheckBox(this).apply {
            setText(R.string.create_systems)
            isChecked = createSystems
            setOnCheckedChangeListener { _, checked -> createSystems = checked }
        })
        button(R.string.continue_frontend) {
            guarded {
                storage.save(StorageModel.Configuration(mode, path, tree, createSystems))
                ConfiguratorSession.finishConfiguration()
                returnToFrontend()
            }
        }
        button(R.string.cancel_configuration) { cancelled() }
        scoped.requestFocus()
    }

    private fun requestAccess() {
        if (Build.VERSION.SDK_INT == 29) {
            requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
        } else {
            try {
                permissionPending = true
                startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:$packageName")))
            } catch (error: ActivityNotFoundException) {
                permissionPending = false
                message = getString(R.string.no_all_files)
                render()
            } catch (error: SecurityException) {
                permissionPending = false
                message = getString(R.string.no_all_files)
                render()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (permissionPending) {
            permissionPending = false
            message = if (storage.broadAccess()) null else getString(R.string.access_denied)
        }
        render()
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        message = if (storage.broadAccess()) null else getString(R.string.access_denied)
        render()
    }

    private fun chooseFolder() {
        try {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION), 2)
        } catch (error: ActivityNotFoundException) {
            message = getString(R.string.no_picker)
            render()
        }
    }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 2) return
        if (resultCode != RESULT_OK || data?.data == null) {
            message = getString(R.string.picker_cancelled)
            render()
            return
        }
        guarded {
            val uri = data.data!!
            val directory = storage.acceptTree(uri, data.flags)
            path = directory.path
            tree = uri.toString()
            message = null
            render()
        }
    }

    private fun returnToFrontend() {
        // A live SDL caller resumes through its registered static callback.
        // After process death launch the recorded entry; HOME is never inferred
        // from a preference, Leanback, or the configurator's own intent.
        if (!ConfiguratorSession.configuring) {
            @Suppress("DEPRECATION")
            val entry = intent.getParcelableExtra<Intent>("entry")
            startActivity(entry ?: Intent(this, MainActivity::class.java))
        }
        finish()
    }
    private fun cancelled() {
        message = getString(R.string.cancelled_recoverable)
        render()
    }
    @Suppress("DEPRECATION")
    override fun onBackPressed() { cancelled() }
}
