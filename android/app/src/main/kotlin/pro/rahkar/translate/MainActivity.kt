package pro.rahkar.translate

import android.app.Application
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
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

@Composable
fun AppTheme(content: @Composable () -> Unit) {
  val dark = androidx.compose.foundation.isSystemInDarkTheme()
  val ctx = LocalContext.current
  val scheme = if (android.os.Build.VERSION.SDK_INT >= 31) {
    if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
  } else if (dark) darkColorScheme() else lightColorScheme()
  MaterialTheme(colorScheme = scheme, content = content)
}

private fun copy(ctx: Context, text: String) {
  val cm = ctx.getSystemService(ClipboardManager::class.java)
  cm.setPrimaryClip(ClipData.newPlainText("Reply", text))
  if (android.os.Build.VERSION.SDK_INT < 33) Toast.makeText(ctx, "Copied", Toast.LENGTH_SHORT).show()
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
          DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(text = { Text("Sign out") }, onClick = { menu = false; vm.signOut() })
          }
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

      OutlinedTextField(vm.received, { vm.received = it.take(8000) }, Modifier.fillMaxWidth(), minLines = 3,
        label = { Text("What they wrote (optional)") }, placeholder = { Text("Paste what they wrote to you") })
      OutlinedTextField(vm.text, { vm.text = it.take(8000) }, Modifier.fillMaxWidth(), minLines = 3,
        label = { Text("What you want to say") }, placeholder = { Text("e.g. say no, I can only do Tuesday") })

      Picker("Style", cfg.styles.map { it.id to it.label }, vm.styleId) { vm.styleId = it; vm.savePrefs() }
      cfg.styles.firstOrNull { it.id == vm.styleId }?.description?.takeIf { it.isNotBlank() }?.let {
        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
      }
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.weight(1f)) { Picker("Language", cfg.languages.map { it.code to it.name }, vm.lang) { vm.lang = it; vm.savePrefs() } }
        Box(Modifier.weight(1f)) { Picker("My language", cfg.myLanguages.map { it to it }, vm.myLang) { vm.myLang = it; vm.savePrefs() } }
      }
      Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable { vm.noSave = !vm.noSave }) {
        Checkbox(vm.noSave, { vm.noSave = it }); Text("Don't save this one")
      }

      if (vm.checking) {
        TurnstileView(vm.baseUrl, vm.checkInteractive, vm::onTurnstileToken, vm::onTurnstileError, vm::onTurnstileInteractive)
      }

      Button(onClick = vm::generate, enabled = vm.usable && vm.busy == null, modifier = Modifier.fillMaxWidth()) {
        if (vm.busy == "generate") { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp); Spacer(Modifier.width(8.dp)) }
        Text("Generate")
      }
      vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

      vm.result?.let { r ->
        ElevatedCard(Modifier.fillMaxWidth()) {
          Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (r.receivedGist.isNotBlank()) Text(buildString { append("They wrote: "); append(r.receivedGist) }, style = MaterialTheme.typography.bodyMedium)
            SelectionContainer { Text(r.message, style = MaterialTheme.typography.bodyLarge) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
              Button(onClick = { copy(ctx, r.message) }, enabled = vm.busy == null) { Text("Copy") }
              OutlinedButton(onClick = { sendToWhatsApp(ctx, r.message) }) { Text("WhatsApp") }
              OutlinedButton(onClick = { share(ctx, r.message) }) { Text("Share") }
            }
            Text("Means: “${r.backTranslation}”", style = MaterialTheme.typography.bodyMedium, fontStyle = FontStyle.Italic,
              color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRowTweaks(cfg.tweaks, vm.busy, vm::tweak)
          }
        }
      }

      HistorySection(vm, ctx)
      Spacer(Modifier.height(24.dp))
    }
  }
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
      label = { Text(label) }, singleLine = true,
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
        Text("${item.styleLabel} · $lang · ${formatTime(item.updatedAt)}", style = MaterialTheme.typography.labelMedium,
          color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(item.output.message.replace(Regex("\\s+"), " "), maxLines = 2, overflow = TextOverflow.Ellipsis)
        Row {
          TextButton(onClick = { copy(ctx, item.output.message) }) { Text("Copy") }
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
