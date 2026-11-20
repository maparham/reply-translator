package pro.rahkar.translate

import android.app.Application
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.TextStyle
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.background
import androidx.compose.ui.zIndex
import androidx.compose.ui.unit.sp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.withStyle
import com.clerk.api.Clerk
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

class App : Application() {
  override fun onCreate() {
    super.onCreate()
    Clerk.initialize(this, BuildConfig.CLERK_PUBLISHABLE_KEY)
  }
}

class MainActivity : ComponentActivity() {
  private val vm: MainViewModel by viewModels()

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    enableEdgeToEdge()
    if (savedInstanceState == null) handleShare(intent)
    setContent { AppTheme { MainScreen(vm) } }
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    handleShare(intent)
  }

  /** Text shared from another app (WhatsApp, mail…) becomes "what they wrote". */
  private fun handleShare(intent: Intent?) {
    if (intent?.action == Intent.ACTION_SEND && intent.type?.startsWith("text/") == true) {
      intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.isNotBlank() }?.let(vm::sharedText)
    }
  }
}

/** White fields with a quiet border that turns ink blue when focused, as on the website. */
@Composable
fun paperFieldColors() = OutlinedTextFieldDefaults.colors(
  focusedContainerColor = Palette.Paper, unfocusedContainerColor = Palette.Paper, disabledContainerColor = Palette.Paper,
  unfocusedBorderColor = Palette.Line, focusedBorderColor = Palette.InkBlue,
)

/** The website's palette: cool office grey, white paper, blue-black ink; post yellow only on Generate. */
object Palette {
  val Bg = Color(0xFFEDF0F3)
  val Paper = Color(0xFFFFFFFF)
  val Ink = Color(0xFF1B2535)
  val InkBlue = Color(0xFF2A4A7B)
  val Muted = Color(0xFF5E6B7D)
  val Line = Color(0xFFCCD4DE)
  val Stamp = Color(0xFFFFCC00)
  val Carbon = Color(0xFFE1E8F0)
  val Danger = Color(0xFFB3261E)
}

// Atkinson Hyperlegible Next (variable): built so letters can't be mistaken, for second-language readers.
@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
private fun atkinson(weight: Int) = androidx.compose.ui.text.font.Font(
  R.font.atkinson_next, FontWeight(weight),
  variationSettings = androidx.compose.ui.text.font.FontVariation.Settings(androidx.compose.ui.text.font.FontVariation.weight(weight)),
)
private val Atkinson = androidx.compose.ui.text.font.FontFamily(atkinson(400), atkinson(600), atkinson(700))

@Composable
fun AppTheme(content: @Composable () -> Unit) {
  val scheme = lightColorScheme(
    primary = Palette.InkBlue, onPrimary = Color.White, secondary = Palette.InkBlue,
    background = Palette.Bg, onBackground = Palette.Ink, surface = Palette.Bg, onSurface = Palette.Ink,
    surfaceVariant = Palette.Carbon, onSurfaceVariant = Palette.Muted, outline = Palette.Line, outlineVariant = Palette.Line,
    surfaceContainer = Palette.Paper, surfaceContainerHigh = Palette.Paper, surfaceContainerLow = Palette.Paper,
    surfaceContainerHighest = Palette.Paper, surfaceContainerLowest = Palette.Paper,
    error = Palette.Danger, primaryContainer = Palette.Carbon, onPrimaryContainer = Palette.Ink,
  )
  val base = Typography()
  fun TextStyle.a() = copy(fontFamily = Atkinson)
  val type = Typography(
    displayLarge = base.displayLarge.a(), displayMedium = base.displayMedium.a(), displaySmall = base.displaySmall.a(),
    headlineLarge = base.headlineLarge.a(), headlineMedium = base.headlineMedium.a(), headlineSmall = base.headlineSmall.a(),
    titleLarge = base.titleLarge.a().copy(fontWeight = FontWeight.Bold), titleMedium = base.titleMedium.a(), titleSmall = base.titleSmall.a(),
    bodyLarge = base.bodyLarge.a(), bodyMedium = base.bodyMedium.a(), bodySmall = base.bodySmall.a(),
    labelLarge = base.labelLarge.a().copy(fontWeight = FontWeight.Bold), labelMedium = base.labelMedium.a(), labelSmall = base.labelSmall.a(),
  )
  MaterialTheme(colorScheme = scheme, typography = type, content = content)
}

private fun copy(ctx: Context, text: String) {
  ctx.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Reply", text))
}

