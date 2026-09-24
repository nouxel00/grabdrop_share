import java.net.URI
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "io.github.nouxel00.grabdrop"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.nouxel00.grabdrop"
        minSdk = 29
        targetSdk = 35
        versionCode = 3
        versionName = "0.3.0"
        ndk {
            // Téléphones récents (ARM 64 bits) et émulateur : divise la taille de l'APK par deux.
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")  // usage personnel : APK installable directement
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
    }
    androidResources {
        noCompress += "task"  // MediaPipe lit le modèle directement dans l'APK
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.08.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.2")
    implementation("androidx.lifecycle:lifecycle-process:2.9.2")

    implementation("androidx.camera:camera-camera2:1.4.2")
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    implementation("androidx.camera:camera-view:1.4.2")
    implementation("com.google.mediapipe:tasks-vision:1.0.0")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")

    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    testImplementation("junit:junit:4.13.2")
}

tasks.withType<Test>().configureEach {
    systemProperty("grabdrop.repo", rootDir.parentFile.absolutePath)  // pour InteropTest (code Python des PC)
}

// Modèle de gestes MediaPipe (le même que sur PC), téléchargé une fois à la compilation.
val downloadGestureModel by tasks.registering {
    val model = file("src/main/assets/gesture_recognizer.task")
    outputs.file(model)
    doLast {
        if (!model.exists()) {
            model.parentFile.mkdirs()
            val url = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
            logger.lifecycle("Téléchargement du modèle de gestes MediaPipe…")
            URI(url).toURL().openStream().use { input -> model.outputStream().use { output -> input.copyTo(output) } }
        }
    }
}
tasks.named("preBuild") { dependsOn(downloadGestureModel) }
