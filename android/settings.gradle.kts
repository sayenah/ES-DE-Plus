// SPDX-License-Identifier: MIT
// ES-DE-Plus — written for ES-DE-Plus.
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "ES-DE-Plus-Android"
include(":app")
