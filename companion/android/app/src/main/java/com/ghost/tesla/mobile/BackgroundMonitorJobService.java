package com.ghost.tesla.mobile;

import android.app.job.JobParameters;
import android.app.job.JobService;
import android.content.Context;
import android.content.SharedPreferences;
import android.webkit.CookieManager;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.Set;

public class BackgroundMonitorJobService extends JobService {
    private volatile Thread worker;

    @Override public boolean onStartJob(JobParameters params) {
        worker = new Thread(() -> {
            try {
                performCheck(getApplicationContext(), false);
            } finally {
                jobFinished(params, false);
            }
        }, "tic-background-monitor");
        worker.start();
        return true;
    }

    @Override public boolean onStopJob(JobParameters params) {
        Thread t = worker;
        if (t != null) t.interrupt();
        return true;
    }

    static void runImmediate(Context context) {
        new Thread(() -> performCheck(context, true), "tic-background-monitor-now").start();
    }

    static void performCheck(Context context, boolean manual) {
        SharedPreferences p = context.getSharedPreferences("ghost", Context.MODE_PRIVATE);
        if (!p.getBoolean("notifications_enabled", true) && !manual) return;

        NotificationCenter.ensureChannels(context);

        JSONObject winter = null;
        String winner = "";
        String lastError = "No configured route";

        Set<String> candidates = new LinkedHashSet<>();
        add(candidates, p.getString("last_good_url", ""));
        add(candidates, p.getString("local", p.getString("primary", "")));
        add(candidates, p.getString("private", p.getString("backup", "")));
        add(candidates, p.getString("public", ""));

        for (String base : candidates) {
            try {
                winter = fetchWinter(base);
                winner = base;
                break;
            } catch (Exception e) {
                lastError = shortError(e);
            }
        }

        if (winter == null) {
            onFailure(context, p, lastError, manual);
            return;
        }

        onSuccess(context, p, winner, winter, manual);
    }

    private static void add(Set<String> out, String value) {
        if (value == null) return;
        String s = value.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (!s.isEmpty()) out.add(s);
    }

