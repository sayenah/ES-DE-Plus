// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Production-path probes with a separate-UID recipient.
package org.esdeplus.frontend

import android.app.Instrumentation
import android.app.BroadcastOptions
import android.content.BroadcastReceiver
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Process
import android.os.SystemClock
import android.system.Os
import org.esdeplus.frontend.bridge.AppDiscovery
import org.esdeplus.frontend.bridge.CoreQuery
import org.esdeplus.frontend.bridge.GameLauncher
import org.esdeplus.frontend.bridge.RomTransport
import org.esdeplus.frontend.bridge.StorageModel
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

object LaunchSmoke {
    private const val stub = "org.esdeplus.stub"
    private val empty = emptyArray<String>()
    private fun equal(actual: Any?, expected: Any?, label: String) {
        fun assertion(value: Any?) { check(value == expected) { "$label: expected=$expected actual=$value" } }
        assertion(actual)
        try { assertion(Any()) } catch (control: IllegalStateException) { return }
        error("Equality assertion accepted its positive control: $label")
    }
    private fun refused(label: String, action: () -> Unit) {
        fun assertion(attempt: () -> Unit) {
            var rejected = false
            try { attempt() } catch (expected: Exception) { rejected = true }
            check(rejected) { "$label was accepted" }
        }
        assertion(action)
        try { assertion {} } catch (control: IllegalStateException) { return }
        error("Refusal assertion accepted its positive control: $label")
    }

    fun userFile(context: Context, relative: String, contents: String?): String {
        // App-owned user configuration must be prepared through the actual
        // application's UID; adb sync cannot write it on all Android images.
        equal(relative in listOf("custom_systems/es_systems.xml", "custom_systems/es_find_rules.xml",
            "settings/es_settings.xml"), true, "Probe user-file scope")
        val file = File(StorageModel(context).appData(), relative)
        if (contents == null) {
            if (file.exists()) equal(file.delete(), true, "Remove probe user file")
            equal(file.exists(), false, "Probe user file removed")
        } else {
            equal(file.parentFile!!.mkdirs() || file.parentFile!!.isDirectory, true, "User-file directory")
            file.writeText(contents)
            equal(file.readText(), contents, "Actual user-file contents")
        }
        return "PASS: user file prepared under frontend UID; assertion positive controls rejected\n"
    }

