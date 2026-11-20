# kotlinx.serialization keeps generated serializers via its bundled rules; keep the JS bridge methods.
-keepclassmembers class pro.rahkar.translate.TurnstileBridge { @android.webkit.JavascriptInterface <methods>; }
