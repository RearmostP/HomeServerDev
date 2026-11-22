plugins {
    id("com.android.application") version "9.5.0"
}

android {
    namespace = "il.homegallery"
    compileSdk = 37

    defaultConfig {
        applicationId = "il.homegallery"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets.named("main") {
        kotlin.directories.add("../network/src/main/kotlin")
        kotlin.directories.add("../server-api/src/main/kotlin")
        assets.directories.add("../server-api/src/main/assets")
    }
}

val browser = rootProject.layout.projectDirectory.dir("../browser")
val localServerHost = rootProject.layout.projectDirectory.file("server-host.local.txt")
abstract class PrepareGalleryAssets : Sync() {
    @get:OutputDirectory
    abstract val assetsDirectory: DirectoryProperty
}

val galleryAssets = tasks.register<PrepareGalleryAssets>("galleryAssets") {
    assetsDirectory.set(layout.buildDirectory.dir("generated/galleryAssets"))
    from(browser) {
        include("index.html")
        filter { line: String ->
            if (line.contains("src=\"/app.js\"")) {
                "  <script src=\"/android-transport.js\"></script>\n" + line
            } else line
        }
    }
    from(browser.file("dist/app.js"))
    from(browser.file("app.css"))
    from(localServerHost) { rename { "server-host.txt" } }
    into(assetsDirectory)
    doFirst {
        val config = localServerHost.asFile
        check(config.isFile && Regex("[a-z0-9-]+[.][a-z0-9-]+[.]ts[.]net").matches(config.readText().trim())) {
            "Create clients/android/server-host.local.txt with the server hostname, without https://."
        }
        check(browser.file("dist/app.js").asFile.isFile) {
            "Build clients/browser with npm ci and npm run build first."
        }
    }
}
androidComponents.onVariants { variant ->
    variant.sources.assets?.addGeneratedSourceDirectory(galleryAssets, PrepareGalleryAssets::assetsDirectory)
}
tasks.named("preBuild") {
    doFirst {
        check(rootProject.file("network/libs/tailbridge.aar").isFile) {
            "Build network/libs/tailbridge.aar with network/build.ps1 first."
        }
    }
}

dependencies {
    implementation(files("../network/libs/tailbridge.aar"))
}
