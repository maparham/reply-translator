package pro.rahkar.translate

import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.encodeToString
import java.io.File
import java.time.Instant
import java.util.UUID

@Serializable data class Prefs(val style: Int? = null, val lang: String? = null, val my: String? = null)

/** History kept on the phone when nobody is signed in (newest first, like the website's localStorage list). */
class LocalHistory(private val file: File, private val now: () -> String = { Instant.now().toString() }) {
  @Synchronized fun items(): List<HistoryItem> =
    runCatching { json.decodeFromString(ListSerializer(HistoryItem.serializer()), file.readText()) }.getOrDefault(emptyList())

  /** Saves (or updates, when [id] is an existing item) and returns the item's id. */
  @Synchronized fun save(id: String?, styleLabel: String, inputs: Inputs, output: Output): String {
    val items = items()
    val existing = id?.let { i -> items.firstOrNull { it.id == i } }
    val t = now()
    val item = HistoryItem(
      id = existing?.id ?: UUID.randomUUID().toString(), createdAt = existing?.createdAt ?: t, updatedAt = t,
      styleLabel = styleLabel, languageCode = inputs.languageCode,
      inputs = HistoryInputs(inputs.text, inputs.received, inputs.myLanguage), output = output,
    )
    write((listOf(item) + items.filter { it.id != item.id }).take(MAX_ITEMS))
    return item.id
  }

  @Synchronized fun delete(id: String) = write(items().filter { it.id != id })
  @Synchronized fun clear() { file.delete() }

  private fun write(items: List<HistoryItem>) {
    val tmp = File(file.parentFile, file.name + ".tmp")
    tmp.writeText(json.encodeToString(ListSerializer(HistoryItem.serializer()), items))
    tmp.renameTo(file)
  }

  companion object { const val MAX_ITEMS = 100 }
}

/** Groups items so each /api/history/import body stays under the server's 256 KB cap (same rule as the website). */
fun importBatches(items: List<HistoryItem>, maxBytes: Int = 200_000): List<List<HistoryItem>> {
  fun size(batch: List<HistoryItem>) = json.encodeToString(mapOf("items" to batch)).toByteArray().size
  val batches = mutableListOf<List<HistoryItem>>()
  var batch = mutableListOf<HistoryItem>()
  for (item in items) {
    if (batch.isNotEmpty() && size(batch + item) > maxBytes) { batches += batch; batch = mutableListOf() }
    batch += item
  }
  if (batch.isNotEmpty()) batches += batch
  return batches
}

private val LOCALE = mapOf(
  "en" to "English", "ar" to "Arabic", "fa" to "Persian", "ps" to "Pashto", "tr" to "Turkish", "ku" to "Kurdish (Kurmanji)",
  "uk" to "Ukrainian", "ru" to "Russian", "bs" to "Bosnian/Croatian/Serbian", "hr" to "Bosnian/Croatian/Serbian",
  "sr" to "Bosnian/Croatian/Serbian", "sq" to "Albanian", "ro" to "Romanian", "bg" to "Bulgarian", "pl" to "Polish",
  "cs" to "Czech", "sk" to "Slovak", "hu" to "Hungarian", "el" to "Greek", "es" to "Spanish", "fr" to "French",
  "it" to "Italian", "pt" to "Portuguese", "hi" to "Hindi", "ur" to "Urdu", "bn" to "Bengali", "zh" to "Chinese",
  "vi" to "Vietnamese", "tl" to "Tagalog", "fil" to "Tagalog", "so" to "Somali", "ti" to "Tigrinya",
)

/** The phone's language as one of the server's "my language" names (the website's mapping). */
fun myLanguageFor(languageTag: String): String = LOCALE[languageTag.lowercase().substringBefore('-').substringBefore('_')] ?: "English"

private val SPEECH_TAGS = mapOf(
  "English" to "en-US", "Arabic" to "ar", "Persian" to "fa-IR", "Dari" to "fa-AF", "Pashto" to "ps-AF",
  "Turkish" to "tr-TR", "Kurdish (Kurmanji)" to "ku", "Ukrainian" to "uk-UA", "Russian" to "ru-RU",
  "Bosnian/Croatian/Serbian" to "hr-HR", "Albanian" to "sq-AL", "Romanian" to "ro-RO", "Bulgarian" to "bg-BG",
  "Polish" to "pl-PL", "Czech" to "cs-CZ", "Slovak" to "sk-SK", "Hungarian" to "hu-HU", "Greek" to "el-GR",
  "Spanish" to "es-ES", "French" to "fr-FR", "Italian" to "it-IT", "Portuguese" to "pt-PT", "Hindi" to "hi-IN",
  "Urdu" to "ur-PK", "Bengali" to "bn-BD", "Chinese" to "zh-CN", "Vietnamese" to "vi-VN", "Tagalog" to "fil-PH",
  "Somali" to "so-SO", "Tigrinya" to "ti-ET",
)

/** Speech-recognition language for a "my language" name; null lets the phone use its own language. */
fun speechTagFor(myLanguage: String): String? = SPEECH_TAGS[myLanguage]

/** Adds dictated text to what is already in the box, with a space between. */
fun appendDictation(current: String, spoken: String): String =
  if (current.isBlank()) spoken.trim() else current.trimEnd() + " " + spoken.trim()
