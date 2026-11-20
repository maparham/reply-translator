package pro.rahkar.translate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class LocalStoreTest {
  @get:Rule val tmp = TemporaryFolder()
  private var clock = 0
  private fun history() = LocalHistory(tmp.root.resolve("h.json")) { "2026-11-20T10:00:%02dZ".format(clock++) }
  private val inputs = Inputs(1, "de", "English", "say no", "Hallo")
  private val out = Output("Hello", "Nein.", "No.")

  @Test fun savesNewestFirstAndUpdatesInPlace() {
    val h = history()
    val a = h.save(null, "Friendly", inputs, out)
    val b = h.save(null, "Official", inputs, out)
    assertEquals(listOf(b, a), h.items().map { it.id })
    h.save(a, "Official", inputs, out.copy(message = "Nein, danke."))
    val items = h.items()
    assertEquals(listOf(a, b), items.map { it.id })
    assertEquals("Nein, danke.", items[0].output.message)
    assertEquals("Official", items[0].styleLabel)
    assertEquals("2026-11-20T10:00:00Z", items[0].createdAt)
  }

  @Test fun keepsNewest100() {
    val h = history()
    repeat(105) { h.save(null, "S", inputs, out) }
    assertEquals(100, h.items().size)
  }

  @Test fun corruptFileReadsAsEmpty() {
    tmp.root.resolve("h.json").writeText("{not json")
    assertEquals(emptyList<HistoryItem>(), history().items())
  }

  @Test fun deleteAndClear() {
    val h = history()
    val a = h.save(null, "S", inputs, out); h.save(null, "S", inputs, out)
    h.delete(a)
    assertEquals(1, h.items().size)
    h.clear()
    assertTrue(h.items().isEmpty())
  }

  @Test fun importBatchesStayUnderLimit() {
    val big = Output("", "x".repeat(8000), "y".repeat(8000))
    val h = history()
    repeat(30) { h.save(null, "S", inputs, big) }
    val batches = importBatches(h.items())
    assertTrue(batches.size > 1)
    assertEquals(30, batches.sumOf { it.size })
    batches.forEach { assertTrue(json.encodeToString(mapOf("items" to it)).toByteArray().size <= 200_000) }
  }

  @Test fun myLanguageFromLocale() {
    assertEquals("Persian", myLanguageFor("fa-IR"))
    assertEquals("Ukrainian", myLanguageFor("uk"))
    assertEquals("English", myLanguageFor("de-DE"))
  }
}
