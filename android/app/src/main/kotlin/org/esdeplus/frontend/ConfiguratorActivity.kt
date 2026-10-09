// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus using plain Android views and public SDK APIs.
package org.esdeplus.frontend

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.storage.StorageManager
import android.net.Uri
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.InputMethodManager
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
    private var typedPath = ""
    private var focusId = 0
    private var pathInput: EditText? = null
    private var completed = false

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        storage = StorageModel(applicationContext)
        val draft = state ?: ConfiguratorSession.loadDraft(this)
        val saved = storage.load()
        mode = draft?.getString("mode") ?: saved?.mode ?: ""
        path = draft?.getString("path") ?: saved?.roms ?: ""
        tree = draft?.getString("tree") ?: saved?.tree ?: ""
        typedPath = draft?.getString("typedPath") ?: path
        focusId = draft?.getInt("focusId") ?: 0
        createSystems = draft?.getBoolean("createSystems") ?: saved?.createSystems ?: true
        permissionPending = draft?.getBoolean("permissionPending") ?: false
        resourceError = ConfiguratorSession.resourceFailure != null ||
            (!ConfiguratorSession.configuring && draft?.getBoolean("resourceError") == true)
        message = if (state != null) state.getString("message")
            else intent.getStringExtra("message") ?: draft?.getString("message") ?: storage.problem()
        if (!intent.hasExtra("entry") && draft?.containsKey("entry") == true) {
            @Suppress("DEPRECATION")
            val entry = draft.getParcelable<Intent>("entry")
            intent.putExtra("entry", entry)
        }
        storage.releaseUnselectedGrants(tree)
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
        captureControls()
        rememberDraft()
        writeState(state)
        super.onSaveInstanceState(state)
        if (!completed) ConfiguratorSession.saveDraft(this, state)
        Log.i("ES-DE-Plus", "Configurator instance state saved mode=$mode")
    }

    override fun onPause() {
        captureControls()
        rememberDraft()
        if (!completed) ConfiguratorSession.saveDraft(this, Bundle().also(::writeState))
        super.onPause()
    }

    private fun captureControls() {
        pathInput?.let { typedPath = it.text.toString() }
        if (::content.isInitialized) content.findFocus()?.let { focusId = it.id }
    }

    private fun rememberDraft() {
        if (completed) return
        captureControls()
        ConfiguratorSession.rememberDraft(Bundle().also(::writeState))
    }

    private fun writeState(state: Bundle) {
        state.putString("mode", mode)
        state.putString("path", path)
        state.putString("tree", tree)
        state.putBoolean("createSystems", createSystems)
        state.putBoolean("permissionPending", permissionPending)
        state.putBoolean("resourceError", resourceError)
        state.putString("message", message)
        state.putString("typedPath", typedPath)
        state.putInt("focusId", focusId)
        @Suppress("DEPRECATION")
        val entry = intent.getParcelableExtra<Intent>("entry")
        state.putParcelable("entry", entry)
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
        it.id = label
        it.isFocusable = true
        it.setOnFocusChangeListener { _, focused -> if (focused) rememberDraft() }
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
        captureControls()
        pathInput = null
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
                guarded {
                    ConfiguratorSession.clearDraft(this)
                    completed = true
                    if (!ConfiguratorSession.retryResources()) ConfiguratorSession.finishConfiguration()
                    returnToFrontend()
                }
            }.requestFocus()
            rememberDraft()
            return
        }
        text(getString(R.string.storage_choice))
        val scoped = button(R.string.scoped_mode) {
            guarded {
                val owned = storage.verifyDirectory(storage.ownedROMs(), true).path
                mode = "scoped"
                path = owned
                tree = ""
                storage.releaseUnselectedGrants()
                message = null
                render()
            }
        }
        button(R.string.direct_mode) {
            if (mode != "direct") { path = ""; tree = ""; typedPath = "" }
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
                    id = R.string.path_hint
                    hint = getString(R.string.path_hint)
                    setSingleLine(true)
                    setText(typedPath)
                    isFocusable = true
                    isFocusableInTouchMode = true
                    contentDescription = getString(R.string.path_hint)
                    addTextChangedListener(object : TextWatcher {
                        override fun beforeTextChanged(value: CharSequence?, start: Int, count: Int, after: Int) {}
                        override fun onTextChanged(value: CharSequence?, start: Int, before: Int, count: Int) {
                            typedPath = value?.toString().orEmpty()
                            rememberDraft()
                        }
                        override fun afterTextChanged(value: Editable?) {}
                    })
                    setOnFocusChangeListener { _, focused -> if (focused) rememberDraft() }
                    setOnKeyListener { _, code, event ->
                        when (code) {
                            KeyEvent.KEYCODE_DPAD_CENTER -> {
                                if (event.action == KeyEvent.ACTION_UP)
                                    getSystemService(InputMethodManager::class.java).showSoftInput(this, 0)
                                true
                            }
                            KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN -> {
                                if (event.action == KeyEvent.ACTION_DOWN)
                                    focusSearch(if (code == KeyEvent.KEYCODE_DPAD_UP) View.FOCUS_UP else View.FOCUS_DOWN)?.requestFocus()
                                true
                            }
                            else -> false
                        }
                    }
                }
                pathInput = input
                content.addView(input)
                button(R.string.use_path) {
                    guarded {
                        val selected = storage.acceptPath(input.text.toString())
                        path = selected.path
                        tree = ""
                        storage.releaseUnselectedGrants()
                        message = getString(R.string.path_selected)
                        render()
                    }
                }
            }
        }
        content.addView(CheckBox(this).apply {
            setText(R.string.create_systems)
            id = R.string.create_systems
            isChecked = createSystems
            setOnCheckedChangeListener { _, checked -> createSystems = checked; rememberDraft() }
            setOnFocusChangeListener { _, focused -> if (focused) rememberDraft() }
        })
        button(R.string.continue_frontend) {
            guarded {
                storage.save(StorageModel.Configuration(mode, path, tree, createSystems))
                ConfiguratorSession.clearDraft(this)
                completed = true
                ConfiguratorSession.finishConfiguration()
                returnToFrontend()
            }
        }
        button(R.string.cancel_configuration) { cancelled() }
        (content.findViewById<android.view.View>(focusId)?.takeIf { it.isFocusable && it.isEnabled }
            ?: scoped).requestFocus()
        rememberDraft()
    }

    private fun requestAccess() {
        if (Build.VERSION.SDK_INT == 29) {
            requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
        } else {
            for (permissionIntent in listOf(
                Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")),
                Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))) {
                try {
                    permissionPending = true
                    rememberDraft()
                    startActivity(permissionIntent)
                    return
                } catch (error: ActivityNotFoundException) {
                    permissionPending = false
                } catch (error: SecurityException) {
                    permissionPending = false
                }
            }
            message = getString(R.string.no_all_files)
            render()
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
            startActivityForResult(getSystemService(StorageManager::class.java).primaryStorageVolume
                .createOpenDocumentTreeIntent().addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION), 2)
        } catch (error: ActivityNotFoundException) {
            message = getString(R.string.no_picker)
            render()
        } catch (error: SecurityException) {
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
            pathInput = null
            typedPath = path
            storage.releaseUnselectedGrants(tree)
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
        storage.releaseUnselectedGrants()
        message = getString(R.string.cancelled_recoverable)
        render()
    }
    @Suppress("DEPRECATION")
    override fun onBackPressed() { cancelled() }
}
