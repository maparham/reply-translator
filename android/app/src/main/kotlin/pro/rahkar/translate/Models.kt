package pro.rahkar.translate

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName

@Serializable data class Style(val id: Int, val label: String, val description: String = "")
@Serializable data class Language(val code: String, val name: String)
@Serializable data class Tweak(val id: String, val label: String)
@Serializable data class User(val email: String, @SerialName("is_admin") val isAdmin: Boolean = false)

@Serializable
data class AppConfig(
  val open: Boolean,
  @SerialName("turnstile_site_key") val turnstileSiteKey: String? = null,
  @SerialName("clerk_publishable_key") val clerkPublishableKey: String? = null,
  val styles: List<Style> = emptyList(),
  val languages: List<Language> = emptyList(),
  @SerialName("my_languages") val myLanguages: List<String> = emptyList(),
  val tweaks: List<Tweak> = emptyList(),
  val user: User? = null,
)

@Serializable
data class Output(
  @SerialName("received_gist") val receivedGist: String = "",
  val message: String,
  @SerialName("back_translation") val backTranslation: String,
)

/** What the user filled in; the same fields the website sends. */
@Serializable
data class Inputs(
  @SerialName("style_id") val styleId: Int,
  @SerialName("language_code") val languageCode: String,
  @SerialName("my_language") val myLanguage: String,
  val text: String,
  val received: String,
)

@Serializable
data class GenerateRequest(
  @SerialName("style_id") val styleId: Int,
  @SerialName("language_code") val languageCode: String,
  @SerialName("my_language") val myLanguage: String,
  val text: String,
  val received: String,
  val save: Boolean,
  @SerialName("history_id") val historyId: String? = null,
  val tweak: String? = null,
  val previous: Output? = null,
)

@Serializable
data class GenerateResponse(val result: Output, @SerialName("history_id") val historyId: String? = null)

@Serializable
data class HistoryInputs(val text: String = "", val received: String = "", @SerialName("my_language") val myLanguage: String = "")

/** One history entry; the same shape as the website's local history and the server's /api/history items. */
@Serializable
data class HistoryItem(
  val id: String,
  @SerialName("created_at") val createdAt: String,
  @SerialName("updated_at") val updatedAt: String,
  @SerialName("style_label") val styleLabel: String,
  @SerialName("language_code") val languageCode: String,
  val inputs: HistoryInputs,
  val output: Output,
)