    fun revokeTree(context: Context): String {
        val storage = StorageModel(context)
        val configuration = storage.load() ?: error("Configuration is required")
        if (configuration.tree.isEmpty()) return "CAPABILITY: real typed-path selection already has no persisted tree\n"
        val rom = File(configuration.roms, "nes/Smoke Alpha.nes")
        val base = arrayOf(stub, ".RecipientActivity", "", "", "", "%ROMPROVIDER%", configuration.roms, rom.path)
        // Build through the production path before removing the real grant;
        // no preference or permission is fabricated.
        equal(GameLauncher(context).intent(base, empty, empty, empty, empty, empty).data?.authority,
            context.packageName + ".roms", "Valid grant before revocation")
        context.contentResolver.releasePersistableUriPermission(Uri.parse(configuration.tree),
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        equal(NativeBridge(context).launchGame(base, empty, empty, empty, empty, empty, false), -1, "Revoked selected tree refuses launch")
        equal(storage.load(), configuration, "Revocation never substitutes configuration")
        return "PASS: real selected tree revoked; production launch refused; original selection retained\n"
    }

    fun run(context: Context): String {
        val bridge = NativeBridge(context)
        val transport = RomTransport(context)
        val root = transport.root()
        val directory = File(root, "nes/Transport 🚀")
        equal(directory.mkdirs() || directory.isDirectory, true, "Probe directory")
        val bytes = byteArrayOf(69, 83, 68, 69, 0, -1, 42)
        var rom = File(directory, "Game 🚀 #?%+,;.nes")
        var filenameCapability = "ROM volume supports Unicode and all requested reserved URI characters."
        try { rom.writeBytes(bytes) }
        catch (error: java.io.FileNotFoundException) {
            val errno = (error.cause as? android.system.ErrnoException)?.errno
            if (errno !in listOf(android.system.OsConstants.EPERM, android.system.OsConstants.EINVAL)) throw error
            rom = File(directory, "Game 🚀 #%+,;.nes")
            rom.writeBytes(bytes)  // Actual writable-file control differs only by '?'.
            filenameCapability = "CAPABILITY: ROM volume refused the filename containing '?' (errno=$errno); the real transport file retains Unicode, #, %, +, comma and semicolon."
        }
        val sibling = File(directory, "sibling.nes").apply { writeBytes(bytes) }
        val outside = File(context.filesDir, "outside-rom.nes").apply { writeBytes(bytes) }
        val link = File(directory, "escape.nes")
        var symlinkCapability = "ROM volume supports a real symlink; provider refusal exercised."
        try { Os.symlink(outside.path, link.path) }
        catch (error: android.system.ErrnoException) {
            if (error.errno !in listOf(android.system.OsConstants.EPERM, android.system.OsConstants.EACCES, android.system.OsConstants.EOPNOTSUPP,
                    android.system.OsConstants.ENOSYS)) throw error
            symlinkCapability = "CAPABILITY: ROM volume refused symlink creation (errno=${error.errno}); canonical containment exercised on the genuine SDK-owned internal filesystem."
        }
        val boundaryRoot = File(context.cacheDir, "rom-boundary-probe").apply { mkdirs() }
        val inside = File(boundaryRoot, "inside.nes").apply { writeBytes(bytes) }
        val internalLink = File(boundaryRoot, "escape.nes")
        Os.symlink(outside.path, internalLink.path)
        equal(RomTransport.fileInside(boundaryRoot, inside.path), inside.canonicalFile, "Canonical boundary positive read")
        refused("Real symlink escape on supported filesystem") { RomTransport.fileInside(boundaryRoot, internalLink.path) }
        val handlerThread = HandlerThread("ESDEPlus-recipient-observer").apply { start() }
        val next = AtomicReference<CountDownLatch>()
        val observation = AtomicReference<JSONObject>()
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(receiving: Context, intent: Intent) {
                if (intent.action == "org.esdeplus.stub.OBSERVATION") {
                    observation.set(JSONObject(intent.getStringExtra("json")!!))
                    next.get()?.countDown()
                }
            }
        }
        val filter = IntentFilter("org.esdeplus.stub.OBSERVATION")
        if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(receiver, filter, null, Handler(handlerThread.looper), Context.RECEIVER_EXPORTED)
        else {
            @Suppress("DEPRECATION")
            context.registerReceiver(receiver, filter, null, Handler(handlerThread.looper))
        }
        val evidence = StringBuilder()
        evidence.append(filenameCapability).append('\n')
        evidence.append(symlinkCapability).append('\n')
        val registered = java.util.concurrent.atomic.AtomicBoolean(false)
        val orderedContext = object : ContextWrapper(context) {
            override fun registerReceiver(receiver: BroadcastReceiver?, filter: IntentFilter,
                permission: String?, scheduler: Handler?): Intent? {
                val result = super.registerReceiver(receiver, filter, permission, scheduler)
                registered.set(true)
                return result
            }
            override fun registerReceiver(receiver: BroadcastReceiver?, filter: IntentFilter,
                permission: String?, scheduler: Handler?, flags: Int): Intent? {
                val result = super.registerReceiver(receiver, filter, permission, scheduler, flags)
                registered.set(true)
                return result
            }
            override fun sendBroadcast(intent: Intent) {
                equal(registered.get(), true, "Registration precedes query dispatch")
                super.sendBroadcast(intent)
            }
            override fun unregisterReceiver(receiver: BroadcastReceiver) {
                super.unregisterReceiver(receiver)
                registered.set(false)
            }
        }
        fun base(data: String = "", activity: String = ".RecipientActivity") =
            arrayOf(stub, activity, "android.intent.action.VIEW", "android.intent.category.DEFAULT", "application/octet-stream", data, directory.path, rom.path)
        fun receive(arguments: Array<String>, strings: Array<String> = empty, lists: Array<String> = empty,
                    integers: Array<String> = empty, booleans: Array<String> = empty, flags: Array<String> = empty): JSONObject {
            val latch = CountDownLatch(1)
            next.set(latch)
            equal(bridge.launchGame(arguments, strings + arrayOf("replyPackage", context.packageName), lists,
                integers, booleans, flags, false), 0, "startActivity result")
            equal(latch.await(10, TimeUnit.SECONDS), true, "Separate-UID recipient observation")
            return observation.get().also { evidence.append(it).append('\n') }
        }
        fun configureQuery(value: String) {
            equal(receive(base(), arrayOf("queryMode", value)).getString("queryMode"), value, "Receiver configuration")
        }
        fun query(mode: String, expected: Int) {
            configureQuery(mode)
            val begin = SystemClock.elapsedRealtimeNanos()
            val actual = CoreQuery(orderedContext).query(stub, "test_libretro_android.so")
            val elapsed = TimeUnit.NANOSECONDS.toMillis(SystemClock.elapsedRealtimeNanos() - begin)
            equal(actual, expected, "Core query $mode")
            equal(registered.get(), false, "Query receiver cleaned up $mode")
            equal(elapsed <= 1000, true, "One total deadline $mode ($elapsed ms)")
            evidence.append("QUERY $mode result=$actual elapsedMs=$elapsed\n")
        }
        try {
            equal(bridge.checkEmulatorInstalled(stub, ".RecipientActivity"), true, "Relative target")
            equal(bridge.checkEmulatorInstalled(stub, ""), true, "Package target")
            equal(bridge.checkEmulatorInstalled(stub, ".TelevisionOnly"), true, "Leanback-only component")
            for (activity in listOf(".MissingActivity", ".PrivateActivity", ".ProtectedActivity", ".DisabledActivity")) {
                equal(bridge.checkEmulatorInstalled(stub, activity), false, "Invalid target discovery $activity")
                equal(bridge.launchGame(base(activity = activity), empty, empty, empty, empty, empty, false), -1, "Invalid target launch $activity")
            }
            equal(bridge.checkEmulatorInstalled("org.esdeplus.missing", ""), false, "Missing package")
            val launcher = GameLauncher(context)
            val expectedHash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            val provider = transport.provider(rom.path)
            val boundaries = arrayOf(transport.provider(sibling.path).toString(),
                provider.buildUpon().path("/rom/../outside-rom.nes").build().toString(),
                Uri.Builder().scheme("content").authority(provider.authority).appendPath("rom")
                    .appendPath(provider.pathSegments[1]).appendPath("nes/Transport 🚀/escape.nes").build().toString())
            val received = receive(base("%ROMPROVIDER%"),
                arrayOf("literal", "雪", "plain", "%ROM%"),
                arrayOf("words", "one,t\\,wo,雪", "documented", "pone,p\\\\,two,pthree",
                    "deniedUris", boundaries.joinToString(",") { it.replace(",", "\\,") }),
                arrayOf("number", "-2147483648"), arrayOf("yes", "1", "no", "false"),
                arrayOf("%ACTIVITY_CLEAR_TOP%", "%ACTIVITY_NO_HISTORY%"))
            equal(received.getString("sha256"), expectedHash, "Provider recipient bytes")
            equal(received.getInt("uid") != Process.myUid(), true, "Distinct recipient UID")
            equal(received.getString("action"), "android.intent.action.VIEW", "Action")
            equal(received.getString("mime"), "application/octet-stream", "MIME")
            equal(received.getString("data"), provider.toString(), "Provider data URI")
            equal(received.getJSONArray("categories").toString(), "[\"android.intent.category.DEFAULT\"]", "Category")
            val requestedFlags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NO_HISTORY or Intent.FLAG_GRANT_READ_URI_PERMISSION
            equal(received.getInt("flags") and requestedFlags, requestedFlags, "Activity and read flags")
            equal(received.getInt("flags") and Intent.FLAG_GRANT_WRITE_URI_PERMISSION, 0, "No write grant")
            val extras = received.getJSONObject("extras")
            equal(extras.getJSONObject("words").getString("type"), "[Ljava.lang.String;", "Array type")
            equal(extras.getJSONObject("words").getJSONArray("value").toString(), "[\"one\",\"t,wo\",\"雪\"]", "Escaped commas")
            equal(extras.getJSONObject("documented").getJSONArray("value").toString(), "[\"pone\",\"p,two\",\"pthree\"]", "INSTALL.md array spelling")
            equal(extras.getJSONObject("number").getString("type"), "java.lang.Integer", "Integer type")
            equal(extras.getJSONObject("number").getInt("value"), Int.MIN_VALUE, "Integer value")
            equal(extras.getJSONObject("yes").getBoolean("value"), true, "Boolean true")
            equal(extras.getJSONObject("no").getBoolean("value"), false, "Boolean false")
            equal(extras.getJSONObject("literal").getString("value"), "雪", "Unicode string")
            equal(extras.getJSONObject("plain").getString("value"), rom.path, "Absolute path meaning")
            equal(received.getString("displayName"), rom.name, "Provider display name")
            equal(received.getLong("size"), bytes.size.toLong(), "Provider size")
            for (key in listOf("writeDenied", "deleteDenied", "insertDenied", "updateDenied", "boundary0", "boundary1", "boundary2"))
                equal(received.getBoolean(key), true, "Recipient boundary $key")
            context.revokeUriPermission(provider, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            val revoked = receive(base(), arrayOf("ROM", provider.toString()))
            equal(revoked.has("readError"), true, "Revoked provider grant denies recipient")
            equal(receive(base("%ROMPROVIDER%")).getString("sha256"), expectedHash, "Fresh exact grant restores recipient read")
            // Direct production provider calls check containment independently
            // of Android's external UID permission enforcement.
            context.contentResolver.openInputStream(provider)!!.use { equal(it.readBytes().contentEquals(bytes), true, "Provider positive read") }
            refused("Symlink escape") { transport.provider(link.path) }
            refused("Directory") { transport.provider(directory.path) }
            refused("App-data file") { transport.provider(outside.path) }
            equal(transport.raw(directory.path), directory.absolutePath, "Raw transport preserves directory-valued ROMs")
            equal(transport.raw(outside.path), outside.absolutePath, "Provider scope does not redefine raw-path meaning")
            refused("Traversal") { transport.providerFile(provider.buildUpon().path("/rom/../outside-rom.nes").build()) }
            refused("Retired root grant") { transport.providerFile(Uri.Builder().scheme("content")
                .authority(provider.authority).appendPath("rom").appendPath("retired-root")
                .appendPath(provider.pathSegments[2]).build()) }
            for (value in listOf("2147483648", "-2147483649", "nan"))
                refused("Integer range $value") { launcher.intent(base(), empty, empty, arrayOf("number", value), empty, empty) }
            refused("Boolean validation") { launcher.intent(base(), empty, empty, empty, arrayOf("bool", "maybe"), empty) }
            refused("Provider extra") { launcher.intent(base(), arrayOf("ROM", "%ROMPROVIDER%"), empty, empty, empty, empty) }
            val combined = launcher.intent(base("%ROMPROVIDER%"), empty, empty, empty, empty,
                arrayOf("%ACTIVITY_CLEAR_TASK%", "%ACTIVITY_CLEAR_TOP%", "%ACTIVITY_NO_HISTORY%"))
            equal(combined.flags and Intent.FLAG_ACTIVITY_CLEAR_TASK, Intent.FLAG_ACTIVITY_CLEAR_TASK, "Clear task")
            equal(combined.data.toString(), provider.toString(), "Data/MIME set together")
            equal(combined.type, "application/octet-stream", "Data/MIME preserved")
            for (name in listOf("", ".RecipientActivity", ".TelevisionOnly")) {
                val selected = receive(base(activity = name))
                equal(selected.getString("component").substringBefore('/'), stub, "Target never leaves package")
            }
            equal(receive(base(activity = ".TelevisionOnly"), arrayOf("queryMode", "phone-off"))
                .getString("queryMode"), "phone-off", "Recipient disables its own phone launchers")
            try {
                equal(bridge.checkEmulatorInstalled(stub, ".RecipientActivity"), false, "Disabled phone launcher")
                equal(receive(base(activity = "")).getString("component"), "$stub/$stub.TelevisionOnly",
                    "Package-only Leanback fallback with no phone launcher")
            } finally {
                equal(receive(base(activity = ".TelevisionOnly"), arrayOf("queryMode", "restore-launchers"))
                    .getString("queryMode"), "restore-launchers", "Recipient restores its own phone launchers")
            }
            val raw = receive(base("%ROM%"))
            val configuration = StorageModel(context).load()!!
            if (Build.VERSION.SDK_INT == 29 || configuration.mode == "direct")
                equal(raw.getString("sha256"), expectedHash, "Recipient raw path bytes with emulator-side permission")
            else {
                equal(raw.has("readError"), true, "App-owned raw path cannot be read by another app on API 30+")
                evidence.append("CAPABILITY: API 30+ app-owned raw path refuses separate-UID read; use ROMPROVIDER.\n")
            }
            if (configuration.mode == "direct") {
                val saf = transport.saf(rom.path)
                val data = receive(base("%ROMSAF%"))
                val extra = receive(base(), arrayOf("bootPath", "%ROMSAF%"))
                equal(extra.getJSONObject("extras").getJSONObject("bootPath").getString("type"), "java.lang.String", "SAF extra stays string")
                if (transport.holdsReadGrant(saf)) {
                    equal(data.getString("sha256"), expectedHash, "SAF data recipient bytes")
                    equal(extra.getString("sha256"), expectedHash, "SAF extra ClipData recipient bytes")
                } else {
                    equal(launcher.intent(base("%ROMSAF%"), empty, empty, empty, empty, empty).flags and Intent.FLAG_GRANT_READ_URI_PERMISSION, 0, "Typed path never invents grant")
                    evidence.append("CAPABILITY: configured typed path has no persisted tree; SAF requires recipient-owned access.\n")
                }
            } else {
                equal(bridge.launchGame(base("%ROMSAF%"), empty, empty, empty, empty, empty, false), -1, "App-owned SAF refusal")
            }
            val apps = bridge.getInstalledApps(false, false).toList().chunked(2)
            equal(apps.all { it.size == 2 }, true, "Alternating pairs")
            val targets = apps.map { it[1] }
            equal(targets.distinct().size, targets.size, "No duplicate components")
            val fixture = apps.filter { it[1].startsWith("$stub/") }
            equal(fixture.size, 4, "Phone, Leanback and collision apps")
            val names = fixture.map { it[0] }
            equal(names.distinct().size, names.size, "Collision resistant names")
            equal(AppDiscovery.filename("Collision/🚀", "a" ) != AppDiscovery.filename("Collision\\🚀", "b"), true, "Sanitized-label collision")
            equal(AppDiscovery.filename("雪", "a"), AppDiscovery.filename("雪", "a"), "Deterministic Unicode filename")
            equal(AppDiscovery.filename("🚀".repeat(100), "long").toByteArray(Charsets.UTF_8).size + 4 <= 255,
                true, "Filesystem byte-length limit with extension")
            equal(names.all { !it.contains('/') && !it.contains('\\') }, true, "Filesystem-safe inventory")
            val temp = File(StorageModel(context).appData(), "importer_temp")
            for (name in names) {
                val icon = File(temp, "icons/$name.png")
                equal(icon.readBytes().take(8), listOf(-119, 80, 78, 71, 13, 10, 26, 10).map { it.toByte() }, "Icon PNG $name")
                equal(File(temp, "media/$name.png").exists(), false, "Artwork opt-out $name")
            }
            equal(bridge.getInstalledApps(false, true).toList(), apps.flatten(), "Artwork cannot change membership")
            for (name in names) equal(File(temp, "media/$name.png").isFile, true, "Requested banner $name")
            val games = bridge.getInstalledApps(true, false).toList().chunked(2)
            equal(games.filter { it[1].startsWith("$stub/") }.size, 4, "Games filter retains game fixtures")
            equal(games.all {
                @Suppress("DEPRECATION") val info = context.packageManager.getApplicationInfo(it[1].substringBefore('/'), 0)
                info.category == android.content.pm.ApplicationInfo.CATEGORY_GAME || info.flags and android.content.pm.ApplicationInfo.FLAG_IS_GAME != 0
            }, true, "Games filter excludes non-games")
            query("valid", 1); query("absent", 0); query("malformed", -2); query("oversized", -2)
            query("none", -1); query("unrelated", -1); query("late", -1)
            query("absent", -2)  // a reply without a request ID cannot safely veto after a failed query
            Thread.sleep(1300)
            query("valid", 1)
            val cannotDispatch = object : ContextWrapper(orderedContext) {
                override fun sendBroadcast(intent: Intent) { throw SecurityException("Dispatch failure probe") }
            }
            equal(CoreQuery(cannotDispatch).query(stub, "test_libretro_android.so"), -2, "Failed query dispatch")
            equal(registered.get(), false, "Dispatch failure unregisters receiver")
            val cannotRegister = object : ContextWrapper(context) {
                override fun registerReceiver(receiver: BroadcastReceiver?, filter: IntentFilter,
                    permission: String?, scheduler: Handler?): Intent? = throw SecurityException("Registration failure probe")
                override fun registerReceiver(receiver: BroadcastReceiver?, filter: IntentFilter,
                    permission: String?, scheduler: Handler?, flags: Int): Intent? = throw SecurityException("Registration failure probe")
            }
            equal(CoreQuery(cannotRegister).query(stub, "test_libretro_android.so"), -2, "Failed query registration")
            query("valid", 1)  // failure paths release serialization and delivery resources
            if (Build.VERSION.SDK_INT >= 34) query("anonymous", -2)
            if (Build.VERSION.SDK_INT >= 34) {
                configureQuery("none")
                val wrongSender = object : ContextWrapper(context) {
                    override fun sendBroadcast(intent: Intent) {
                        super.sendBroadcast(intent)
                        context.sendBroadcast(Intent(CoreQuery.RESULT).putExtra("CORES", emptyArray<String>()),
                            null, BroadcastOptions.makeBasic().setShareIdentityEnabled(true).toBundle())
                    }
                }
                equal(CoreQuery(wrongSender).query(stub, "test_libretro_android.so"), -2, "Actual platform wrong-sender reply")
            }
            equal(bridge.checkRACoreInstalled("org.esdeplus.missing", "test_libretro_android.so"), -2, "Absent package query")
            equal(CoreQuery.reply(Intent(CoreQuery.RESULT).putExtra("CORES", emptyArray<String>()), "test_libretro_android.so", "wrong", stub, true), -2, "Wrong sender reply")
            equal(CoreQuery.reply(Intent(CoreQuery.RESULT).putExtra("CORES", emptyArray<String>()), "test_libretro_android.so", stub, stub, true), 0, "Authenticated empty reply positive control")
            val missing = RomTransport(object : ContextWrapper(context) { override fun getExternalFilesDir(type: String?): File? = null })
            refused("Unavailable selected storage") { missing.provider(rom.path) }
            return "PASS: PR-C launch/discovery/provider/query probes; assertion positive controls rejected\n" + evidence
        } finally {
            context.unregisterReceiver(receiver)
            handlerThread.quit()
            link.delete(); outside.delete(); sibling.delete(); rom.delete(); directory.delete()
            internalLink.delete(); inside.delete(); boundaryRoot.delete()
            File(StorageModel(context).appData(), "importer_temp").deleteRecursively()
        }
    }
}
