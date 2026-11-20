package pro.rahkar.translate

import android.annotation.SuppressLint
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView

/** Receives calls from /static/app-check.js (window.ReplyApp); they arrive on a WebView thread. */
class TurnstileBridge(
  private val allowedHost: String,
  private val webView: () -> WebView?,
  private val tokenHandler: (String) -> Unit,
  private val errorHandler: (String) -> Unit,
  private val interactiveHandler: () -> Unit,
) {
  private val main = Handler(Looper.getMainLooper())

  // Only the app's own check page may talk to the app.
  private fun fromOurPage(block: () -> Unit) = main.post {
    if (webView()?.url?.let { Uri.parse(it).host } == allowedHost) block()
  }

  @JavascriptInterface fun onToken(token: String) { fromOurPage { tokenHandler(token) } }
  @JavascriptInterface fun onError(message: String) { fromOurPage { errorHandler(message) } }
  @JavascriptInterface fun onInteractive(@Suppress("UNUSED_PARAMETER") ignored: String) { fromOurPage { interactiveHandler() } }
}

/** The web view that runs Turnstile on translate.rahkar.pro. 1 dp tall unless Turnstile wants a click. */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun TurnstileView(baseUrl: String, interactive: Boolean, onToken: (String) -> Unit, onError: (String) -> Unit, onInteractive: () -> Unit) {
  val host = Uri.parse(baseUrl).host!!
  AndroidView(
    modifier = Modifier.fillMaxWidth().height(if (interactive) 140.dp else 1.dp),
    factory = { ctx ->
      WebView(ctx).apply {
        var self: WebView? = null
        self = this
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        webViewClient = object : WebViewClient() {
          // Stay on our page; Turnstile's own iframe loads aren't navigations of this frame.
          override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = request.url.host != host
        }
        addJavascriptInterface(TurnstileBridge(host, { self }, onToken, onError, onInteractive), "ReplyApp")
        loadUrl("$baseUrl/app-check")
      }
    },
    onRelease = { it.destroy() },
  )
}
