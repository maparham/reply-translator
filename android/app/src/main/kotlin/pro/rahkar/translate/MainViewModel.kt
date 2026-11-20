package pro.rahkar.translate

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.clerk.api.Clerk
import com.clerk.api.network.serialization.ClerkResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale

/** The main screen's state and logic; mirrors src/translator/static/app.js. */
class MainViewModel(app: Application) : AndroidViewModel(app) {
  val baseUrl = BuildConfig.BASE_URL
  private val api = Api(baseUrl, PrefsCookieStore(app))
  private val local = LocalHistory(app.filesDir.resolve("history.json"))
  private val prefs = app.getSharedPreferences("prefs", 0)

  var cfg by mutableStateOf<AppConfig?>(null); private set
  var user by mutableStateOf<User?>(null); private set
  var loadFailed by mutableStateOf(false); private set
  var error by mutableStateOf<String?>(null)
  var received by mutableStateOf("")
  var text by mutableStateOf("")
  var styleId by mutableStateOf<Int?>(null)
  var lang by mutableStateOf<String?>(null)
  var myLang by mutableStateOf("English")
  var noSave by mutableStateOf(false)
  var busy by mutableStateOf<String?>(null); private set // "generate", a tweak id, "signin"
  var result by mutableStateOf<Output?>(null); private set
  var resultLang by mutableStateOf("de"); private set
  val history = mutableStateListOf<HistoryItem>()
  var importCount by mutableStateOf(0); private set
  var checking by mutableStateOf(false); private set
  var checkInteractive by mutableStateOf(false); private set

  private var last: Pair<Inputs, String>? = null // inputs + style label of the shown result
  private var histId: String? = null
  private var sessionOk = false
  private var pendingCheck: CompletableDeferred<String>? = null
  private val sessionLock = Mutex()

  val usable get() = cfg?.let { it.open && it.styles.isNotEmpty() && it.languages.isNotEmpty() } == true

  init { load() }

  fun load() = viewModelScope.launch {
    loadFailed = false
    val c = try { api.config() } catch (e: ApiException) { loadFailed = true; return@launch }
    cfg = c
    user = c.user
    sessionOk = c.user != null
    val p = prefs
    styleId = p.getInt("style", -1).takeIf { id -> c.styles.any { it.id == id } } ?: c.styles.firstOrNull()?.id
    lang = p.getString("lang", null)?.takeIf { code -> c.languages.any { it.code == code } } ?: c.languages.firstOrNull()?.code
    myLang = p.getString("my", null)?.takeIf { it in c.myLanguages } ?: myLanguageFor(Locale.getDefault().toLanguageTag())
    refreshHistory()
    offerImport()
    // A Clerk session from an earlier sign-in, but no server session (expired or cleared): sign in again quietly.
    if (user == null) launch { if (clerkReady() && Clerk.session != null) exchangeClerk() }
  }

  fun savePrefs() {
    prefs.edit().putInt("style", styleId ?: -1).putString("lang", lang).putString("my", myLang).apply()
  }

  // ---------- anonymous session (Turnstile) ----------
  fun onTurnstileToken(token: String) { pendingCheck?.complete(token) }
  fun onTurnstileError(message: String) { pendingCheck?.completeExceptionally(ApiException(403, message)) }
  fun onTurnstileInteractive() { checkInteractive = true }

  private suspend fun turnstileToken(): String {
    val d = CompletableDeferred<String>()
    pendingCheck = d
    checkInteractive = false
    checking = true
    try {
      return withTimeoutOrNull(60_000) { d.await() } ?: throw ApiException(403, "Verification is taking too long, try again")
    } finally { checking = false; checkInteractive = false; pendingCheck = null }
  }

  private suspend fun ensureSession(force: Boolean = false) = sessionLock.withLock {
    if (user != null || (sessionOk && !force)) return@withLock
    val token = turnstileToken()
    // Sign-in may have finished while the check ran; an anonymous cookie must not replace the user's.
    if (user != null) return@withLock
    api.startSession(token)
    sessionOk = true
  }

  /** Runs [block] with a session; a 401 means it expired, so get a fresh one and retry once. */
  private suspend fun <T> withSession(block: suspend () -> T): T {
    ensureSession()
    return try { block() } catch (e: ApiException) {
      if (e.status != 401) throw e
      if (user != null) {
        user = null
        if (!(Clerk.session != null && exchangeClerk())) throw ApiException(401, "Please sign in again")
      } else {
        sessionOk = false
        ensureSession(force = true)
      }
      block()
    }
  }

  // ---------- generate / tweak ----------
  fun generate() = run(null)
  fun tweak(id: String) = run(id)

  private fun run(tweak: String?) {
    val c = cfg ?: return
    if (busy != null) return
    if (tweak != null && (last == null || result == null)) return
    val inputs = if (tweak != null) last!!.first else Inputs(styleId ?: return, lang ?: return, myLang, text, received)
    if (tweak == null && inputs.text.isBlank()) { error = "Please write what you want to say"; return }
    if (tweak == null) savePrefs()
    val save = !noSave
    val label = if (tweak != null) last!!.second else c.styles.firstOrNull { it.id == inputs.styleId }?.label ?: "Style"
    val req = GenerateRequest(inputs.styleId, inputs.languageCode, inputs.myLanguage, inputs.text, inputs.received, save,
      historyId = if (tweak != null) histId else null, tweak = tweak, previous = if (tweak != null) result else null)
    error = null
    busy = tweak ?: "generate"
    val asUser = user != null
    viewModelScope.launch {
      try {
        val res = withSession { api.generate(req) }
        if (tweak == null) histId = null
        last = inputs to label
        result = res.result
        resultLang = inputs.languageCode.substringBefore('-')
        if (save) {
          histId = if (asUser && res.historyId != null) res.historyId else local.save(histId, label, inputs, res.result)
          refreshHistory()
        }
      } catch (e: ApiException) { error = e.message }
      finally { busy = null }
    }
  }

