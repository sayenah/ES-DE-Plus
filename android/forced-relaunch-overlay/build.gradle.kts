// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus. Resource-only CI overlay, never shipped.
plugins { id("com.android.application") }
android {
    namespace = "org.esdeplus.relaunchprobe"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.esdeplus.relaunchprobe"
        minSdk = 31
        targetSdk = 36
        versionCode = 1
        versionName = "WO-18-probe"
        manifestPlaceholders["frontendId"] = providers.gradleProperty("esde.applicationId").get()
    }
}
androidComponents { beforeVariants(selector().withBuildType("release")) { it.enable = false } }
