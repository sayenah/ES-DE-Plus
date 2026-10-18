// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. File-handler-only CI package, never shipped.
// Reuses ES-DE-Plus's MIT recipient implementation from android/stub-emulator.
plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "org.esdeplus.stub"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.esdeplus.handlerstub"
        minSdk = 33
        targetSdk = 36
        versionCode = 1
        versionName = "PR-I-handler-probe"
    }
    sourceSets.getByName("main").java.srcDir("../stub-emulator/src/main/kotlin")
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
androidComponents { beforeVariants(selector().withBuildType("release")) { it.enable = false } }
