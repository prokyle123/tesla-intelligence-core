package com.ghost.tesla.mobile;

import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.graphics.Insets;
import android.net.Uri;
import android.text.TextUtils;
import android.view.*;
import android.webkit.*;
import android.widget.*;

import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

public class MainActivity extends Activity {
    static final String VER = "0.8.1";

    WebView web;
    TextView status;
    TextView detail;
    LinearLayout root;
    LinearLayout navPanel;
    SharedPreferences prefs;
    ConnectorManager connector;
    final Handler ui = new Handler(Looper.getMainLooper());

    String local = "";
    String tail = "";
    String pub = "";
    String active = null;
    String kind = "OFFLINE";
    String view = "morning";
    String navSelection = "home";
    String lastGoodKind = "";
    String lastGoodUrl = "";

    String dl = "not tested";
    String dt = "not tested";
    String dpb = "not tested";
    String lastJsError = "";
    String lastSyncReport = "not run";
    boolean dashboardReady = false;
    final Map<String, TextView> navButtons = new LinkedHashMap<>();

    boolean map = false;
    boolean firstRunScanActive = false;
    long pausedAt = 0L;

    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        connector = new ConnectorManager();
        prefs = getSharedPreferences("ghost", MODE_PRIVATE);

        local = ConnectorManager.normalize(prefs.getString("local", prefs.getString("primary", "")));
        tail = ConnectorManager.normalize(prefs.getString("private", prefs.getString("backup", "")));
        pub = ConnectorManager.normalize(prefs.getString("public", ""));
        lastGoodKind = prefs.getString("last_good_kind", "");
        lastGoodUrl = ConnectorManager.normalize(prefs.getString("last_good_url", ""));

        Intent launch = getIntent();
        if (launch != null) {
            String x = launch.getStringExtra("tic_local");
            if (x != null && !x.trim().isEmpty()) local = ConnectorManager.normalize(x);
            x = launch.getStringExtra("tic_tailnet");
            if (x != null && !x.trim().isEmpty()) tail = ConnectorManager.normalize(x);
            x = launch.getStringExtra("tic_public");
            if (x != null && !x.trim().isEmpty()) pub = ConnectorManager.normalize(x);
            x = launch.getStringExtra("tic_view");
            if (x != null && !x.trim().isEmpty()) view = x.trim();
        }
        navSelection = navKeyForView(view);

        build();
        bars();

