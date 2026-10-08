// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus from the upstream resource and native contracts.
import java.security.MessageDigest
plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val appId = providers.gradleProperty("esde.applicationId").get()
val appVersion = providers.gradleProperty("esde.versionCode").get().toInt()
val stagedAssets = layout.buildDirectory.dir("generated/assets/frontend")
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
            "$digest\t${f.relativeTo(destination).invariantSeparatorsPath}"
        }.toList()
        destination.resolve("resource-manifest.tsv").writeText(entries.joinToString("\n", postfix = "\n"))
    }
}
android {
    namespace = "org.esdeplus.frontend"
    compileSdk = 36
    ndkVersion = "27.3.13750724"
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
                    "-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=lib")
                targets += listOf("main", "es-pdf-convert")
            }
        }
    }
    externalNativeBuild { cmake { path = file("../../CMakeLists.txt"); version = "3.31.5" } }
    sourceSets.getByName("main") {
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
    packaging { jniLibs { useLegacyPackaging = false } }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
tasks.named("preBuild") { dependsOn(stageAssets) }