/** Copy button that shows "Copied ✓" (or a check mark, as an icon) for a moment after a tap, on every Android version. */
@Composable
private fun CopyButton(text: String, icon: Boolean, enabled: Boolean = true) {
  val ctx = LocalContext.current
  var copiedAt by remember { mutableStateOf(0L) }
  LaunchedEffect(copiedAt) { if (copiedAt != 0L) { kotlinx.coroutines.delay(1800); copiedAt = 0L } }
  val copied = copiedAt != 0L
  val onClick = { copy(ctx, text); copiedAt = System.currentTimeMillis() }
  if (icon) ActionIcon(if (copied) R.drawable.ic_check else R.drawable.ic_copy, if (copied) "Copied" else "Copy",
    enabled = enabled, highlighted = copied, onClick = onClick)
  else TextButton(onClick = onClick, enabled = enabled) { Text(if (copied) "Copied ✓" else "Copy") }
}

/** A round outlined icon button for the reply's actions. */
@Composable
private fun ActionIcon(
  res: Int, description: String, enabled: Boolean = true, highlighted: Boolean = false,
  tint: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.primary, onClick: () -> Unit,
) {
  if (highlighted) FilledIconButton(onClick = onClick, enabled = enabled) {
    Icon(androidx.compose.ui.res.painterResource(res), contentDescription = description)
  } else OutlinedIconButton(onClick = onClick, enabled = enabled) {
    Icon(androidx.compose.ui.res.painterResource(res), contentDescription = description, tint = tint)
  }
}

private fun sendToWhatsApp(ctx: Context, text: String) {
  val direct = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text).setPackage("com.whatsapp")
  try { ctx.startActivity(direct) } catch (_: ActivityNotFoundException) {
    ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/?text=" + Uri.encode(text))))
  }
}

