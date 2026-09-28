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
    static final String VER = "0.4.0";

    WebView web;
    TextView status;
    TextView detail;
    LinearLayout root;
    SharedPreferences prefs;
    ConnectorManager connector;
    final Handler ui = new Handler(Looper.getMainLooper());

    String local = "";
    String tail = "";
    String pub = "";
    String active = null;
    String kind = "OFFLINE";
    String view = "morning";
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
                getWindow().setDecorFitsSystemWindows(false);
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
        if (Build.VERSION.SDK_INT >= 21) {
            v.setOnApplyWindowInsetsListener((view, insets) -> {
                int left, top, right, bottom;
                if (Build.VERSION.SDK_INT >= 30) {
                    Insets s = insets.getInsets(
                            WindowInsets.Type.systemBars()
                                    | WindowInsets.Type.displayCutout()
                    );
                    left = s.left;
                    top = s.top;
                    right = s.right;
                    bottom = s.bottom;
                } else {
                    left = insets.getSystemWindowInsetLeft();
                    top = insets.getSystemWindowInsetTop();
                    right = insets.getSystemWindowInsetRight();
                    bottom = insets.getSystemWindowInsetBottom();
                }
                view.setPadding(left, top, right, bottom);
                return insets;
            });
            v.requestApplyInsets();
        }
    }

    @Override protected void onResume() {
        super.onResume();
        bars();
        if (root != null) root.requestApplyInsets();
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
            if (root != null) root.requestApplyInsets();
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
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(d(8), d(5), d(8), d(5));
        top.setBackgroundColor(Color.rgb(5, 24, 34));

        LinearLayout titles = new LinearLayout(this);
        titles.setOrientation(LinearLayout.VERTICAL);

        TextView title = new TextView(this);
        title.setText("TESLA INTELLIGENCE CORE");
        title.setTextColor(Color.WHITE);
        title.setTextSize(14);
        title.setTypeface(null, 1);
        title.setSingleLine(true);

        detail = new TextView(this);
        detail.setText("Companion v" + VER);
        detail.setTextColor(Color.rgb(105, 160, 184));
        detail.setTextSize(9);
        detail.setSingleLine(true);
        detail.setEllipsize(TextUtils.TruncateAt.MIDDLE);

        titles.addView(title, new LinearLayout.LayoutParams(-1, d(22)));
        titles.addView(detail, new LinearLayout.LayoutParams(-1, d(16)));
        top.addView(titles, new LinearLayout.LayoutParams(0, d(44), 1));

        status = button("OFFLINE");
        status.setOnClickListener(v -> diagnostics());
        top.addView(status, new LinearLayout.LayoutParams(d(92), d(36)));

        TextView connect = button("CONNECT");
        connect.setOnClickListener(v -> resolve());
        top.addView(connect, new LinearLayout.LayoutParams(d(78), d(36)));

        TextView set = button("SETUP");
        set.setOnClickListener(v -> settings(false));
        top.addView(set, new LinearLayout.LayoutParams(d(70), d(36)));

        root.addView(top, new LinearLayout.LayoutParams(-1, d(54)));

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
                verifyWebViewData();
            }

            @Override public void onReceivedError(WebView v, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    status.setText("ERROR");
                    detail.setText(kind + " • WebView error " + error.getErrorCode());
                }
            }
        });

        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));

        LinearLayout nav = new LinearLayout(this);
        nav.setBackgroundColor(Color.rgb(5, 24, 34));

        String[][] items = {
                {"READY", "morning"},
                {"EVENTS", "events"},
                {"NEURAL", "neural4"},
                {"TRUTH", "truth"},
                {"THERMAL", "thermal"},
                {"MORE", "more"}
        };

        for (String[] it : items) {
            TextView x = button(it[0]);
            x.setTextSize(10);
            x.setPadding(0, 0, 0, 0);
            x.setContentDescription(it[0] + " dashboard section");
            if (!"more".equals(it[1])) navButtons.put(it[1], x);
            x.setOnClickListener(v -> {
                bars();
                if ("more".equals(it[1])) more();
                else select(it[1]);
            });
            nav.addView(x, new LinearLayout.LayoutParams(0, d(50), 1));
        }

        root.addView(nav, new LinearLayout.LayoutParams(-1, d(50)));
        updateNativeNav();
        setContentView(root);
        bars();
        root.requestApplyInsets();
    }

    void select(String x) {
        view = x;
        map = false;
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        updateNativeNav();
        switchDashboardView(x);
    }

    void updateNativeNav() {
        for (Map.Entry<String, TextView> e : navButtons.entrySet()) {
            boolean selected = e.getKey().equals(view) && !map;
            TextView b = e.getValue();
            b.setBackgroundColor(selected ? Color.rgb(13, 72, 96) : Color.rgb(7, 30, 42));
            b.setTextColor(selected ? Color.WHITE : Color.rgb(177, 222, 238));
            b.setTypeface(null, selected ? 1 : 0);
        }
    }

    void switchDashboardView(String target) {
        if (active == null || active.isEmpty()) return;

        String js =
                "(function(){" +
                "var n='" + target + "';" +
                "try{" +
                "if(typeof switchView==='function'){switchView(n);}" +
                "else{" +
                "var t=document.querySelector('.tab[data-view=\"'+n+'\"]');" +
                "document.querySelectorAll('.tab').forEach(function(x){x.classList.toggle('active',x===t);});" +
                "document.querySelectorAll('.view').forEach(function(v){v.classList.toggle('active',v.id==='view-'+n);});" +
                "window.scrollTo(0,0);" +
                "}" +
                "var v=document.getElementById('view-'+n);" +
                "return v&&v.classList.contains('active')?'OK:'+n:'MISSING:'+n;" +
                "}catch(e){return 'ERROR:'+e;}" +
                "})()";

        web.evaluateJavascript(js, value -> {
            String result = cleanJsValue(value);
            if (result.startsWith("OK:")) {
                detail.setText(kind + " • " + shortUrl(active) + " • " + target.toUpperCase());
                applyCompanionCss();
            } else if (result.startsWith("ERROR:") || result.startsWith("MISSING:")) {
                lastJsError = "view switch • " + result;
                detail.setText(kind + " • view switch issue");
            }
        });
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
        map = true;
        updateNativeNav();
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        switchDashboardView("neural4");
        ui.postDelayed(this::applyCompanionCss, 250);
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
        web.loadUrl(active + "/");
    }

    void loadAuth(String base) {
        active = ConnectorManager.normalize(base);
        kind = "PUBLIC";
        dashboardReady = false;
        status.setText("LOGIN");
        detail.setText("PIN gateway • enter PIN");
        web.loadUrl(active + "/");
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

                    switchDashboardView(view);
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
        return out.replace("\\\\", "\\").replace("\\\\"", "\"");
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
                "var st=document.getElementById('ticMapStyle');if(st)st.remove();st=document.createElement('style');st.id='ticMapStyle';st.textContent='#n4MapShell{height:auto!important;min-height:0!important}#n4NetworkMap{width:100%!important;height:auto!important;max-width:100%!important;display:block!important}';document.head.appendChild(st);";

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
        switchDashboardView(view);
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

    @Override public void onBackPressed() {
        bars();
        if (map) {
            map = false;
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
            apply();
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