    private static JSONObject fetchWinter(String base) throws Exception {
        URL url = new URL(base + "/api/v3/winter");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setConnectTimeout(7000);
        c.setReadTimeout(9000);
        c.setRequestProperty("Accept", "application/json");
        c.setRequestProperty("User-Agent", "TIC-Companion-Background/0.9.1");
        c.setInstanceFollowRedirects(false);

        try {
            String cookie = CookieManager.getInstance().getCookie(base);
            if (cookie != null && !cookie.isEmpty()) c.setRequestProperty("Cookie", cookie);
        } catch (Throwable ignored) {
        }

        int code = c.getResponseCode();
        if (code != 200) throw new Exception("HTTP " + code + " from " + host(base));

        StringBuilder body = new StringBuilder();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) body.append(line);
        } finally {
            c.disconnect();
        }

        JSONObject j = new JSONObject(body.toString());
        if (!j.has("score") && !j.has("current") && !j.has("departure")) {
            throw new Exception("Winter API response was not recognized");
        }
        return j;
    }

    private static void onFailure(Context context, SharedPreferences p, String error, boolean manual) {
        int fails = p.getInt("monitor_fail_count", 0) + 1;
        boolean already = p.getBoolean("monitor_offline_alerted", false);

        SharedPreferences.Editor e = p.edit()
                .putInt("monitor_fail_count", fails)
                .putLong("last_monitor_at", System.currentTimeMillis())
                .putString("last_monitor_status", "OFFLINE")
                .putString("last_monitor_error", error);
        e.apply();

        if (manual) {
            NotificationCenter.post(context, 1100, "Background check failed", error, "morning");
            return;
        }

        if (fails >= 2 && !already && p.getBoolean("alert_connection", true)) {
            NotificationCenter.post(
                    context,
                    1101,
                    "Tesla Intelligence Core unreachable",
                    "The background monitor could not reach the saved Pi routes. Last result: " + error,
                    "morning"
            );
            p.edit().putBoolean("monitor_offline_alerted", true).apply();
        }
    }

    private static void onSuccess(Context context, SharedPreferences p, String base, JSONObject w, boolean manual) {
        boolean wasOffline = p.getBoolean("monitor_offline_alerted", false);
        JSONObject current = w.optJSONObject("current");
        JSONObject departure = w.optJSONObject("departure");
        if (current == null) current = new JSONObject();
        if (departure == null) departure = new JSONObject();

        double score = w.optDouble("score", Double.NaN);
        String state = w.optString("state", "readiness");
        String action = w.optString("action", "Winter readiness data is available.");
        double arrivalSoc = departure.optDouble("arrival_soc", Double.NaN);
        String preconditionKey = jsonValue(departure.opt("precondition_start_ts"));
        int preconditionMinutes = departure.optInt("precondition_minutes", 0);
        boolean heaterOn = current.optBoolean("heater_on", false);

        SharedPreferences.Editor e = p.edit()
                .putInt("monitor_fail_count", 0)
                .putBoolean("monitor_offline_alerted", false)
                .putLong("last_monitor_at", System.currentTimeMillis())
                .putString("last_monitor_status", "OK")
                .putString("last_monitor_error", "")
                .putString("last_monitor_url", base);
        if (!Double.isNaN(score)) e.putFloat("last_monitor_score", (float) score);
        if (!Double.isNaN(arrivalSoc)) e.putFloat("last_monitor_arrival_soc", (float) arrivalSoc);
        e.apply();

        if (wasOffline && p.getBoolean("alert_connection", true)) {
            NotificationCenter.post(
                    context,
                    1102,
                    "Tesla Intelligence Core connection restored",
                    "Background monitoring is connected again through " + host(base) + ".",
                    "morning"
            );
        }

        if (manual) {
            String summary = Double.isNaN(score)
                    ? "Connected to " + host(base) + "."
                    : "Connected to " + host(base) + ". Winter readiness is " + Math.round(score) + ".";
            NotificationCenter.post(context, 1100, "Background check passed", summary, "morning");
        }

        if (p.getBoolean("alert_readiness", true) && !Double.isNaN(score)) {
            int threshold = p.getInt("readiness_threshold", 70);
            boolean low = score < threshold;
            boolean wasLow = p.getBoolean("monitor_readiness_low", false);

            if (low && !wasLow) {
                NotificationCenter.post(
                        context,
                        1110,
                        "Winter readiness dropped to " + Math.round(score),
                        state.toUpperCase() + " • " + action,
                        "morning"
                );
            } else if (!low && wasLow) {
                NotificationCenter.post(
                        context,
                        1111,
                        "Winter readiness recovered",
                        "Winter readiness is back to " + Math.round(score) + ".",
                        "morning"
                );
            }
            p.edit().putBoolean("monitor_readiness_low", low).apply();
        }

        if (p.getBoolean("alert_arrival_soc", true) && !Double.isNaN(arrivalSoc)) {
            int threshold = p.getInt("arrival_soc_threshold", 20);
            boolean low = arrivalSoc < threshold;
            boolean wasLow = p.getBoolean("monitor_arrival_low", false);

            if (low && !wasLow) {
                NotificationCenter.post(
                        context,
                        1120,
                        "Projected arrival SOC is low",
                        "Projected arrival is " + Math.round(arrivalSoc) + "%, below your " + threshold + "% alert level.",
                        "morning"
                );
            } else if (!low && wasLow) {
                NotificationCenter.post(
                        context,
                        1121,
                        "Projected arrival SOC recovered",
                        "Projected arrival is back to " + Math.round(arrivalSoc) + "%.",
                        "morning"
                );
            }
            p.edit().putBoolean("monitor_arrival_low", low).apply();
        }

        if (p.getBoolean("alert_warmup", true)) {
            String last = p.getString("monitor_last_precondition", "");
            if (!preconditionKey.isEmpty() && !preconditionKey.equals(last)) {
                String msg = preconditionMinutes > 0
                        ? "GHOST recommends about " + preconditionMinutes + " minutes of warm-up before the learned departure."
                        : "GHOST now recommends battery warm-up before the learned departure.";
                NotificationCenter.post(context, 1130, "Warm-up recommended", msg, "morning");
            }
            p.edit().putString("monitor_last_precondition", preconditionKey).apply();
        }

        if (p.getBoolean("alert_heater", false)) {
            boolean prev = p.getBoolean("monitor_heater_on", false);
            if (heaterOn && !prev) {
                NotificationCenter.post(
                        context,
                        1140,
                        "Battery heater active",
                        "The direct battery-heater sensor is reporting ON.",
                        "morning"
                );
            }
            p.edit().putBoolean("monitor_heater_on", heaterOn).apply();
        }
    }

    private static String jsonValue(Object value) {
        if (value == null || value == JSONObject.NULL) return "";
        String s = String.valueOf(value).trim();
        return "null".equalsIgnoreCase(s) ? "" : s;
    }

    private static String shortError(Exception e) {
        String s = e.getMessage();
        if (s == null || s.isEmpty()) s = e.getClass().getSimpleName();
        return s.length() > 160 ? s.substring(0, 160) : s;
    }

    private static String host(String base) {
        try {
            String h = new URL(base).getHost();
            return h == null || h.isEmpty() ? base : h;
        } catch (Exception e) {
            return base;
        }
    }
}