private fun share(ctx: Context, text: String) {
  ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), null))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(vm: MainViewModel) {
  val ctx = LocalContext.current
  val cfg = vm.cfg
  Scaffold(
    topBar = {
      TopAppBar(title = { Text("Reply Translator") }, actions = {
        val u = vm.user
        if (u != null) {
          var menu by remember { mutableStateOf(false) }
          TextButton(onClick = { menu = true }) { Text(u.email, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 180.dp)) }
          var confirmDelete by remember { mutableStateOf(false) }
          DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(text = { Text("Sign out") }, onClick = { menu = false; vm.signOut() })
            DropdownMenuItem(text = { Text("Delete account", color = MaterialTheme.colorScheme.error) },
              onClick = { menu = false; confirmDelete = true })
          }
          if (confirmDelete) AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete your account?") },
            text = { Text("This deletes ${u.email} and all history saved to it. It cannot be undone.") },
            confirmButton = { TextButton(onClick = { confirmDelete = false; vm.deleteAccount() }) {
              Text("Delete", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
          )
        } else if (cfg?.clerkPublishableKey != null) {
          TextButton(onClick = vm::signIn, enabled = vm.busy == null) { Text(if (vm.busy == "signin") "Signing in…" else "Sign in") }
        }
      })
    },
  ) { pad ->
    Column(
      Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).imePadding(),
      verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
      if (cfg == null) {
        if (vm.loadFailed) {
          Text("Could not load the app. Check your connection.")
          Button(onClick = { vm.load() }) { Text("Try again") }
        } else Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return@Column
      }
      if (!cfg.open) Notice("Temporarily unavailable. Please try again later.")
      if (vm.importCount > 0) {
        Card {
          Column(Modifier.padding(12.dp)) {
            Text("Move ${vm.importCount} item${if (vm.importCount == 1) "" else "s"} from this phone to your account?")
            Row { TextButton(onClick = { vm.importLocal() }) { Text("Move") }; TextButton(onClick = vm::dismissImport) { Text("Not now") } }
          }
        }
      }

      InputField(vm.text, { vm.text = it }, "What you want to say", "Any language, e.g. say no, I can only do Tuesday",
        voiceLanguage = vm.myLang)
      // Optional, so it starts as one line and grows with what is pasted.
      InputField(vm.received, { vm.received = it }, "What they wrote (optional)", "Paste what they wrote to you", minLines = 1)

      // From: the language you write in (Auto = detect it); summaries and the "Means" check come in it. To: the reply.
      Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f)) {
          Picker("From", cfg.myLanguages.map { it to if (it == "Auto") "Auto-detect" else it }, vm.myLang) { vm.myLang = it; vm.savePrefs() }
        }
        Text("→", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box(Modifier.weight(1f)) { Picker("To", cfg.languages.map { it.code to it.name }, vm.lang) { vm.lang = it; vm.savePrefs() } }
      }
      Picker("Style", cfg.styles.map { it.id to it.label }, vm.styleId) { vm.styleId = it; vm.savePrefs() }
      cfg.styles.firstOrNull { it.id == vm.styleId }?.description?.takeIf { it.isNotBlank() }?.let {
        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
      }
      Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable { vm.noSave = !vm.noSave }) {
        Checkbox(vm.noSave, { vm.noSave = it }); Text("Don't save this one")
      }

      if (vm.checking) {
        TurnstileView(vm.baseUrl, vm.checkInteractive, vm::onTurnstileToken, vm::onTurnstileError, vm::onTurnstileInteractive)
      }

      // The one loud thing, as on the website: post yellow with ink text.
      Button(onClick = vm::generate, enabled = vm.usable && vm.busy == null, modifier = Modifier.fillMaxWidth().height(56.dp),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Palette.Stamp, contentColor = Palette.Ink,
          disabledContainerColor = Color(0xFFDFE4EA), disabledContentColor = Color(0xFF8994A3))) {
        if (vm.busy == "generate") { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Palette.Ink); Spacer(Modifier.width(10.dp)) }
        Text("Generate", fontSize = 18.sp, fontWeight = FontWeight.Bold)
      }
      vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

      vm.result?.let { r ->
        // The sendable letter on a white sheet, with its carbon copy in your language tucked underneath.
        Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
          if (r.receivedGist.isNotBlank()) Text(
            androidx.compose.ui.text.buildAnnotatedString {
              withStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold, color = Palette.Ink)) { append("They wrote: ") }
              append(r.receivedGist)
            }, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted, modifier = Modifier.padding(start = 4.dp, bottom = 10.dp))
          Surface(color = Palette.Paper, shape = RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp, bottomStart = 12.dp, bottomEnd = 12.dp),
            shadowElevation = 3.dp, modifier = Modifier.fillMaxWidth().zIndex(1f)) {
            Column {
              Box(Modifier.fillMaxWidth().height(4.dp).background(Palette.Ink))
              Column(Modifier.padding(start = 20.dp, end = 12.dp, top = 18.dp, bottom = 10.dp)) {
                SelectionContainer { Text(r.message, fontSize = 19.sp, lineHeight = 29.sp) }
                Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.End)) {
                  CopyButton(r.message, icon = true, enabled = vm.busy == null)
                  ActionIcon(R.drawable.ic_whatsapp, "Send with WhatsApp", tint = Color(0xFF1E9E52)) { sendToWhatsApp(ctx, r.message) }
                  ActionIcon(R.drawable.ic_share, "Share") { share(ctx, r.message) }
                }
              }
            }
          }
          Surface(color = Palette.Carbon, shape = RoundedCornerShape(bottomStart = 12.dp, bottomEnd = 12.dp),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 12.dp)) {
              Text("What it says", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = Palette.Muted)
              Text("“${r.backTranslation}”", style = MaterialTheme.typography.bodyMedium, color = Palette.Ink)
            }
          }
          Spacer(Modifier.height(14.dp))
          FlowRowTweaks(cfg.tweaks, vm.busy, vm::tweak)
        }
      }

      HistorySection(vm, ctx)
      TextButton(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(vm.baseUrl + "/privacy"))) },
        modifier = Modifier.align(Alignment.CenterHorizontally)) {
        Text("Privacy policy", style = MaterialTheme.typography.bodySmall)
      }
      Spacer(Modifier.height(24.dp))
    }
  }
}

private const val MAX_CHARS = 8000

private fun clipboardText(ctx: Context): String? =
  ctx.getSystemService(ClipboardManager::class.java).primaryClip
    ?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.toString()?.takeIf { it.isNotBlank() }

/**
 * A text box with buttons inside: Paste when it's empty, ✕ (clear) when it has text, and with [voiceLanguage]
 * a 🎤 that adds dictated text (the phone's speech input, listening in that language).
 */