  // ---------- history ----------
  private suspend fun refreshHistory() {
    val items = if (user != null) try { withSession { api.history() } } catch (e: ApiException) { error = e.message; return }
    else local.items()
    history.clear(); history.addAll(items)
  }

  fun open(item: HistoryItem) {
    val c = cfg ?: return
    received = item.inputs.received
    text = item.inputs.text
    c.styles.firstOrNull { it.label == item.styleLabel }?.let { styleId = it.id }
    if (c.languages.any { it.code == item.languageCode }) lang = item.languageCode
    if (item.inputs.myLanguage in c.myLanguages) myLang = item.inputs.myLanguage
    histId = item.id
    last = Inputs(styleId ?: return, lang ?: return, myLang, text, received) to item.styleLabel
    result = item.output
    resultLang = item.languageCode.substringBefore('-')
    error = null
  }

  fun delete(id: String) = viewModelScope.launch {
    if (user != null) try { withSession { api.deleteHistory(id) } } catch (e: ApiException) { error = e.message }
    else local.delete(id)
    if (histId == id) histId = null
    refreshHistory()
  }

  fun deleteAll() = viewModelScope.launch {
    if (user != null) try { withSession { api.deleteAllHistory() } } catch (e: ApiException) { error = e.message }
    else local.clear()
    histId = null
    refreshHistory()
  }

  private fun offerImport() { importCount = if (user != null) local.items().size else 0 }
  fun dismissImport() { importCount = 0 }

  fun importLocal() = viewModelScope.launch {
    try {
      for (batch in importBatches(local.items())) withSession { api.importHistory(batch) }
      local.clear()
      importCount = 0
      refreshHistory()
    } catch (e: ApiException) { error = e.message }
  }

  // ---------- account ----------
  private suspend fun clerkReady(): Boolean = withTimeoutOrNull(15_000) { Clerk.isInitialized.first { it } } == true

  /** Swaps the Clerk session for the server's session cookie. */
  private suspend fun exchangeClerk(): Boolean {
    val token = when (val r = Clerk.auth.getToken()) {
      is ClerkResult.Success -> r.value
      is ClerkResult.Failure -> return false
    }
    val u = sessionLock.withLock { api.loginClerk(token) }
    user = u
    sessionOk = true
    offerImport()
    refreshHistory()
    return true
  }

  fun signIn() {
    if (busy != null) return
    busy = "signin"
    error = null
    viewModelScope.launch {
      try {
        if (!clerkReady()) { error = "Sign-in is not available right now, try again"; return@launch }
        if (Clerk.session == null && !googleSignIn()) return@launch
        if (!exchangeClerk()) error = "Sign-in failed, try again"
      } catch (e: ApiException) { error = e.message }
      finally { busy = null }
    }
  }

  /**
   * Google's own account picker first; if Google refuses it (e.g. this signing key isn't registered with Google
   * yet), Clerk's browser sign-in in a Chrome tab, which only needs the website's Google login. False if it didn't
   * finish (an error is shown unless the user just closed the picker).
   */
  private suspend fun googleSignIn(): Boolean {
    val oneTap = Clerk.auth.signInWithGoogleOneTap()
    if (oneTap is ClerkResult.Success) return true
    val failure = oneTap as ClerkResult.Failure
    if (isCancel(failure)) return false
    return when (val r = Clerk.auth.signInWithOAuth(com.clerk.api.sso.OAuthProvider.GOOGLE)) {
      is ClerkResult.Success -> true
      is ClerkResult.Failure -> {
        if (!isCancel(r)) error = r.error?.errors?.firstOrNull()?.let { it.longMessage ?: it.message } ?: "Sign-in didn't finish"
        false
      }
    }
  }

  private fun isCancel(f: ClerkResult.Failure<*>): Boolean {
    val t = f.throwable
    return t is kotlinx.coroutines.CancellationException ||
      t?.javaClass?.simpleName?.contains("Cancel") == true || t?.message?.contains("cancel", ignoreCase = true) == true
  }

  fun signOut() = viewModelScope.launch {
    sessionLock.withLock {
      runCatching { api.logout() }
      runCatching { Clerk.auth.signOut() }
      user = null
      sessionOk = false
    }
    clearAfterSignOut()
  }

  /** Deletes the account and everything saved with it on the server (Google Play requires this in the app). */
  fun deleteAccount() {
    if (busy != null) return
    busy = "delete"
    viewModelScope.launch {
      try {
        sessionLock.withLock {
          api.deleteAccount()
          runCatching { Clerk.auth.signOut() }
          user = null
          sessionOk = false
        }
        clearAfterSignOut()
        error = "Your account and its history were deleted."
      } catch (e: ApiException) { error = e.message }
      finally { busy = null }
    }
  }

  private suspend fun clearAfterSignOut() {
    histId = null
    last = null
    result = null
    importCount = 0
    refreshHistory()
  }

  fun sharedText(t: String) { received = t.take(8000); result = null; error = null }
}
