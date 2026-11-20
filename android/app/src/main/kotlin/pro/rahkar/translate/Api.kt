package pro.rahkar.translate

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.encodeToString
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val status: Int, message: String) : Exception(message)

val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }

/** Keeps the server's session cookie across app restarts. */
interface CookieStore { fun load(): String?; fun save(value: String?) }

class PrefsCookieStore(context: Context) : CookieStore {
  private val prefs = context.getSharedPreferences("session", Context.MODE_PRIVATE)
  override fun load(): String? = prefs.getString("cookie", null)
  override fun save(value: String?) { prefs.edit().apply { if (value == null) remove("cookie") else putString("cookie", value) }.apply() }
}

/** Holds only the app's own session cookie (tr_session); everything else is ignored. */
class SessionCookieJar(private val store: CookieStore) : CookieJar {
  @Volatile private var cookie: Cookie? = null
  private var loaded = false

  @Synchronized private fun current(url: HttpUrl): Cookie? {
    if (!loaded) {
      loaded = true
      cookie = store.load()?.let { Cookie.parse(url, it) }
    }
    return cookie?.takeIf { it.expiresAt > System.currentTimeMillis() }
  }

  @Synchronized override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
    val c = cookies.lastOrNull { it.name == COOKIE } ?: return
    loaded = true
    if (c.expiresAt <= System.currentTimeMillis()) { cookie = null; store.save(null) }
    else { cookie = c; store.save(c.toString()) }
  }

  override fun loadForRequest(url: HttpUrl): List<Cookie> = listOfNotNull(current(url)?.takeIf { it.matches(url) })

  @Synchronized fun clear() { cookie = null; loaded = true; store.save(null) }

  companion object { const val COOKIE = "tr_session" }
}

class Api(private val baseUrl: String, cookieStore: CookieStore, client: OkHttpClient? = null) {
  val cookies = SessionCookieJar(cookieStore)
  private val http = (client ?: OkHttpClient()).newBuilder()
    .cookieJar(cookies)
    .connectTimeout(15, TimeUnit.SECONDS)
    .readTimeout(90, TimeUnit.SECONDS) // a generation can take a while
    .build()
  private val origin = baseUrl.trimEnd('/')
  private val jsonType = "application/json".toMediaType()

  private suspend fun call(method: String, path: String, body: String? = null): String = withContext(Dispatchers.IO) {
    val req = Request.Builder().url(origin + path)
      // The server rejects state-changing /api/ calls whose Origin isn't the site (CSRF guard for browsers).
      .header("Origin", origin)
      .method(method, body?.toRequestBody(jsonType) ?: if (method == "GET") null else "".toRequestBody(jsonType))
      .build()
    val resp = try { http.newCall(req).execute() } catch (e: IOException) {
      throw ApiException(0, "No connection, check your internet and try again")
    }
    resp.use {
      val text = it.body.string()
      if (!it.isSuccessful) throw ApiException(it.code, errorMessage(text))
      text
    }
  }

  private fun errorMessage(text: String): String =
    runCatching { json.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.contentOrNull }.getOrNull()
      ?: "Something went wrong, try again"

  suspend fun config(): AppConfig = json.decodeFromString(call("GET", "/api/config"))

  suspend fun startSession(turnstileToken: String) {
    call("POST", "/api/session", buildJsonObject { put("turnstile_token", turnstileToken) }.toString())
  }

  suspend fun loginClerk(token: String): User =
    json.decodeFromString(call("POST", "/api/login/clerk", buildJsonObject { put("token", token) }.toString()))

  suspend fun logout() { try { call("POST", "/api/logout", "{}") } finally { cookies.clear() } }

  suspend fun generate(req: GenerateRequest): GenerateResponse =
    json.decodeFromString(call("POST", if (req.tweak != null) "/api/tweak" else "/api/generate", json.encodeToString(req)))

  suspend fun deleteAccount() { call("DELETE", "/api/account"); cookies.clear() }

  suspend fun history(): List<HistoryItem> = json.decodeFromString(call("GET", "/api/history"))

  suspend fun deleteHistory(id: String) { call("DELETE", "/api/history/" + java.net.URLEncoder.encode(id, "UTF-8").replace("+", "%20")) }

  suspend fun deleteAllHistory() { call("DELETE", "/api/history") }

  suspend fun importHistory(items: List<HistoryItem>): Int {
    val body = json.encodeToString(mapOf("items" to items))
    return json.parseToJsonElement(call("POST", "/api/history/import", body)).jsonObject["imported"]?.jsonPrimitive?.int ?: 0
  }
}