@Composable
private fun InputField(
  value: String, onChange: (String) -> Unit, label: String, placeholder: String,
  voiceLanguage: String? = null, minLines: Int = 3,
) {
  val ctx = LocalContext.current
  val currentValue by rememberUpdatedState(value)
  val dictate = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
    val spoken = r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
    if (r.resultCode == android.app.Activity.RESULT_OK && !spoken.isNullOrBlank()) {
      onChange(appendDictation(currentValue, spoken).take(MAX_CHARS))
    }
  }
  OutlinedTextField(
    value, { onChange(it.take(MAX_CHARS)) }, Modifier.fillMaxWidth(), minLines = minLines, maxLines = 12,
    label = { Text(label) }, placeholder = { Text(placeholder) }, colors = paperFieldColors(), shape = RoundedCornerShape(12.dp),
    trailingIcon = { Row(verticalAlignment = Alignment.CenterVertically) {
      if (voiceLanguage != null) {
        IconButton(onClick = {
          val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PROMPT, "Say what you want to answer")
          speechTagFor(voiceLanguage)?.let { intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, it) }
          try { dictate.launch(intent) } catch (_: ActivityNotFoundException) {
            Toast.makeText(ctx, "Voice typing isn't available on this phone", Toast.LENGTH_SHORT).show()
          }
        }) { Icon(androidx.compose.ui.res.painterResource(R.drawable.ic_mic), contentDescription = "Voice typing", tint = Palette.InkBlue) }
      }
      if (value.isEmpty()) {
        TextButton(onClick = {
          val t = clipboardText(ctx)
          if (t != null) onChange(t.trim().take(MAX_CHARS))
          else Toast.makeText(ctx, "Nothing to paste. Copy a text first.", Toast.LENGTH_SHORT).show()
        }) { Text("Paste") }
      } else {
        IconButton(onClick = { onChange("") }) { Text("✕", style = MaterialTheme.typography.titleMedium) }
      }
    } },
  )
}

@Composable
private fun Notice(text: String) {
  Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium) {
    Text(text, Modifier.padding(12.dp).fillMaxWidth())
  }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FlowRowTweaks(tweaks: List<Tweak>, busy: String?, onTweak: (String) -> Unit) {
  FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    tweaks.forEach { t ->
      AssistChip(onClick = { onTweak(t.id) }, enabled = busy == null,
        label = { Text(if (busy == t.id) "${t.label}…" else t.label) })
    }
  }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun <T> Picker(label: String, options: List<Pair<T, String>>, selected: T?, onSelect: (T) -> Unit) {
  var open by remember { mutableStateOf(false) }
  ExposedDropdownMenuBox(open, { open = it }) {
    OutlinedTextField(
      value = options.firstOrNull { it.first == selected }?.second ?: "", onValueChange = {}, readOnly = true,
      label = { Text(label) }, singleLine = true, colors = paperFieldColors(), shape = RoundedCornerShape(12.dp),
      trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
      modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
    )
    ExposedDropdownMenu(open, { open = false }) {
      options.forEach { (value, text) -> DropdownMenuItem(text = { Text(text) }, onClick = { onSelect(value); open = false }) }
    }
  }
}

private val dateFormat = DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT)
private fun formatTime(iso: String) = runCatching { dateFormat.format(Instant.parse(iso).atZone(ZoneId.systemDefault())) }.getOrDefault(iso)

@Composable
private fun HistorySection(vm: MainViewModel, ctx: Context) {
  var open by rememberSaveable { mutableStateOf(false) }
  var confirm by remember { mutableStateOf(false) }
  HorizontalDivider()
  TextButton(onClick = { open = !open }) {
    Text("${if (open) "▾" else "▸"} History${if (vm.history.isNotEmpty()) " (${vm.history.size})" else ""}")
  }
  if (!open) return
  if (vm.user == null) Text("Saved on this phone only. Sign in to keep it across devices.", style = MaterialTheme.typography.bodySmall)
  if (vm.history.isEmpty()) Text("Nothing here yet.", style = MaterialTheme.typography.bodySmall)
  val languages = vm.cfg?.languages.orEmpty()
  vm.history.forEach { item ->
    Card(Modifier.fillMaxWidth().clickable { vm.open(item) }) {
      Column(Modifier.padding(12.dp)) {
        val lang = languages.firstOrNull { it.code == item.languageCode }?.name ?: item.languageCode
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
          Text("${item.styleLabel}, $lang", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
          Text(formatTime(item.updatedAt), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(item.output.message.replace(Regex("\\s+"), " "), maxLines = 2, overflow = TextOverflow.Ellipsis)
        Row {
          CopyButton(item.output.message, icon = false)
          TextButton(onClick = { vm.delete(item.id) }) { Text("Delete", color = MaterialTheme.colorScheme.error) }
        }
      }
    }
  }
  if (vm.history.isNotEmpty()) TextButton(onClick = { confirm = true }) { Text("Delete all", color = MaterialTheme.colorScheme.error) }
  if (confirm) AlertDialog(
    onDismissRequest = { confirm = false },
    title = { Text("Delete all history?") },
    confirmButton = { TextButton(onClick = { confirm = false; vm.deleteAll() }) { Text("Delete all") } },
    dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
  )
}
