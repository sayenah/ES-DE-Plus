// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the upstream resource and native contracts.
import java.security.MessageDigest
import javax.xml.parsers.DocumentBuilderFactory
plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val appId = providers.gradleProperty("esde.applicationId").get()
val appVersion = providers.gradleProperty("esde.versionCode").get().toInt()
val stagedAssets = layout.buildDirectory.dir("generated/assets/frontend")
val queryManifest = layout.buildDirectory.file("generated/visibility/AndroidManifest.xml")
val generateQueries by tasks.registering {
    inputs.file("../../resources/systems/android/es_find_rules.xml")
    inputs.file("src/main/AndroidManifest.xml")
    outputs.file(queryManifest)
    doLast {
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder()
            .parse(file("../../resources/systems/android/es_find_rules.xml"))
        val rules = document.getElementsByTagName("rule")
        val packages = sortedSetOf<String>()
        for (i in 0 until rules.length) {
            val rule = rules.item(i) as org.w3c.dom.Element
            if (rule.getAttribute("type") != "androidpackage") continue
            val entries = rule.getElementsByTagName("entry")
            for (j in 0 until entries.length) {
                val name = entries.item(j).textContent.trim().substringBefore('/')
                require(name.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+")))
                packages.add(name)
            }
        }
        val output = queryManifest.get().asFile
        output.parentFile.mkdirs()
        val queries = """<queries>
${packages.joinToString("\n") { "<package android:name=\"$it\" />" }}
<intent><action android:name="android.intent.action.MAIN" /><category android:name="android.intent.category.LAUNCHER" /></intent>
<intent><action android:name="android.intent.action.MAIN" /><category android:name="android.intent.category.LEANBACK_LAUNCHER" /></intent>
</queries>
"""
        output.writeText(file("src/main/AndroidManifest.xml").readText().replace("<application", queries + "<application"))
    }
}
val stageAssets by tasks.registering {
    inputs.dir("../../resources")
    inputs.dir("../../locale/po")
    inputs.dir("../../themes/linear-es-de")
    inputs.dir("../branding")
    outputs.dir(stagedAssets)
    doLast {
        val destination = stagedAssets.get().asFile
        delete(destination)
        copy { from("../../resources"); into(destination) }
        copy { from("../../themes/linear-es-de"); into(destination.resolve("themes/linear-es-de")) }
        copy { from("../branding/splash.svg"); into(destination.resolve("graphics")) }
        file("../../locale/po").listFiles()!!.filter { it.extension == "po" }.sorted().forEach { po ->
            val locale = destination.resolve("locale/${po.nameWithoutExtension}/LC_MESSAGES/${po.nameWithoutExtension}.mo")
            locale.parentFile.mkdirs()
            exec { commandLine("msgfmt", "--check", "-o", locale.absolutePath, po.absolutePath) }
        }
        val entries = destination.walkTopDown().filter { it.isFile }.sortedBy { it.relativeTo(destination).invariantSeparatorsPath }.map { f ->
            val digest = MessageDigest.getInstance("SHA-256").digest(f.readBytes()).joinToString("") { "%02x".format(it) }
            "$digest\t${f.length()}\t${f.relativeTo(destination).invariantSeparatorsPath}"
        }.toList()
        destination.resolve("resource-manifest.tsv").writeText(entries.joinToString("\n", postfix = "\n"))
    }
}
android {
    namespace = "org.esdeplus.frontend"
    compileSdk = 36
    ndkVersion = "28.2.13676358"
    defaultConfig {
        applicationId = appId
        minSdk = 29
        targetSdk = 36
        versionCode = appVersion
        versionName = "slice-1"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_APPLICATION_ID=$appId", "-DANDROID_VERSION_CODE=$appVersion",
                    "-DGLES=ON", "-DANDROID_PLATFORM=android-29", "-DANDROID_STL=c++_shared",
                    "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON", "-DAPPLICATION_UPDATER=OFF",
                    "-DCMAKE_PROJECT_TOP_LEVEL_INCLUDES=${file("../native-output.cmake").absolutePath}",
                    "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384",
                    "-DCMAKE_MODULE_LINKER_FLAGS=-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384")
                targets += listOf("main", "es-pdf-convert")
            }
        }
    }
    externalNativeBuild { cmake { path = file("../../CMakeLists.txt"); version = "3.31.5" } }
    sourceSets.getByName("main") {
        manifest.srcFile(queryManifest)
        assets.srcDir(stagedAssets)
        jniLibs.srcDir("../libs")
    }
    buildFeatures { buildConfig = true }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    packaging {
        jniLibs {
            useLegacyPackaging = false
            // Install-time linker alias; all runtime consumers request libpng16.so.
            excludes += "**/libpng.so"
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
tasks.named("preBuild") { dependsOn(stageAssets, generateQueries) }

// Reviewed shipped runtime dependencies; build plugins and tools never enter dex.
tasks.register("auditRuntimeLicences") {
    doLast {
        for (variant in listOf("debug", "release")) {
            val actual = configurations.getByName("${variant}RuntimeClasspath")
                .resolvedConfiguration.resolvedArtifacts.map {
                    val id = it.moduleVersion.id
                    "${id.group}:${id.name}:${id.version}"
                }.toSet()
            val reviewed = setOf("org.jetbrains.kotlin:kotlin-stdlib:2.2.21", "org.jetbrains:annotations:13.0")
            fun verify(inputs: Set<String>) { check(inputs == reviewed) { "Unreviewed dex dependency: $inputs" } }
            verify(actual)
            try { verify(actual + "example:unreviewed:1"); error("Runtime licence control escaped") }
            catch (expected: IllegalStateException) { check(expected.message!!.startsWith("Unreviewed dex dependency:")) }
            println("PASS: $variant actual dex runtime inputs $actual; unknown dependency positive control rejected")
        }
    }
}
