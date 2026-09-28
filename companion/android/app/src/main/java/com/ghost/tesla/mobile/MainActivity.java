package com.ghost.tesla.mobile;

import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import java.net.URI;
import java.net.Socket;
import java.net.InetSocketAddress;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.*;

public class MainActivity extends Activity {
    static final String VER="0.2.0";
    static final int LOCAL_MS=3500, PRIVATE_MS=5000, PUBLIC_MS=7000;
    WebView web; TextView status, detail; SharedPreferences prefs;
    final ExecutorService io=Executors.newCachedThreadPool();
    final Handler ui=new Handler(Looper.getMainLooper());
    String local="", tail="", pub="", active=null, kind="OFFLINE", view="morning";
    String dl="not tested", dt="not tested", dpb="not tested";
    boolean map=false; long pausedAt=0;

    static class Probe { boolean ok; String detail; Probe(boolean o,String d){ok=o;detail=d;} }

    @Override public void onCreate(Bundle b){
        super.onCreate(b); bars();
        prefs=getSharedPreferences("ghost",MODE_PRIVATE);
        local=norm(prefs.getString("local",prefs.getString("primary","")));
        tail=norm(prefs.getString("private",prefs.getString("backup","")));
        pub=norm(prefs.getString("public",""));

        // Optional non-persistent endpoint overrides are useful for testing,
        // demos and automated screenshots without baking addresses into the APK.
        Intent launch=getIntent();
        if(launch!=null){
            String x=launch.getStringExtra("tic_local");
            if(x!=null&&!x.trim().isEmpty()) local=norm(x);
            x=launch.getStringExtra("tic_tailnet");
            if(x!=null&&!x.trim().isEmpty()) tail=norm(x);
            x=launch.getStringExtra("tic_public");
            if(x!=null&&!x.trim().isEmpty()) pub=norm(x);
        }

        build();
        if(!any()){ welcome(); ui.postDelayed(()->settings(true),250); } else resolve();
    }

