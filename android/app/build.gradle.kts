import java.util.Properties

plugins {
  alias(libs.plugins.android.application)
  alias(libs.plugins.kotlin.compose)
  alias(libs.plugins.kotlin.serialization)
}

// Release signing comes from android/keystore.properties (git-ignored), pointing at a keystore outside the repo.
val keystoreProps = Properties().apply {
  val f = rootProject.file("keystore.properties")
  if (f.exists()) f.inputStream().use { load(it) }
}

android {
  namespace = "pro.rahkar.translate"
  compileSdk = 36

  defaultConfig {
    applicationId = "pro.rahkar.translate"
    minSdk = 26
    targetSdk = 36
    versionCode = 6
    versionName = "1.3.0"
    buildConfigField("String", "BASE_URL", "\"https://translate.rahkar.pro\"")
    // Public key (it is in every page of the website too).
    buildConfigField("String", "CLERK_PUBLISHABLE_KEY", "\"pk_live_Y2xlcmsudHJhbnNsYXRlLnJhaGthci5wcm8k\"")
  }

  signingConfigs {
    if (keystoreProps.isNotEmpty()) {
      create("release") {
        storeFile = file(keystoreProps.getProperty("storeFile"))
        storePassword = keystoreProps.getProperty("storePassword")
        keyAlias = keystoreProps.getProperty("keyAlias")
        keyPassword = keystoreProps.getProperty("keyPassword")
      }
    }
  }

  buildTypes {
    release {
      isMinifyEnabled = true
      proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
      signingConfig = signingConfigs.findByName("release")
    }
  }

  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
  }

  buildFeatures {
    compose = true
    buildConfig = true
  }
}

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
  implementation(platform(libs.compose.bom))
  implementation(libs.compose.ui)
  implementation(libs.compose.material3)
  implementation(libs.activity.compose)
  implementation(libs.lifecycle.viewmodel.compose)
  implementation(libs.lifecycle.runtime.compose)
  implementation(libs.okhttp)
  implementation(libs.serialization.json)
  implementation(libs.coroutines.android)
  implementation(libs.clerk)
  testImplementation(libs.junit)
  testImplementation(libs.okhttp.mockwebserver)
  testImplementation(libs.coroutines.test)
}
