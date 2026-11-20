package pro.rahkar.translate

import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ApiTest {
  private val server = MockWebServer()
  private val store = object : CookieStore { var v: String? = null; override fun load() = v; override fun save(value: String?) { v = value } }
  private lateinit var api: Api

  @Before fun setUp() { server.start(); api = Api(server.url("/").toString(), store) }
  @After fun tearDown() { server.close() }

  @Test fun sendsOriginAndKeepsSessionCookie() = runTest {
    server.enqueue(MockResponse.Builder().addHeader("Set-Cookie", "tr_session=abc; Path=/; Max-Age=3600; HttpOnly").body("{\"ok\":true}").build())
    server.enqueue(MockResponse.Builder().body("[]").build())
    api.startSession("tok")
    val first = server.takeRequest()
    assertEquals(server.url("/").toString().trimEnd('/'), first.headers["Origin"])
    assertEquals("{\"turnstile_token\":\"tok\"}", first.body?.utf8())
    assertEquals(true, store.v?.startsWith("tr_session=abc"))
    // A fresh client (app restart) reads the stored cookie.
    Api(server.url("/").toString(), store).history()
    assertEquals("tr_session=abc", server.takeRequest().headers["Cookie"])
  }

  @Test fun generateRequestShape() = runTest {
    server.enqueue(MockResponse.Builder().body("{\"result\":{\"received_gist\":\"\",\"message\":\"Nein.\",\"back_translation\":\"No.\"},\"history_id\":null}").build())
    val r = api.generate(GenerateRequest(2, "de", "English", "say no", "", save = true))
    assertEquals("Nein.", r.result.message)
    assertNull(r.historyId)
    val req = server.takeRequest()
    assertEquals("/api/generate", req.url.encodedPath)
    assertEquals("{\"style_id\":2,\"language_code\":\"de\",\"my_language\":\"English\",\"text\":\"say no\",\"received\":\"\",\"save\":true}", req.body?.utf8())
  }

  @Test fun tweakGoesToTweakEndpoint() = runTest {
    server.enqueue(MockResponse.Builder().body("{\"result\":{\"message\":\"m\",\"back_translation\":\"b\"}}").build())
    api.generate(GenerateRequest(2, "de", "English", "t", "", true, "h1", "shorter", Output("", "a", "b")))
    val req = server.takeRequest()
    assertEquals("/api/tweak", req.url.encodedPath)
    assertEquals(true, req.body?.utf8()?.contains("\"previous\":{\"received_gist\":\"\",\"message\":\"a\",\"back_translation\":\"b\"}"))
  }

  @Test fun serverErrorMessageSurfaces() = runTest {
    server.enqueue(MockResponse.Builder().code(503).body("{\"error\":\"Temporarily unavailable\"}").build())
    try { api.history(); fail() } catch (e: ApiException) {
      assertEquals(503, e.status); assertEquals("Temporarily unavailable", e.message)
    }
  }

  @Test fun logoutClearsCookieEvenOnFailure() = runTest {
    store.v = "tr_session=abc; Path=/"
    server.enqueue(MockResponse.Builder().code(500).build())
    runCatching { api.logout() }
    assertNull(store.v)
  }

  @Test fun deleteAccountCallsEndpointAndForgetsCookie() = runTest {
    store.v = "tr_session=abc; Path=/"
    server.enqueue(MockResponse.Builder().body("{\"ok\":true}").build())
    api.deleteAccount()
    val req = server.takeRequest()
    assertEquals("DELETE", req.method)
    assertEquals("/api/account", req.url.encodedPath)
    assertNull(store.v)
  }
}
