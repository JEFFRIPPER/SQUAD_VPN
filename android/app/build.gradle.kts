plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// CI passes -PversionCode=<run number>; local builds stay at 1.
val buildNumber = (findProperty("versionCode") as String?)?.toIntOrNull() ?: 1
// The user-facing version lives in android/version.properties; builds differ by versionCode.
val appVersion = rootProject.file("version.properties").readLines()
    .firstOrNull { it.startsWith("VERSION_NAME=") }?.substringAfter('=')?.trim() ?: "1.0"

android {
    namespace = "com.squad.vpn"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.squad.vpn"
        minSdk = 26
        targetSdk = 35
        versionCode = buildNumber
        versionName = appVersion
        buildConfigField("String", "REPO", "\"JEFFRIPPER/SQUAD_VPN\"")
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    // The release key is not in the repo. CI decodes it from the repository
    // secret SQUAD_KEYSTORE_B64 into a file and passes its path and password;
    // without them release builds stop instead of signing with another key.
    val keystore = System.getenv("SQUAD_KEYSTORE")?.takeIf { it.isNotBlank() }
    signingConfigs {
        if (keystore != null) {
            create("release") {
                storeFile = file(keystore)
                storeType = "pkcs12"
                storePassword = System.getenv("SQUAD_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("SQUAD_KEY_ALIAS") ?: "squad"
                keyPassword = System.getenv("SQUAD_KEY_PASSWORD") ?: System.getenv("SQUAD_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        // Local debug builds use the standard Android debug key.
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    // libv2ray.aar (Xray core) is downloaded by CI from AndroidLibXrayLite releases.
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))

    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.animation:animation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