        if (launch != null && launch.getBooleanExtra("tic_settings", false)) {
            welcome("Connection Center requested.");
            ui.postDelayed(() -> settings(false), 250);
        } else if (!any()) {
            welcome("Searching the local network for Tesla Intelligence Core…");
            ui.postDelayed(this::firstRunDiscovery, 350);
        } else {
            resolve();
        }
    }

    void bars() {
        getWindow().setStatusBarColor(Color.rgb(4, 19, 28));
        getWindow().setNavigationBarColor(Color.rgb(4, 19, 28));
        if (Build.VERSION.SDK_INT >= 29) getWindow().setNavigationBarContrastEnforced(false);

        try {
            if (Build.VERSION.SDK_INT >= 30) {
                // Keep app content inside the normal Android system-bar area.
                // This prevents the phone navigation/gesture region from overlapping companion controls.
                getWindow().setDecorFitsSystemWindows(true);
                WindowInsetsController c = getWindow().getInsetsController();
                if (c != null) {
                    c.show(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                    c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_DEFAULT);
                }
            } else {
                getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
            }
        } catch (Exception ignored) {
        }
    }

    void applySafeInsets(View v) {
        // v0.8.0 uses decorFitsSystemWindows(true), so Android owns the safe-area layout.
    }

    @Override protected void onResume() {
        super.onResume();
        bars();
        if (pausedAt > 0 && System.currentTimeMillis() - pausedAt > 180000 && any()) resolve();
    }

    @Override protected void onPause() {
        pausedAt = System.currentTimeMillis();
        super.onPause();
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) {
            bars();
        }
    }

    int d(int n) {
        return Math.round(n * getResources().getDisplayMetrics().density);
    }

    boolean any() {
        return !local.isEmpty() || !tail.isEmpty() || !pub.isEmpty();
    }

    String shortUrl(String s) {
        if (s == null || s.isEmpty()) return "—";
        return s.replace("http://", "").replace("https://", "");
    }

    String dash(String s) {
        return s == null || s.isEmpty() ? "—" : s;
    }

    String esc(String s) {
        return s == null ? "" : s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    TextView button(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextColor(Color.rgb(220, 246, 255));
        v.setGravity(Gravity.CENTER);
        v.setTextSize(11);
        v.setPadding(d(8), 0, d(8), 0);
        v.setBackgroundColor(Color.rgb(7, 30, 42));
        return v;
    }

    TextView label(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextColor(Color.rgb(106, 175, 202));
        v.setTextSize(10);
        v.setPadding(0, d(10), 0, d(3));
        return v;
    }

    void build() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(4, 19, 28));
        applySafeInsets(root);

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setPadding(d(8), d(4), d(8), d(4));
        top.setBackgroundColor(Color.rgb(5, 24, 34));

        LinearLayout topRow = new LinearLayout(this);
        topRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText("TESLA INTELLIGENCE CORE");
        title.setTextColor(Color.WHITE);
        title.setTextSize(13);
        title.setTypeface(null, 1);
        title.setSingleLine(true);
        title.setEllipsize(TextUtils.TruncateAt.END);
        topRow.addView(title, new LinearLayout.LayoutParams(0, d(34), 1));

        status = button("OFFLINE");
        status.setTextSize(10);
        status.setOnClickListener(v -> diagnostics());
        topRow.addView(status, new LinearLayout.LayoutParams(d(84), d(32)));

        LinearLayout routeRow = new LinearLayout(this);
        routeRow.setGravity(Gravity.CENTER_VERTICAL);

        detail = new TextView(this);
        detail.setText("Companion v" + VER);
        detail.setTextColor(Color.rgb(105, 160, 184));
        detail.setTextSize(9);
        detail.setGravity(Gravity.CENTER_VERTICAL);
        detail.setSingleLine(true);
        detail.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        detail.setPadding(0, 0, d(6), 0);
        routeRow.addView(detail, new LinearLayout.LayoutParams(0, d(32), 1));

        TextView connect = button("RETRY");
        connect.setTextSize(9);
        connect.setOnClickListener(v -> resolve());
        routeRow.addView(connect, new LinearLayout.LayoutParams(d(62), d(30)));

        TextView set = button("SETUP");
        set.setTextSize(9);
        set.setOnClickListener(v -> settings(false));
        routeRow.addView(set, new LinearLayout.LayoutParams(d(62), d(30)));

        top.addView(topRow, new LinearLayout.LayoutParams(-1, d(34)));
        top.addView(routeRow, new LinearLayout.LayoutParams(-1, d(32)));
        root.addView(top, new LinearLayout.LayoutParams(-1, d(74)));

        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        ws.setBuiltInZoomControls(true);
        ws.setDisplayZoomControls(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        ws.setUserAgentString(ws.getUserAgentString() + " TIC-Companion/" + VER);
        if (Build.VERSION.SDK_INT >= 26) ws.setSafeBrowsingEnabled(true);

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        web.setBackgroundColor(Color.rgb(4, 19, 28));

        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onReceivedTitle(WebView v, String title) {
                if (title == null) return;
                String low = title.toLowerCase();
                if (low.contains("ghost access") || low.contains("pin") || low.contains("login") || low.contains("gateway")) {
                    status.setText("LOGIN");
                    detail.setText("PIN gateway • enter PIN");
                }
            }

            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if (message != null && message.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    lastJsError = "L" + message.lineNumber() + " • " + message.message();
                    ui.post(() -> {
                        if (!"LOGIN".contentEquals(status.getText())) {
                            detail.setText("Dashboard JS • " + lastJsError);
                        }
                    });
                }
                return true;
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView v, String url, android.graphics.Bitmap favicon) {
                if (url != null && url.contains("/__ghost_auth/")) {
                    status.setText("LOGIN");
                    detail.setText("PIN gateway • enter PIN");
                } else {
                    status.setText("VERIFY");
                    detail.setText(kind + " • checking dashboard data…");
                }
            }

            @Override public void onPageFinished(WebView v, String url) {
                if (url != null && url.contains("/__ghost_auth/")) {
                    status.setText("LOGIN");
                    detail.setText("PIN gateway • enter PIN");
                    return;
                }
                ensureCompanionWebNav();
                verifyWebViewData();
            }

            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                Uri u = request == null ? null : request.getUrl();
                if (u != null && "tic".equalsIgnoreCase(u.getScheme())) {
                    handleCompanionLink(u.toString());
                    return true;
                }
                return false;
            }

            @Override public boolean shouldOverrideUrlLoading(WebView v, String url) {
                if (url != null && url.toLowerCase().startsWith("tic://")) {
                    handleCompanionLink(url);
                    return true;
                }
                return false;
            }

            @Override public void onReceivedError(WebView v, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    status.setText("ERROR");
                    detail.setText(kind + " • WebView error " + error.getErrorCode());
                }
            }
        });

        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));

        navPanel = new LinearLayout(this);
        navPanel.setOrientation(LinearLayout.VERTICAL);
        navPanel.setBackgroundColor(Color.rgb(5, 24, 34));
        navPanel.setPadding(d(4), d(3), d(4), d(3));
        navPanel.setClickable(true);
        navPanel.setFocusable(true);
        if (Build.VERSION.SDK_INT >= 21) navPanel.setElevation(d(24));

        if (Build.VERSION.SDK_INT >= 21) {
            navPanel.setOnApplyWindowInsetsListener((v, insets) -> {
                int bottomInset;
                if (Build.VERSION.SDK_INT >= 30) {
                    Insets navInsets = insets.getInsets(WindowInsets.Type.navigationBars());
                    Insets gestureInsets = insets.getInsets(WindowInsets.Type.mandatorySystemGestures());
                    bottomInset = Math.max(navInsets.bottom, gestureInsets.bottom);
                } else {
                    bottomInset = insets.getSystemWindowInsetBottom();
                }

                v.setPadding(d(4), d(3), d(4), d(3) + bottomInset);
                ViewGroup.LayoutParams lp = v.getLayoutParams();
                if (lp != null) {
                    lp.height = d(102) + bottomInset;
                    v.setLayoutParams(lp);
                }
                return insets;
            });
        }

        LinearLayout row1 = new LinearLayout(this);
        row1.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);

        String[][] navItems = {
                {"HOME", "home", "1"},
                {"READY", "ready", "1"},
                {"EVENTS", "events", "1"},
                {"NEURAL", "neural", "1"},
                {"TRUTH", "truth", "2"},
                {"THERMAL", "thermal", "2"},
                {"MORE", "more", "2"}
        };

        for (String[] item : navItems) {
            Button b = new Button(this);
            b.setText(item[0]);
            b.setAllCaps(false);
            b.setTextSize(10);
            b.setTextColor(Color.rgb(220, 246, 255));
            b.setBackgroundColor(Color.rgb(7, 30, 42));
            b.setMinWidth(0);
            b.setMinimumWidth(0);
            b.setMinHeight(0);
            b.setMinimumHeight(0);
            b.setPadding(d(3), 0, d(3), 0);
            b.setClickable(false); // Activity-level hit testing handles taps before children/WebView.
            b.setFocusable(false);
            if (!"more".equals(item[1])) navButtons.put(item[1], b);

            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, d(44), 1);
            lp.setMargins(d(2), d(2), d(2), d(2));
            if ("1".equals(item[2])) row1.addView(b, lp);
            else row2.addView(b, lp);
        }

        navPanel.addView(row1, new LinearLayout.LayoutParams(-1, d(48)));
        navPanel.addView(row2, new LinearLayout.LayoutParams(-1, d(48)));
        root.addView(navPanel, new LinearLayout.LayoutParams(-1, d(102)));
        updateNativeNav();

        setContentView(root);
        bars();
        navPanel.requestApplyInsets();
    }

    String navKeyForView(String target) {
        if ("morning".equals(target) || "home".equals(target)) return "home";
        if ("events".equals(target)) return "events";
        if ("neural4".equals(target) || "neural".equals(target)) return "neural";
        if ("truth".equals(target)) return "truth";
        if ("thermal".equals(target)) return "thermal";
        return "more";
    }

    String viewUrl(String target, String focus) {
        String base = ConnectorManager.normalize(active);
        if (base.isEmpty()) return "";
        StringBuilder u = new StringBuilder(base)
                .append("/?companion=1&view=")
                .append(Uri.encode(target == null || target.isEmpty() ? "morning" : target));
        if (focus != null && !focus.isEmpty()) {
            u.append("&focus=").append(Uri.encode(focus));
        }
        return u.toString();
    }

    void select(String target) {
        navSelection = navKeyForView(target);
        view = target;
        map = false;
        updateNativeNav();

        if (active == null || active.isEmpty()) {
            detail.setText("Connect to the dashboard first");
            return;
        }

        status.setText(kind);
        detail.setText(kind + " • " + target.toUpperCase());
        setWebNavActive(navSelection);
        switchCurrentWebView(target, "");
    }

    void navigateTo(String key, String target, String focus) {
        navSelection = key;
        view = target;
        map = false;
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        updateNativeNav();

        if (active == null || active.isEmpty()) {
            detail.setText("Connect to the dashboard first");
            return;
        }

        dashboardReady = false;
        status.setText(kind);

        String label = "morning".equals(target) && "readiness".equals(focus)
                ? "WINTER READINESS"
                : ("morning".equals(target) ? "HOME" : target.toUpperCase());

        detail.setText(kind + " • OPENING " + label);

        String url = viewUrl(target, focus);
        if (!url.isEmpty()) {
            web.stopLoading();
            web.loadUrl(url);
        }
    }

    void updateNativeNav() {
        for (Map.Entry<String, TextView> e : navButtons.entrySet()) {
            boolean selected = e.getKey().equals(navSelection) && !map;
            TextView b = e.getValue();
            b.setBackgroundColor(selected ? Color.rgb(13, 92, 122) : Color.rgb(7, 30, 42));
            b.setTextColor(selected ? Color.WHITE : Color.rgb(177, 222, 238));
            b.setTypeface(null, selected ? 1 : 0);
            b.setAlpha(selected ? 1.0f : 0.90f);
        }
    }

    void more() {
        String[] labels = {
                "AI LAB",
                "MODELS",
                "DATA QUALITY",
                "SOURCES",
                "PRODUCTION",
                "HISTORY",
                "NEURAL MAP",
                "CONNECTION CENTER",
                "TESLA BROWSER ACCESS",
                "CONNECTION DIAGNOSTICS"
        };
        String[] acts = {
                "overview",
                "models",
                "quality",
                "sources",
                "production",
                "history",
                "map",
                "setup",
                "browser",
                "diag"
        };

        new AlertDialog.Builder(this)
                .setTitle("Tesla Intelligence Core")
                .setItems(labels, (dialog, which) -> {
                    String action = acts[which];
                    if ("map".equals(action)) openMap();
                    else if ("setup".equals(action)) settings(false);
                    else if ("browser".equals(action)) browserInfo();
                    else if ("diag".equals(action)) diagnostics();
                    else select(action);
                })
                .setNegativeButton("CLOSE", null)
                .show();
    }

    void openMap() {
        view = "neural4";
        navSelection = "neural";
        map = true;
        updateNativeNav();
        setWebNavActive("neural");
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);

        if (active != null && !active.isEmpty()) {
            dashboardReady = false;
            switchCurrentWebView("neural4", "");
            ui.postDelayed(this::applyCompanionCss, 180);
        }
    }

    void ensureCompanionWebNav() {
        // Native v0.8.0 navigation is authoritative. Do not inject a second web navigation layer.
    }

    void setWebNavActive(String key) {
        updateNativeNav();
    }

    void handleCompanionLink(String raw) {
        Uri u;
        try { u = Uri.parse(raw); } catch (Exception e) { return; }
        if (u == null || !"tic".equalsIgnoreCase(u.getScheme())) return;

        String host = u.getHost() == null ? "" : u.getHost().toLowerCase();
        String path = u.getPath() == null ? "" : u.getPath().replaceFirst("^/", "").toLowerCase();

        if ("more".equals(host)) {
            detail.setText(kind + " • opening menu…");
            more();
            return;
        }

        if (!"view".equals(host)) return;

        String key = path;
        String target;
        String focus = "";

        switch (key) {
            case "home":
                target = "morning";
                break;
            case "ready":
                target = "morning";
                focus = "readiness";
                break;
            case "events":
                target = "events";
                break;
            case "neural":
                target = "neural4";
                break;
            case "truth":
                target = "truth";
                break;
            case "thermal":
                target = "thermal";
                break;
            default:
                return;
        }

        navSelection = key;
        view = target;
        map = false;
        setWebNavActive(key);

        String label = "ready".equals(key) ? "WINTER READINESS" : key.toUpperCase();
        status.setText(kind);
        detail.setText(kind + " • " + label);

        switchCurrentWebView(target, focus);
    }

    void switchCurrentWebView(String target, String focus) {
        String safeTarget = target == null ? "morning" : target.replace("'", "");
        String safeFocus = focus == null ? "" : focus.replace("'", "");

        String js =
                "(function(){" +
                "var n='" + safeTarget + "';" +
                "var id='view-'+n;" +
                "var target=document.getElementById(id);" +
                "if(!target)return 'MISSING:'+id;" +
                "try{" +
                "document.querySelectorAll('.view').forEach(function(v){" +
                "v.classList.toggle('active',v===target);" +
                "v.style.setProperty('display',v===target?'block':'none','important');" +
                "});" +
                "document.querySelectorAll('.tab').forEach(function(t){" +
                "t.classList.toggle('active',t.getAttribute('data-view')===n);" +
                "});" +
                "target.style.setProperty('display','block','important');" +
                "target.style.setProperty('visibility','visible','important');" +
                "target.style.setProperty('opacity','1','important');" +
                ("readiness".equals(safeFocus)
                        ? "setTimeout(function(){var e=document.querySelector('.winter-ready-hero');if(e)e.scrollIntoView({block:'start',behavior:'auto'});},50);"
                        : "window.scrollTo({top:0,left:0,behavior:'auto'});") +
                "var cs=getComputedStyle(target);" +
                "var visible=(cs.display!=='none'&&cs.visibility!=='hidden'&&target.offsetHeight>0);" +
                "return (visible?'VISIBLE:':'HIDDEN:')+id+':'+Math.round(target.offsetHeight);" +
                "}catch(e){return 'ERROR:'+e;}" +
                "})()";

        web.evaluateJavascript(js, value -> {
            String result = cleanJsValue(value);
            lastSyncReport = "NAV " + result;

            if (result.startsWith("VISIBLE:")) {
                status.setText(kind);
                String label = "readiness".equals(safeFocus)
                        ? "WINTER READINESS"
                        : ("morning".equals(safeTarget) ? "HOME" : safeTarget.toUpperCase());
                detail.setText(kind + " • " + label + " • VISIBLE");
            } else {
                lastJsError = "nav • " + result;
                detail.setText(kind + " • " + result);
            }
        });
    }

    void firstRunDiscovery() {
        if (firstRunScanActive) return;
        firstRunScanActive = true;
        status.setText("SCAN");
        detail.setText("Searching local network…");

        final boolean[] found = {false};

        connector.scanLocalNetwork(new ConnectorManager.ScanListener() {
            @Override public void onProgress(String message) {
                ui.post(() -> detail.setText(message));
            }

            @Override public void onFound(String url, String message) {
                found[0] = true;
                ui.post(() -> {
                    local = ConnectorManager.normalize(url);
                    saveEndpoints();
                    Toast.makeText(MainActivity.this, "Found Tesla Intelligence Core: " + shortUrl(local), Toast.LENGTH_LONG).show();
                    resolve();
                });
            }

            @Override public void onFinished(boolean didFind) {
                ui.post(() -> {
                    firstRunScanActive = false;
                    if (!didFind && !found[0]) {
                        status.setText("SETUP");
                        detail.setText("Automatic scan did not find the Pi");
                        settings(true);
                    }
                });
            }
        });
    }

    void resolve() {
        connector.cancelScan();

        if (!any()) {
            status.setText("SETUP");
            detail.setText("No dashboard endpoints configured");
            settings(true);
            return;
        }

        status.setText("CONNECT");
        detail.setText("Testing Local / Tailnet / Public…");

        connector.connect(local, tail, pub, new ConnectorManager.ConnectListener() {
            @Override public void onProgress(String message) {
                ui.post(() -> detail.setText(message));
            }

            @Override public void onComplete(ConnectorManager.EndpointResult winner, List<ConnectorManager.EndpointResult> results) {
                ui.post(() -> {
                    for (ConnectorManager.EndpointResult r : results) {
                        if ("LOCAL".equals(r.kind)) dl = r.detail;
                        else if ("TAILNET".equals(r.kind)) dt = r.detail;
                        else if ("PUBLIC".equals(r.kind)) dpb = r.detail;
                    }

                    if (winner != null) {
                        if (winner.authRequired) {
                            rememberWinner("PUBLIC", winner.base);
                            loadAuth(winner.base);
                        } else {
                            rememberWinner(winner.kind, winner.base);
                            load(winner.base, winner.kind);
                        }
                    } else {
                        active = null;
                        kind = "OFFLINE";
                        status.setText("OFFLINE");
                        detail.setText("No configured path answered • tap OFFLINE");
                        offline();
                    }
                });
            }
        });
    }

    void rememberWinner(String k, String base) {
        lastGoodKind = k;
        lastGoodUrl = ConnectorManager.normalize(base);
        prefs.edit()
                .putString("last_good_kind", lastGoodKind)
                .putString("last_good_url", lastGoodUrl)
                .apply();
    }

    void load(String base, String k) {
        active = ConnectorManager.normalize(base);
        kind = k;
        dashboardReady = false;
        status.setText("VERIFY");
        detail.setText(k + " • checking dashboard data…");
        String focus = "ready".equals(navSelection) ? "readiness" : "";
        String url = viewUrl(view, focus);
        web.loadUrl(url.isEmpty() ? active + "/" : url);
    }

    void loadAuth(String base) {
        active = ConnectorManager.normalize(base);
        kind = "PUBLIC";
        dashboardReady = false;
        status.setText("LOGIN");
        detail.setText("PIN gateway • enter PIN");
        String focus = "ready".equals(navSelection) ? "readiness" : "";
        String url = viewUrl(view, focus);
        web.loadUrl(url.isEmpty() ? active + "/" : url);
    }

    void verifyWebViewData() {
        if (active == null || active.isEmpty()) return;

        String js =
                "(function(){" +
                "var r=document.documentElement;" +
                "r.setAttribute('data-tic-api','CHECKING');" +
                "fetch('/api/v3/overview',{cache:'no-store',credentials:'include'})" +
                ".then(function(x){return x.text().then(function(t){" +
                "var ok=(x.status===200&&t&&t.trim().charAt(0)==='{'&&(t.indexOf('\\\"readiness\\\"')>=0||t.indexOf('\\\"events\\\"')>=0||t.indexOf('\\\"version\\\"')>=0));" +
                "if(ok){r.setAttribute('data-tic-api','DATA_OK');}" +
                "else if(x.status===401){r.setAttribute('data-tic-api','AUTH');}" +
                "else{r.setAttribute('data-tic-api','HTTP_'+x.status);}" +
                "});})" +
                ".catch(function(e){r.setAttribute('data-tic-api','ERROR');});" +
                "})()";

        web.evaluateJavascript(js, null);

        ui.postDelayed(() -> web.evaluateJavascript(
                "(function(){return document.documentElement.getAttribute('data-tic-api')||'UNKNOWN';})()",
                value -> {
                    String state = value == null ? "UNKNOWN" : value.replace("\\", "").replace("\"", "").trim();

                    if ("DATA_OK".equals(state)) {
                        status.setText(kind);
                        detail.setText(kind + " • " + shortUrl(active) + " • API OK");
                        forceDashboardRefresh();
                        return;
                    }

                    if ("AUTH".equals(state)) {
                        kind = "PUBLIC";
                        status.setText("LOGIN");
                        detail.setText("PIN gateway • enter PIN");
                        return;
                    }

                    if ("CHECKING".equals(state) || "UNKNOWN".equals(state)) {
                        ui.postDelayed(this::verifyWebViewData, 700);
                        return;
                    }

                    status.setText("NO DATA");
                    detail.setText(kind + " • dashboard API " + state);
                }
        ), 850);
    }

    void forceDashboardRefresh() {
        if (active == null || active.isEmpty()) return;

        String js =
                "(function(){" +
                "var root=document.documentElement;" +
                "root.setAttribute('data-tic-sync','RUNNING');" +
                "(async function(){" +
                "var report=[];" +
                "try{" +
                "var r=await fetch('/api/status',{cache:'no-store',credentials:'include'});" +
                "report.push('status:'+r.status);" +
                "if(r.ok){var d=await r.json();window.DATA=d;if(typeof render==='function'){render(d);report.push('core:rendered');}else{report.push('core:renderer-missing');}}" +
                "}catch(e){report.push('status:error');}" +
                "try{" +
                "var a=await fetch('/api/v3/overview',{cache:'no-store',credentials:'include'});" +
                "report.push('v3:'+a.status);" +
                "if(a.ok&&typeof renderV3==='function'){renderV3(await a.json());report.push('v3:rendered');}" +
                "}catch(e){report.push('v3:error');}" +
                "try{" +
                "var b=await fetch('/api/v3/events?limit=80',{cache:'no-store',credentials:'include'});" +
                "report.push('events:'+b.status);" +
                "if(b.ok&&typeof renderEventRows==='function'){renderEventRows(await b.json());report.push('events:rendered');}" +
                "}catch(e){report.push('events:error');}" +
                "try{" +
                "var c=await fetch('/api/v3/winter',{cache:'no-store',credentials:'include'});" +
                "report.push('winter:'+c.status);" +
                "if(c.ok&&typeof renderWinterBoard==='function'){renderWinterBoard(await c.json());report.push('winter:rendered');}" +
                "}catch(e){report.push('winter:error');}" +
                "try{if(typeof refreshNeuralV4==='function'){await refreshNeuralV4();report.push('neural:refreshed');}else{report.push('neural:missing');}}catch(e){report.push('neural:error');}" +
                "root.setAttribute('data-tic-sync',report.join('|'));" +
                "})().catch(function(){root.setAttribute('data-tic-sync','sync:error');});" +
                "return 'STARTED';" +
                "})()";

        web.evaluateJavascript(js, null);
        ui.postDelayed(this::checkDashboardSync, 900);
    }

    void checkDashboardSync() {
        if (active == null || active.isEmpty()) return;

        web.evaluateJavascript(
                "(function(){return document.documentElement.getAttribute('data-tic-sync')||'UNKNOWN';})()",
                value -> {
                    String report = cleanJsValue(value);
                    lastSyncReport = report;

                    if ("RUNNING".equals(report) || "UNKNOWN".equals(report)) {
                        ui.postDelayed(this::checkDashboardSync, 650);
                        return;
                    }

                    boolean rendered = report.contains("core:rendered")
                            || report.contains("v3:rendered")
                            || report.contains("winter:rendered")
                            || report.contains("events:rendered");

                    dashboardReady = rendered;
                    status.setText(kind);

                    if (rendered) {
                        detail.setText(kind + " • " + shortUrl(active) + " • LIVE");
                    } else {
                        detail.setText(kind + " • " + shortUrl(active) + " • API LIVE");
                    }

                    ensureCompanionWebNav();
                    setWebNavActive(navSelection);
                    ui.postDelayed(this::applyCompanionCss, 250);
                }
        );
    }

    String cleanJsValue(String value) {
        if (value == null) return "";
        String out = value.trim();
        if (out.length() >= 2 && out.startsWith("\"") && out.endsWith("\"")) {
            out = out.substring(1, out.length() - 1);
        }
        return out.replace("\\\\", "\\").replace("\\\"", "\"");
    }

    void openAnyway(String base, String k) {
        String n = ConnectorManager.normalize(base);
        if (n.isEmpty()) {
            Toast.makeText(this, "That endpoint is blank.", Toast.LENGTH_SHORT).show();
            return;
        }
        rememberWinner(k, n);
        load(n, k);
    }

    void welcome(String message) {
        String html =
                "<body style='margin:0;background:#04131c;color:#dff6ff;font-family:sans-serif;padding:28px'>" +
                "<div style='max-width:760px;margin:auto'>" +
                "<h2 style='color:#fff'>Tesla Intelligence Core Companion</h2>" +
                "<p>" + esc(message) + "</p>" +
                "<p style='color:#81b7cf'>The companion can use Local LAN, private Tailscale, or an optional public HTTPS / PIN gateway.</p>" +
                "</div></body>";

        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
    }

    void offline() {
        String html =
                "<body style='margin:0;background:#04131c;color:#dff6ff;font-family:sans-serif;padding:28px'>" +
                "<h2>Dashboard unavailable</h2>" +
                "<p><b>Local</b><br>" + esc(local) + "<br><small>" + esc(dl) + "</small></p>" +
                "<p><b>Tailnet</b><br>" + esc(tail) + "<br><small>" + esc(dt) + "</small></p>" +
                "<p><b>Public / Funnel</b><br>" + esc(pub) + "<br><small>" + esc(dpb) + "</small></p>" +
                "<p>Tap <b>OFFLINE</b> for diagnostics or <b>SETUP</b> to open the Connection Center.</p>" +
                "</body>";

        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
    }

    String mapJs() {
        return "function ticFixMap(){var s=document.getElementById('n4NetworkMap'),h=document.getElementById('n4MapShell');if(!s||!h)return;" +
                "s.setAttribute('preserveAspectRatio','xMidYMid meet');var v=s.viewBox&&s.viewBox.baseVal?s.viewBox.baseVal:null;if(v&&v.width>0&&v.height>0)s.style.setProperty('aspect-ratio',v.width+' / '+v.height,'important');}" +
                "ticFixMap();var s=document.getElementById('n4NetworkMap');if(s&&!s.__ticObserver){s.__ticObserver=new MutationObserver(function(){ticFixMap();});s.__ticObserver.observe(s,{attributes:true,attributeFilter:['preserveAspectRatio','viewBox']});}" +
                "if(!window.__ticTimer)window.__ticTimer=setInterval(ticFixMap,1000);";
    }

    void applyCompanionCss() {
        if (active == null || active.isEmpty()) return;

        String css = map ?
                "var st=document.getElementById('ticMapStyle');if(st)st.remove();st=document.createElement('style');st.id='ticMapStyle';st.textContent='header.topbar,.neural-v4-hero,.neural-v4-kpis,.n6-governor,.neural-dev>.section-title,.n4-live-narrative,.n4-mission-strip,.n4-runtime-strip,.neural-progress-card,.n4-insight-strip,.n4-observatory-strip{display:none!important}main{padding:0!important;max-width:none!important;width:100%!important}.neural-dev{margin:0!important;padding:0!important;border:0!important}#n4MapShell{height:100vh!important;min-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important}#n4NetworkMap{width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important;display:block!important}';document.head.appendChild(st);" :
                "var st=document.getElementById('ticMapStyle');if(st)st.remove();st=document.createElement('style');st.id='ticMapStyle';st.textContent='.navrow,#ticCompanionNav,#ticInjectedNav,#ticCompanionMore{display:none!important}body{padding-bottom:0!important}#n4MapShell{height:auto!important;min-height:0!important}#n4NetworkMap{width:100%!important;height:auto!important;max-width:100%!important;display:block!important}';document.head.appendChild(st);";

        String js =
                "(function(){" +
                css +
                mapJs() +
                (map
                        ? "setTimeout(function(){ticFixMap();var m=document.getElementById('n4MapShell');if(m)m.scrollIntoView({block:'start'});},120);"
                        : "setTimeout(ticFixMap,120);") +
                "})()";

        web.evaluateJavascript(js, null);
    }

    void apply() {
        applyCompanionCss();
    }

    void diagnostics() {
        String message =
                "ACTIVE\n" + kind + " • " + dash(active) +
                "\n\nLAST GOOD\n" + dash(lastGoodKind) + " • " + dash(lastGoodUrl) +
                "\n\nLOCAL\n" + dash(local) + "\n" + dl +
                "\n\nTAILNET\n" + dash(tail) + "\n" + dt +
                "\n\nPUBLIC / FUNNEL\n" + dash(pub) + "\n" + dpb +
                "\n\nDASHBOARD\nview " + view.toUpperCase() + " • " + (dashboardReady ? "rendered" : "API connected") +
                "\nSync: " + lastSyncReport +
                "\n\nJAVASCRIPT\n" + (lastJsError.isEmpty() ? "no captured console errors" : lastJsError) +
                "\n\nConnection order is Local → Tailnet → Public. Probes run in parallel and the most-private successful route wins.";

        AlertDialog.Builder b = new AlertDialog.Builder(this)
                .setTitle("Connection diagnostics")
                .setMessage(message)
                .setPositiveButton("RETEST", (dialog, which) -> resolve())
                .setNeutralButton("SETUP", (dialog, which) -> settings(false))
                .setNegativeButton("CLOSE", null);

        b.show();
    }

    EditText field(String hint, String value) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setText(value);
        e.setSingleLine(true);
        e.setTextSize(13);
        e.setSelectAllOnFocus(false);
        return e;
    }

    TextView actionButton(String text) {
        TextView v = button(text);
        v.setTextSize(12);
        v.setPadding(d(10), d(10), d(10), d(10));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, d(48));
        lp.setMargins(0, d(8), 0, 0);
        v.setLayoutParams(lp);
        return v;
    }

    void settings(boolean first) {
        connector.cancelScan();

        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(d(18), d(8), d(18), d(12));
        scroll.addView(box);

        TextView intro = new TextView(this);
        intro.setText("Configure one or more routes. The connector tests them in parallel and prefers Local, then Tailnet, then Public HTTPS.");
        intro.setTextColor(Color.DKGRAY);
        intro.setTextSize(12);
        box.addView(intro);

        box.addView(label("LOCAL LAN"));
        EditText l = field("http://192.168.x.x:8766", local);
        box.addView(l);

        box.addView(label("PRIVATE TAILSCALE"));
        EditText t = field("http://100.x.x.x:8766 or hostname:8766", tail);
        box.addView(t);

        box.addView(label("PUBLIC HTTPS / PIN GATEWAY"));
        EditText p = field("https://your-hostname.ts.net", pub);
        box.addView(p);

        TextView scanState = new TextView(this);
        scanState.setText("LAN scanner: ready");
        scanState.setTextColor(Color.rgb(85, 130, 145));
        scanState.setTextSize(11);
        scanState.setPadding(0, d(8), 0, 0);
        box.addView(scanState);

        TextView scan = actionButton("AUTO-FIND PI ON LOCAL NETWORK");
        box.addView(scan);

        TextView test = actionButton("TEST THESE ENDPOINTS");
        box.addView(test);

        TextView publicOpen = actionButton("OPEN PUBLIC URL ANYWAY");
        box.addView(publicOpen);

        TextView help = new TextView(this);
        help.setText(
                "Scanner searches the current /24 LAN for the default dashboard port 8766.\n\n" +
                "Public access should terminate at the PIN gateway, not intentionally expose the raw dashboard. " +
                "The public route can still work even when a Java probe behaves differently from WebView, so 'Open Public Anyway' is available."
        );
        help.setTextColor(Color.DKGRAY);
        help.setTextSize(11);
        help.setPadding(0, d(12), 0, 0);
        box.addView(help);

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(first ? "Find your Tesla Intelligence Core" : "Connection Center")
                .setView(scroll)
                .setPositiveButton("SAVE + CONNECT", null)
                .setNeutralButton("TESLA BROWSER", null)
                .setNegativeButton(first ? "SKIP" : "CANCEL", null)
                .create();

        dialog.setOnShowListener(x -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                local = ConnectorManager.normalize(l.getText().toString());
                tail = ConnectorManager.normalize(t.getText().toString());
                pub = ConnectorManager.normalize(p.getText().toString());
                saveEndpoints();
                dialog.dismiss();
                resolve();
            });

            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> browserInfo());

            scan.setOnClickListener(v -> {
                scan.setEnabled(false);
                scan.setText("SCANNING…");
                scanState.setText("LAN scanner: starting…");

                final boolean[] found = {false};

                connector.scanLocalNetwork(new ConnectorManager.ScanListener() {
                    @Override public void onProgress(String message) {
                        ui.post(() -> scanState.setText(message));
                    }

                    @Override public void onFound(String url, String message) {
                        found[0] = true;
                        ui.post(() -> {
                            l.setText(url);
                            scanState.setText("FOUND • " + shortUrl(url));
                            scan.setText("FOUND TESLA INTELLIGENCE CORE");
                        });
                    }

                    @Override public void onFinished(boolean didFind) {
                        ui.post(() -> {
                            scan.setEnabled(true);
                            if (!didFind && !found[0]) {
                                scan.setText("AUTO-FIND PI ON LOCAL NETWORK");
                                scanState.setText("Nothing found on port 8766. You can enter the URL manually.");
                            }
                        });
                    }
                });
            });

            test.setOnClickListener(v -> {
                String tl = ConnectorManager.normalize(l.getText().toString());
                String tt = ConnectorManager.normalize(t.getText().toString());
                String tp = ConnectorManager.normalize(p.getText().toString());
                test.setText("TESTING…");
                test.setEnabled(false);

                connector.connect(tl, tt, tp, new ConnectorManager.ConnectListener() {
                    @Override public void onProgress(String message) {
                        ui.post(() -> scanState.setText(message));
                    }

                    @Override public void onComplete(ConnectorManager.EndpointResult winner, List<ConnectorManager.EndpointResult> results) {
                        ui.post(() -> {
                            test.setEnabled(true);
                            test.setText("TEST THESE ENDPOINTS");

                            StringBuilder msg = new StringBuilder();
                            for (ConnectorManager.EndpointResult r : results) {
                                msg.append(r.ok ? "✓ " : "✕ ")
                                        .append(r.kind)
                                        .append(" — ")
                                        .append(r.detail)
                                        .append("\n");
                            }

                            if (winner != null) {
                                scanState.setText("Best route: " + winner.kind + " • " + shortUrl(winner.base));
                            } else {
                                scanState.setText("No configured route passed the connector test.");
                            }

                            new AlertDialog.Builder(MainActivity.this)
                                    .setTitle(winner == null ? "No route connected" : "Connection test")
                                    .setMessage(msg.toString().trim())
                                    .setPositiveButton("OK", null)
                                    .show();
                        });
                    }
                });
            });

            publicOpen.setOnClickListener(v -> {
                String raw = ConnectorManager.normalize(p.getText().toString());
                if (raw.isEmpty()) {
                    Toast.makeText(MainActivity.this, "Public URL is blank.", Toast.LENGTH_SHORT).show();
                    return;
                }
                pub = raw;
                saveEndpoints();
                dialog.dismiss();
                openAnyway(pub, "PUBLIC");
            });
        });

        dialog.setOnDismissListener(x -> connector.cancelScan());
        dialog.setCancelable(!first);
        dialog.show();
    }

    void saveEndpoints() {
        prefs.edit()
                .putString("local", local)
                .putString("private", tail)
                .putString("public", pub)
                .remove("primary")
                .remove("backup")
                .apply();
    }

    void browserInfo() {
        String configured = pub.isEmpty() ? "No public HTTPS endpoint configured." : pub;
        String message =
                "On the setup this project was developed with, the Tesla browser would not load the Pi's local/private dashboard URL. " +
                "A working option was an HTTPS Tailscale Funnel pointed at the PIN gateway. Your installation may vary.\n\n" +
                "Tesla browser → HTTPS Funnel → PIN gateway → dashboard\n\n" +
                "That gives the car browser an Internet-reachable HTTPS URL while the PIN prevents the raw dashboard from being directly public.\n\n" +
                "Configured public URL:\n" + configured +
                "\n\nWhen the Pi and car both have Internet access and Funnel/gateway are healthy, open that URL in the Tesla browser and authenticate with the PIN.";

        AlertDialog.Builder b = new AlertDialog.Builder(this)
                .setTitle("Tesla browser access")
                .setMessage(message)
                .setNegativeButton("CLOSE", null);

        if (!pub.isEmpty()) {
            b.setPositiveButton("COPY URL", (dialog, which) -> {
                ClipboardManager cb = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                cb.setPrimaryClip(ClipData.newPlainText("Tesla Intelligence Core URL", pub));
                Toast.makeText(this, "URL copied", Toast.LENGTH_SHORT).show();
            });
            b.setNeutralButton("OPEN HERE", (dialog, which) -> openAnyway(pub, "PUBLIC"));
        } else {
            b.setPositiveButton("SETUP", (dialog, which) -> settings(false));
        }

        b.show();
    }

    @Override public boolean dispatchTouchEvent(MotionEvent ev) {
        if (navPanel != null && navPanel.getVisibility() == View.VISIBLE) {
            int[] loc = new int[2];
            navPanel.getLocationOnScreen(loc);
            float rawX = ev.getRawX();
            float rawY = ev.getRawY();
            float left = loc[0];
            float top = loc[1];
            float right = left + navPanel.getWidth();
            float bottom = top + navPanel.getHeight();

            if (rawX >= left && rawX < right && rawY >= top && rawY < bottom) {
                float localX = rawX - left;
                float localY = rawY - top;
                float usableBottom = navPanel.getHeight() - navPanel.getPaddingBottom();

                // The reserved system navigation / gesture inset is not a companion button.
                if (localY >= usableBottom) return true;

                if (ev.getActionMasked() == MotionEvent.ACTION_UP) {
                    boolean topRow = localY < usableBottom / 2f;

                    String key;
                    if (topRow) {
                        int col = Math.max(0, Math.min(3, (int) (localX / Math.max(1f, navPanel.getWidth() / 4f))));
                        key = new String[]{"home", "ready", "events", "neural"}[col];
                    } else {
                        int col = Math.max(0, Math.min(2, (int) (localX / Math.max(1f, navPanel.getWidth() / 3f))));
                        key = new String[]{"truth", "thermal", "more"}[col];
                    }

                    navPanel.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    handleNativeNavKey(key);
                }
                return true;
            }
        }
        return super.dispatchTouchEvent(ev);
    }

    void handleNativeNavKey(String key) {
        if (key == null) return;

        switch (key) {
            case "home":
                navSelection = "home";
                view = "morning";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • HOME");
                switchCurrentWebView("morning", "");
                break;
            case "ready":
                navSelection = "ready";
                view = "morning";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • WINTER READINESS");
                switchCurrentWebView("morning", "readiness");
                break;
            case "events":
                navSelection = "events";
                view = "events";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • EVENTS");
                switchCurrentWebView("events", "");
                break;
            case "neural":
                navSelection = "neural";
                view = "neural4";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • NEURAL");
                switchCurrentWebView("neural4", "");
                break;
            case "truth":
                navSelection = "truth";
                view = "truth";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • TRUTH");
                switchCurrentWebView("truth", "");
                break;
            case "thermal":
                navSelection = "thermal";
                view = "thermal";
                map = false;
                updateNativeNav();
                detail.setText(kind + " • THERMAL");
                switchCurrentWebView("thermal", "");
                break;
            case "more":
                detail.setText(kind + " • MORE");
                more();
                break;
        }
    }

    @Override public void onBackPressed() {
        bars();
        if (map) {
            map = false;
            navSelection = "neural";
            updateNativeNav();
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
            switchCurrentWebView("neural4", "");
            return;
        }
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        if (connector != null) connector.shutdown();
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
