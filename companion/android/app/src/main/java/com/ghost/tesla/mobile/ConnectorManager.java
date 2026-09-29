package com.ghost.tesla.mobile;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public final class ConnectorManager {
    public static final int DASHBOARD_PORT = 8766;

    public static final class EndpointResult {
        public final String kind;
        public final String base;
        public final boolean ok;
        public final boolean authRequired;
        public final String detail;
        public final int rank;

        EndpointResult(String kind, String base, boolean ok, boolean authRequired, String detail, int rank) {
            this.kind = kind;
            this.base = base;
            this.ok = ok;
            this.authRequired = authRequired;
            this.detail = detail;
            this.rank = rank;
        }
    }

    public interface ConnectListener {
        void onProgress(String message);
        void onComplete(EndpointResult winner, List<EndpointResult> results);
    }

    public interface ScanListener {
        void onProgress(String message);
        void onFound(String url, String detail);
        void onFinished(boolean found);
    }

    private final ExecutorService pool = Executors.newCachedThreadPool();
    private final AtomicInteger connectGeneration = new AtomicInteger();
    private final AtomicInteger scanGeneration = new AtomicInteger();

    public static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (s.isEmpty()) return "";
        if (!s.matches("(?i)^https?://.*")) {
            String lower = s.toLowerCase(Locale.US);
            if (lower.endsWith(".ts.net") || lower.contains(".ts.net:")) s = "https://" + s;
            else s = "http://" + s;
        }
        return s;
    }

    public void connect(String local, String tailnet, String pub, ConnectListener listener) {
        final int generation = connectGeneration.incrementAndGet();
        final ArrayList<EndpointResult> seeds = new ArrayList<>();

        local = normalize(local);
        tailnet = normalize(tailnet);
        pub = normalize(pub);

        if (!local.isEmpty()) seeds.add(new EndpointResult("LOCAL", local, false, false, "pending", 0));
        if (!tailnet.isEmpty()) seeds.add(new EndpointResult("TAILNET", tailnet, false, false, "pending", 1));
        if (!pub.isEmpty()) seeds.add(new EndpointResult("PUBLIC", pub, false, false, "pending", 2));

        if (seeds.isEmpty()) {
            listener.onComplete(null, Collections.emptyList());
            return;
        }

        listener.onProgress("Testing " + seeds.size() + " configured path" + (seeds.size() == 1 ? "" : "s") + " in parallel…");

        pool.submit(() -> {
            CompletionService<EndpointResult> completion = new ExecutorCompletionService<>(pool);
            int count = 0;
            for (EndpointResult seed : seeds) {
                count++;
                completion.submit(() -> {
                    int timeout = seed.rank == 0 ? 2200 : (seed.rank == 1 ? 3200 : 5200);
                    Probe p = probe(seed.base, timeout);
                    return new EndpointResult(seed.kind, seed.base, p.ok, p.authRequired, p.detail, seed.rank);
                });
            }

            ArrayList<EndpointResult> results = new ArrayList<>();
            EndpointResult best = null;
            long firstSuccessAt = 0L;
            long deadline = System.currentTimeMillis() + 6500L;
            int received = 0;

            while (received < count && System.currentTimeMillis() < deadline && generation == connectGeneration.get()) {
                try {
                    Future<EndpointResult> f = completion.poll(220, TimeUnit.MILLISECONDS);
                    if (f == null) {
                        if (best != null && System.currentTimeMillis() - firstSuccessAt > 750L) break;
                        continue;
                    }

                    EndpointResult r = f.get();
                    received++;
                    results.add(r);

                    if (r.ok) {
                        if (best == null || r.rank < best.rank) best = r;
                        if (firstSuccessAt == 0L) firstSuccessAt = System.currentTimeMillis();
                        if (best.rank == 0) break;
                    }
                } catch (Exception ignored) {
                }
            }

            if (generation != connectGeneration.get()) return;

            for (EndpointResult seed : seeds) {
                boolean already = false;
                for (EndpointResult r : results) {
                    if (r.kind.equals(seed.kind)) {
                        already = true;
                        break;
                    }
                }
                if (!already) results.add(new EndpointResult(seed.kind, seed.base, false, false, "probe timed out", seed.rank));
            }

            listener.onComplete(best, results);
        });
    }

    public void scanLocalNetwork(ScanListener listener) {
        final int generation = scanGeneration.incrementAndGet();

        pool.submit(() -> {
            String ip = privateIpv4();
            if (ip == null) {
                listener.onProgress("No private IPv4 network detected.");
                listener.onFinished(false);
                return;
            }

            String[] parts = ip.split("\\.");
            if (parts.length != 4) {
                listener.onProgress("Could not determine local subnet.");
                listener.onFinished(false);
                return;
            }

            String prefix = parts[0] + "." + parts[1] + "." + parts[2] + ".";
            listener.onProgress("Scanning " + prefix + "0/24 for Tesla Intelligence Core on port " + DASHBOARD_PORT + "…");

            ExecutorService scanPool = Executors.newFixedThreadPool(36);
            CompletionService<String> completion = new ExecutorCompletionService<>(scanPool);
            ArrayList<Future<String>> futures = new ArrayList<>();

            for (int host = 1; host <= 254; host++) {
                final String hostIp = prefix + host;
                if (hostIp.equals(ip)) continue;

                futures.add(completion.submit(() -> {
                    if (generation != scanGeneration.get()) return null;
                    String base = "http://" + hostIp + ":" + DASHBOARD_PORT;
                    return identifyDashboard(base, 330) ? base : null;
                }));
            }

            boolean found = false;
            long deadline = System.currentTimeMillis() + 6500L;
            int remaining = futures.size();

            try {
                while (remaining > 0 && System.currentTimeMillis() < deadline && generation == scanGeneration.get()) {
                    Future<String> f = completion.poll(180, TimeUnit.MILLISECONDS);
                    if (f == null) continue;
                    remaining--;
                    String url = null;
                    try { url = f.get(); } catch (Exception ignored) {}
                    if (url != null) {
                        found = true;
                        listener.onFound(url, "Discovered on the local network");
                        break;
                    }
                }
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            } finally {
                for (Future<String> f : futures) f.cancel(true);
                scanPool.shutdownNow();
            }

            if (generation == scanGeneration.get()) listener.onFinished(found);
        });
    }

    public void cancelScan() {
        scanGeneration.incrementAndGet();
    }

    public void cancelConnect() {
        connectGeneration.incrementAndGet();
    }

    public void shutdown() {
        cancelScan();
        cancelConnect();
        pool.shutdownNow();
    }

    private static final class Probe {
        final boolean ok;
        final boolean authRequired;
        final String detail;

        Probe(boolean ok, boolean authRequired, String detail) {
            this.ok = ok;
            this.authRequired = authRequired;
            this.detail = detail;
        }
    }

    private static Probe probe(String raw, int timeoutMs) {
        String base = normalize(raw);
        if (base.isEmpty()) return new Probe(false, false, "endpoint blank");

        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(base + "/api/v3/overview").openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(timeoutMs);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            c.setRequestProperty("Accept", "application/json");
            c.setRequestProperty("User-Agent", "TIC-Companion/0.8.0");

            int code = c.getResponseCode();
            String body = readSmallBody(c);

            if (code == 200 && body != null && body.trim().startsWith("{")) {
                String lower = body.toLowerCase(Locale.US);
                if (lower.contains("\"readiness\"") || lower.contains("\"events\"") || lower.contains("\"version\"")) {
                    return new Probe(true, false, "DATA OK • /api/v3/overview");
                }
                return new Probe(false, false, "HTTP 200 but response was not recognized as Tesla Intelligence Core data");
            }

            if (code == 401) {
                String lower = body == null ? "" : body.toLowerCase(Locale.US);
                if (lower.contains("pin authentication required") || lower.contains("authentication required")) {
                    return new Probe(true, true, "PIN LOGIN REQUIRED • /api/v3/overview returned 401");
                }
                return new Probe(false, false, "HTTP 401 from dashboard API");
            }

            if (code == 302 || code == 303 || code == 307 || code == 308) {
                String location = c.getHeaderField("Location");
                if (location != null && location.toLowerCase(Locale.US).contains("auth")) {
                    return new Probe(true, true, "LOGIN REQUIRED • redirected to " + location);
                }
            }

            Probe root = probeRoot(base, timeoutMs);
            if (root.authRequired) return root;
            if (root.ok) return new Probe(false, false, "Web page answered, but dashboard data API did not: HTTP " + code);
            return new Probe(false, false, "Dashboard API unavailable: HTTP " + code + " • " + root.detail);
        } catch (Exception e) {
            Probe root = probeRoot(base, Math.min(timeoutMs, 2200));
            if (root.authRequired) return root;
            return new Probe(false, false, e.getClass().getSimpleName() + ": " + safeMessage(e) + " • " + root.detail);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static Probe probeRoot(String base, int timeoutMs) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(base + "/").openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(timeoutMs);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", "TIC-Companion/0.8.0");
            int code = c.getResponseCode();
            String body = readSmallBody(c);
            String lower = body == null ? "" : body.toLowerCase(Locale.US);

            if (code >= 200 && code < 400) {
                if (lower.contains("ghost // secure funnel")
                        || lower.contains("enter the ghost pin")
                        || lower.contains("public funnel gateway")
                        || lower.contains("__ghost_auth/login")) {
                    return new Probe(true, true, "PIN LOGIN PAGE");
                }

                if (lower.contains("tesla intelligence core")
                        || lower.contains("ghost winter readiness")
                        || lower.contains("winter readiness board")) {
                    return new Probe(true, false, "Dashboard HTML reachable");
                }

                return new Probe(true, false, "HTTP " + code + " /");
            }

            return new Probe(false, false, "HTTP " + code + " /");
        } catch (Exception e) {
            Probe t = tcp(base, Math.min(timeoutMs, 1500));
            return new Probe(false, false, e.getClass().getSimpleName() + ": " + safeMessage(e) + " • " + t.detail);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String readSmallBody(HttpURLConnection c) {
        InputStream in = null;
        try {
            int code = c.getResponseCode();
            in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) return "";
            BufferedReader reader = new BufferedReader(new InputStreamReader(in));
            StringBuilder body = new StringBuilder();
            char[] buf = new char[1024];
            int n;
            while ((n = reader.read(buf)) > 0 && body.length() < 16384) body.append(buf, 0, n);
            return body.toString();
        } catch (Exception ignored) {
            return "";
        } finally {
            try { if (in != null) in.close(); } catch (Exception ignored) {}
        }
    }

    private static Probe tcp(String base, int timeoutMs) {
        Socket socket = null;
        try {
            URI u = new URI(normalize(base));
            String host = u.getHost();
            int port = u.getPort();
            if (host == null) return new Probe(false, false, "invalid URL");
            if (port < 0) port = "https".equalsIgnoreCase(u.getScheme()) ? 443 : 80;
            socket = new Socket();
            socket.connect(new InetSocketAddress(host, port), timeoutMs);
            return new Probe(true, false, "TCP " + host + ":" + port + " connected");
        } catch (Exception e) {
            return new Probe(false, false, e.getClass().getSimpleName() + ": " + safeMessage(e));
        } finally {
            try { if (socket != null) socket.close(); } catch (Exception ignored) {}
        }
    }

    private static boolean identifyDashboard(String base, int timeoutMs) {
        HttpURLConnection c = null;
        InputStream in = null;
        try {
            c = (HttpURLConnection) new URL(base + "/").openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(Math.max(500, timeoutMs + 250));
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", "TIC-Companion-Scanner/0.8.0");
            int code = c.getResponseCode();
            if (code < 200 || code >= 400) return false;

            in = c.getInputStream();
            BufferedReader reader = new BufferedReader(new InputStreamReader(in));
            StringBuilder body = new StringBuilder();
            char[] buf = new char[2048];
            int n;
            while ((n = reader.read(buf)) > 0 && body.length() < 24576) body.append(buf, 0, n);
            String text = body.toString().toLowerCase(Locale.US);

            return text.contains("ghost winter readiness")
                    || text.contains("tesla intelligence core")
                    || text.contains("winter readiness board")
                    || text.contains("n4networkmap")
                    || text.contains("ghost_tesla_ai");
        } catch (Exception ignored) {
            return false;
        } finally {
            try { if (in != null) in.close(); } catch (Exception ignored) {}
            if (c != null) c.disconnect();
        }
    }

    private static String privateIpv4() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            ArrayList<String> candidates = new ArrayList<>();

            while (interfaces.hasMoreElements()) {
                NetworkInterface ni = interfaces.nextElement();
                try {
                    if (!ni.isUp() || ni.isLoopback()) continue;
                } catch (Exception ignored) {}

                Enumeration<InetAddress> addresses = ni.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress addr = addresses.nextElement();
                    if (!(addr instanceof Inet4Address) || addr.isLoopbackAddress()) continue;
                    String ip = addr.getHostAddress();
                    if (isPrivate(ip)) candidates.add(ip);
                }
            }

            for (String ip : candidates) {
                if (ip.startsWith("192.168.")) return ip;
            }
            for (String ip : candidates) {
                if (ip.startsWith("10.")) return ip;
            }
            return candidates.isEmpty() ? null : candidates.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    private static boolean isPrivate(String ip) {
        if (ip == null) return false;
        if (ip.startsWith("10.") || ip.startsWith("192.168.")) return true;
        if (!ip.startsWith("172.")) return false;
        try {
            int second = Integer.parseInt(ip.split("\\.")[1]);
            return second >= 16 && second <= 31;
        } catch (Exception e) {
            return false;
        }
    }

    private static String safeMessage(Exception e) {
        String m = e.getMessage();
        return m == null ? e.getClass().getSimpleName() : m;
    }
}