    void bars(){
        getWindow().setStatusBarColor(Color.rgb(4,19,28));
        getWindow().setNavigationBarColor(Color.rgb(4,19,28));
        if(Build.VERSION.SDK_INT>=29)getWindow().setNavigationBarContrastEnforced(false);
        try{
            if(Build.VERSION.SDK_INT>=30){
                WindowInsetsController c=getWindow().getInsetsController();
                if(c!=null){c.show(WindowInsets.Type.statusBars()|WindowInsets.Type.navigationBars());c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_DEFAULT);}
            }else getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
        }catch(Exception ignored){}
    }
    @Override protected void onResume(){super.onResume();bars();if(pausedAt>0&&System.currentTimeMillis()-pausedAt>300000&&any())resolve();}
    @Override protected void onPause(){pausedAt=System.currentTimeMillis();super.onPause();}
    @Override public void onWindowFocusChanged(boolean f){super.onWindowFocusChanged(f);if(f)bars();}

    int d(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    boolean any(){return !local.isEmpty()||!tail.isEmpty()||!pub.isEmpty();}
    String norm(String s){s=s==null?"":s.trim();while(s.endsWith("/"))s=s.substring(0,s.length()-1);return s;}
    String shortUrl(String s){return s==null||s.isEmpty()?"—":s.replace("http://","").replace("https://","");}
    String dash(String s){return s==null||s.isEmpty()?"—":s;}
    String esc(String s){return s==null?"":s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;");}

    TextView button(String t){
        TextView v=new TextView(this);v.setText(t);v.setTextColor(Color.rgb(220,246,255));v.setGravity(Gravity.CENTER);
        v.setTextSize(11);v.setPadding(d(8),0,d(8),0);v.setBackgroundColor(Color.rgb(7,30,42));return v;
    }

    void build(){
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(Color.rgb(4,19,28));
        LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);top.setPadding(d(8),d(5),d(8),d(5));top.setBackgroundColor(Color.rgb(5,24,34));
        LinearLayout titles=new LinearLayout(this);titles.setOrientation(LinearLayout.VERTICAL);
        TextView title=new TextView(this);title.setText("TESLA INTELLIGENCE CORE");title.setTextColor(Color.WHITE);title.setTextSize(14);title.setTypeface(null,1);title.setSingleLine(true);
        detail=new TextView(this);detail.setText("Companion v"+VER);detail.setTextColor(Color.rgb(105,160,184));detail.setTextSize(9);detail.setSingleLine(true);
        titles.addView(title,new LinearLayout.LayoutParams(-1,d(22)));titles.addView(detail,new LinearLayout.LayoutParams(-1,d(16)));
        top.addView(titles,new LinearLayout.LayoutParams(0,d(44),1));
        status=button("OFFLINE");status.setOnClickListener(v->diagnostics());top.addView(status,new LinearLayout.LayoutParams(d(90),d(36)));
        TextView refresh=button("REFRESH");refresh.setOnClickListener(v->resolve());top.addView(refresh,new LinearLayout.LayoutParams(d(76),d(36)));
        TextView set=button("SETTINGS");set.setOnClickListener(v->settings(false));top.addView(set,new LinearLayout.LayoutParams(d(80),d(36)));
        root.addView(top,new LinearLayout.LayoutParams(-1,d(54)));

        web=new WebView(this); WebSettings s=web.getSettings();
        s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setUseWideViewPort(true);s.setLoadWithOverviewMode(true);
        s.setBuiltInZoomControls(true);s.setDisplayZoomControls(false);s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);s.setUserAgentString(s.getUserAgentString()+" TIC-Companion/"+VER);
        if(Build.VERSION.SDK_INT>=26)s.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,true);
        web.setBackgroundColor(Color.rgb(4,19,28));
        web.setWebViewClient(new WebViewClient(){
            @Override public void onPageStarted(WebView v,String u,android.graphics.Bitmap f){detail.setText(kind+" • loading "+shortUrl(active));}
            @Override public void onPageFinished(WebView v,String u){detail.setText(kind+" • "+shortUrl(active));apply();ui.postDelayed(()->apply(),350);ui.postDelayed(()->apply(),1200);}
            @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame()){diag(kind,"WebView "+e.getErrorCode()+": "+e.getDescription());resolve();}}
        });
        root.addView(web,new LinearLayout.LayoutParams(-1,0,1));

        LinearLayout nav=new LinearLayout(this);nav.setBackgroundColor(Color.rgb(5,24,34));
        String[][] items={{"HOME","morning"},{"NEURAL","neural4"},{"TRUTH","truth"},{"THERMAL","thermal"},{"MORE","more"}};
        for(String[] it:items){TextView x=button(it[0]);x.setTextSize(12);x.setOnClickListener(v->{bars();if("more".equals(it[1]))more();else select(it[1]);});nav.addView(x,new LinearLayout.LayoutParams(0,d(50),1));}
        root.addView(nav,new LinearLayout.LayoutParams(-1,d(50)));setContentView(root);bars();
    }

    void select(String x){view=x;map=false;setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);apply();}
    void more(){
        String[] labels={"AI LAB","MODELS","DATA QUALITY","SOURCES","EVENTS","PRODUCTION","HISTORY","NEURAL MAP","TESLA BROWSER ACCESS","CONNECTION DIAGNOSTICS"};
        String[] acts={"overview","models","quality","sources","events","production","history","map","browser","diag"};
        new AlertDialog.Builder(this).setTitle("Tesla Intelligence Core").setItems(labels,(d,w)->{
            String a=acts[w]; if("map".equals(a))openMap();else if("browser".equals(a))browserInfo();else if("diag".equals(a))diagnostics();else select(a);
        }).setNegativeButton("CLOSE",null).show();
    }
    void openMap(){view="neural4";map=true;setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);apply();}

    Probe tcp(String base,int ms){
        Socket so=null;try{URI u=new URI(norm(base));String h=u.getHost();int p=u.getPort();if(p<0)p="https".equalsIgnoreCase(u.getScheme())?443:80;
            if(h==null)return new Probe(false,"invalid URL");so=new Socket();so.connect(new InetSocketAddress(h,p),ms);return new Probe(true,"TCP "+h+":"+p+" connected");
        }catch(Exception e){return new Probe(false,e.getClass().getSimpleName()+": "+e.getMessage());}finally{try{if(so!=null)so.close();}catch(Exception ignored){}}
    }
    Probe probe(String base,int ms){
        if(base==null||base.isEmpty())return new Probe(false,"endpoint blank");String last="no response";
        for(String path:new String[]{"/api/health","/health","/"}){
            HttpURLConnection c=null;try{c=(HttpURLConnection)new URL(norm(base)+path).openConnection();c.setConnectTimeout(ms);c.setReadTimeout(ms);c.setUseCaches(false);c.setInstanceFollowRedirects(true);
                c.setRequestProperty("Accept","application/json,text/html,*/*");c.setRequestProperty("User-Agent","TIC-Companion/"+VER);int code=c.getResponseCode();
                if(code>=200&&code<400)return new Probe(true,"HTTP "+code+" "+path);last="HTTP "+code+" "+path;
            }catch(Exception e){last=e.getClass().getSimpleName()+": "+e.getMessage();}finally{if(c!=null)c.disconnect();}
        }
        Probe t=tcp(base,Math.min(ms,3000));return t.ok?new Probe(true,t.detail+" • HTTP probe inconclusive"):new Probe(false,last+" • "+t.detail);
    }
    void diag(String k,String v){if("LOCAL".equals(k))dl=v;else if("TAILNET".equals(k))dt=v;else if("PUBLIC".equals(k))dpb=v;}

    void resolve(){
        if(!any()){status.setText("SETUP");detail.setText("Configure a dashboard URL");welcome();return;}
        status.setText("CONNECTING");detail.setText("Trying Local → Tailnet → Public");
        io.submit(()->{
            if(!local.isEmpty()){Probe p=probe(local,LOCAL_MS);dl=p.detail;if(p.ok){load(local,"LOCAL");return;}}
            if(!tail.isEmpty()){Probe p=probe(tail,PRIVATE_MS);dt=p.detail;if(p.ok){load(tail,"TAILNET");return;}}
            if(!pub.isEmpty()){Probe p=probe(pub,PUBLIC_MS);dpb=p.detail;if(p.ok){load(pub,"PUBLIC");return;}}
            ui.post(()->{active=null;kind="OFFLINE";status.setText("OFFLINE");detail.setText("Tap OFFLINE for diagnostics");offline();});
        });
    }
    void load(String base,String k){ui.post(()->{active=norm(base);kind=k;status.setText(k);detail.setText(k+" • "+shortUrl(active));web.loadUrl(active+"/");});}

    void welcome(){
        web.loadDataWithBaseURL(null,"<body style='background:#04131c;color:#dff6ff;font-family:sans-serif;padding:28px'><h2>Tesla Intelligence Core Companion</h2><p>Configure Local, private Tailscale and/or public HTTPS endpoints in <b>SETTINGS</b>.</p><p>The app tries Local → Tailnet → Public and fails over automatically.</p></body>","text/html","UTF-8",null);
    }
    void offline(){
        String h="<body style='background:#04131c;color:#dff6ff;font-family:sans-serif;padding:28px'><h2>Dashboard unavailable</h2>"+
            "<p><b>Local:</b> "+esc(local)+"<br><small>"+esc(dl)+"</small></p><p><b>Tailnet:</b> "+esc(tail)+"<br><small>"+esc(dt)+"</small></p>"+
            "<p><b>Public:</b> "+esc(pub)+"<br><small>"+esc(dpb)+"</small></p><p>Tap OFFLINE for diagnostics or SETTINGS to edit endpoints.</p></body>";
        web.loadDataWithBaseURL(null,h,"text/html","UTF-8",null);
    }

    String mapJs(){
        return "function ticFixMap(){var s=document.getElementById('n4NetworkMap'),h=document.getElementById('n4MapShell');if(!s||!h)return;"+
            "s.setAttribute('preserveAspectRatio','xMidYMid meet');var v=s.viewBox&&s.viewBox.baseVal?s.viewBox.baseVal:null;if(v&&v.width>0&&v.height>0)s.style.setProperty('aspect-ratio',v.width+' / '+v.height,'important');}"+
            "ticFixMap();var s=document.getElementById('n4NetworkMap');if(s&&!s.__ticObserver){s.__ticObserver=new MutationObserver(function(){ticFixMap();});s.__ticObserver.observe(s,{attributes:true,attributeFilter:['preserveAspectRatio','viewBox']});}"+
            "if(!window.__ticTimer)window.__ticTimer=setInterval(ticFixMap,1000);";
    }
    void apply(){
        if(active==null)return;
        String css=map?
            "var st=document.getElementById('ticMapStyle');if(st)st.remove();st=document.createElement('style');st.id='ticMapStyle';st.textContent='header.topbar,.neural-v4-hero,.neural-v4-kpis,.n6-governor,.neural-dev>.section-title,.n4-live-narrative,.n4-mission-strip,.n4-runtime-strip,.neural-progress-card,.n4-insight-strip,.n4-observatory-strip{display:none!important}main{padding:0!important;max-width:none!important;width:100%!important}.neural-dev{margin:0!important;padding:0!important;border:0!important}#n4MapShell{height:100vh!important;min-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important}#n4NetworkMap{width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important;display:block!important}';document.head.appendChild(st);":
            "var st=document.getElementById('ticMapStyle');if(st)st.remove();st=document.createElement('style');st.id='ticMapStyle';st.textContent='#n4MapShell{height:auto!important;min-height:0!important}#n4NetworkMap{width:100%!important;height:auto!important;max-width:100%!important;display:block!important}';document.head.appendChild(st);";
        String js="(function(){var b=document.querySelector('.tab[data-view=\\\""+view+"\\\"]');if(b)b.click();"+css+mapJs()+(map?"setTimeout(function(){ticFixMap();var m=document.getElementById('n4MapShell');if(m)m.scrollIntoView({block:'start'});},120);":"setTimeout(ticFixMap,120);")+"})()";
        web.evaluateJavascript(js,null);
    }

    void diagnostics(){
        String m="ACTIVE\n"+kind+" • "+dash(active)+"\n\nLOCAL\n"+dash(local)+"\n"+dl+"\n\nTAILNET\n"+dash(tail)+"\n"+dt+"\n\nPUBLIC / FUNNEL\n"+dash(pub)+"\n"+dpb+
            "\n\nThe app tries Local → Tailnet → Public. A public endpoint may show the PIN gateway before the dashboard.";
        new AlertDialog.Builder(this).setTitle("Connection diagnostics").setMessage(m).setPositiveButton("RETEST",(d,w)->resolve()).setNeutralButton("SETTINGS",(d,w)->settings(false)).setNegativeButton("CLOSE",null).show();
    }
    EditText field(String hint,String val){EditText e=new EditText(this);e.setHint(hint);e.setText(val);e.setSingleLine(true);e.setTextSize(13);return e;}
    void settings(boolean first){
        LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(d(18),d(8),d(18),0);
        EditText l=field("Local URL (optional)",local),t=field("Private Tailscale URL (optional)",tail),p=field("Public HTTPS / Funnel URL (optional)",pub);
        box.addView(l);box.addView(t);box.addView(p);
        TextView help=new TextView(this);help.setText("Examples:\nLocal: http://192.168.x.x:8766\nTailnet: http://100.x.x.x:8766 or http://hostname:8766\nPublic: https://your-hostname.example/\n\nPublic access should terminate at the PIN gateway, not expose the raw dashboard.");
        help.setTextColor(Color.DKGRAY);help.setTextSize(11);help.setPadding(0,d(8),0,0);box.addView(help);
        AlertDialog.Builder b=new AlertDialog.Builder(this).setTitle(first?"Set up companion":"Dashboard endpoints").setView(box)
            .setPositiveButton("SAVE + CONNECT",(x,w)->{local=norm(l.getText().toString());tail=norm(t.getText().toString());pub=norm(p.getText().toString());
                prefs.edit().putString("local",local).putString("private",tail).putString("public",pub).remove("primary").remove("backup").apply();resolve();})
            .setNeutralButton("BROWSER INFO",(x,w)->browserInfo());
        if(!first)b.setNegativeButton("CANCEL",null);b.setCancelable(!first);b.show();
    }

    void browserInfo(){
        String u=pub.isEmpty()?"No public HTTPS endpoint configured.":pub;
        String m="On the development setup, the Tesla browser would not load the Pi's local/private dashboard URL. A working option was an HTTPS Tailscale Funnel pointed at the PIN gateway. Your installation may vary.\n\n"+
            "That gives the car browser an Internet-reachable HTTPS URL while the PIN keeps the raw dashboard from being directly public.\n\nConfigured public URL:\n"+u+
            "\n\nWhen the car has Internet access and the Funnel/gateway are running, open that URL in the Tesla browser and authenticate with the PIN.";
        AlertDialog.Builder b=new AlertDialog.Builder(this).setTitle("Tesla browser access").setMessage(m).setNegativeButton("CLOSE",null);
        if(!pub.isEmpty()){b.setPositiveButton("COPY URL",(x,w)->{ClipboardManager cb=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);cb.setPrimaryClip(ClipData.newPlainText("Tesla Intelligence Core URL",pub));Toast.makeText(this,"URL copied",Toast.LENGTH_SHORT).show();});b.setNeutralButton("OPEN HERE",(x,w)->load(pub,"PUBLIC"));}
        else b.setPositiveButton("SETTINGS",(x,w)->settings(false));b.show();
    }

    @Override public void onBackPressed(){bars();if(map){map=false;setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);apply();return;}if(web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){io.shutdownNow();if(web!=null)web.destroy();super.onDestroy();}
}
