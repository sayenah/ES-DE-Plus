// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Separate-UID CI recipient, never shipped.
plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "org.esdeplus.stub"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.esdeplus.stub"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "PR-C-probe"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
androidComponents { beforeVariants(selector().withBuildType("release")) { it.enable = false } }
