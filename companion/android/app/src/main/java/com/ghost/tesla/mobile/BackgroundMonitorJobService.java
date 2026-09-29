package com.ghost.tesla.mobile;

import android.app.job.JobParameters;
import android.app.job.JobService;
import android.content.Context;
import android.content.SharedPreferences;
import android.webkit.CookieManager;

import org.json.JSONArray;
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
        c.setRequestProperty("User-Agent", "TIC-Companion-Background/0.9.5");
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
        NotificationCenter.updateStatusFromCache(context);

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

        double currentSoc = current.optDouble("soc", Double.NaN);
        double packF = current.optDouble("pack_f", Double.NaN);
        double moduleSpreadF = current.optDouble("module_spread_f", Double.NaN);
        double outsideF = current.optDouble("outside_f", Double.NaN);

        double pack6hF = Double.NaN;
        double outside6hF = Double.NaN;
        JSONArray forecast = w.optJSONArray("forecast");
        if (forecast != null) {
            for (int i = 0; i < forecast.length(); i++) {
                JSONObject row = forecast.optJSONObject(i);
                if (row == null || row.optInt("hours", -1) != 6) continue;
                pack6hF = row.optDouble("pack_f", Double.NaN);
                outside6hF = row.optDouble("outside_f", Double.NaN);
                break;
            }
        }

        double departureSoc = departure.optDouble("departure_soc", Double.NaN);
        double arrivalSoc = departure.optDouble("arrival_soc", Double.NaN);
        double departurePackF = departure.optDouble("departure_pack_f", Double.NaN);

        String preconditionKey = jsonValue(departure.opt("precondition_start_ts"));
        double preconditionStartTs = departure.optDouble("precondition_start_ts", Double.NaN);
        int preconditionMinutes = departure.optInt("precondition_minutes", 0);
        String preconditionSource = departure.optString("precondition_source_label", departure.optString("precondition_source", ""));
        String preconditionConfidence = departure.optString("precondition_confidence", "");
        double preconditionExpectedPackF = departure.optDouble("precondition_expected_pack_f", Double.NaN);
        double preconditionTargetPackF = departure.optDouble("precondition_target_pack_f", Double.NaN);
        boolean heaterOn = current.optBoolean("heater_on", false);
        boolean preconditioning = current.optBoolean("preconditioning", false);
        long dataAt = System.currentTimeMillis();

        SharedPreferences.Editor e = p.edit()
                .putInt("monitor_fail_count", 0)
                .putBoolean("monitor_offline_alerted", false)
                .putLong("last_monitor_at", dataAt)
                .putLong("last_monitor_data_at", dataAt)
                .putString("last_monitor_status", "OK")
                .putString("last_monitor_state", state)
                .putString("last_monitor_error", "")
                .putString("last_monitor_url", base)
                .putBoolean("last_monitor_heater_on", heaterOn)
                .putBoolean("last_monitor_preconditioning", preconditioning);
        if (!Double.isNaN(score)) e.putFloat("last_monitor_score", (float) score);
        if (!Double.isNaN(currentSoc)) e.putFloat("last_monitor_current_soc", (float) currentSoc);
        if (!Double.isNaN(departureSoc)) e.putFloat("last_monitor_departure_soc", (float) departureSoc);
        if (!Double.isNaN(arrivalSoc)) e.putFloat("last_monitor_arrival_soc", (float) arrivalSoc);
        if (!Double.isNaN(packF)) e.putFloat("last_monitor_pack_f", (float) packF);
        if (!Double.isNaN(departurePackF)) e.putFloat("last_monitor_departure_pack_f", (float) departurePackF);
        if (!Double.isNaN(moduleSpreadF)) e.putFloat("last_monitor_module_spread_f", (float) moduleSpreadF);
        if (!Double.isNaN(outsideF)) e.putFloat("last_monitor_outside_f", (float) outsideF);
        if (!Double.isNaN(pack6hF)) e.putFloat("last_monitor_pack_6h_f", (float) pack6hF);
        else e.remove("last_monitor_pack_6h_f");
        if (!Double.isNaN(outside6hF)) e.putFloat("last_monitor_outside_6h_f", (float) outside6hF);
        else e.remove("last_monitor_outside_6h_f");
        if (!Double.isNaN(preconditionStartTs)) e.putLong("last_monitor_precondition_start_ms", (long) (preconditionStartTs * 1000.0));
        else e.remove("last_monitor_precondition_start_ms");
        e.putInt("last_monitor_precondition_minutes", Math.max(0, preconditionMinutes));
        e.putString("last_monitor_precondition_source", preconditionSource == null ? "" : preconditionSource);
        e.putString("last_monitor_precondition_confidence", preconditionConfidence == null ? "" : preconditionConfidence);
        if (!Double.isNaN(preconditionExpectedPackF)) e.putFloat("last_monitor_precondition_expected_pack_f", (float) preconditionExpectedPackF);
        else e.remove("last_monitor_precondition_expected_pack_f");
        if (!Double.isNaN(preconditionTargetPackF)) e.putFloat("last_monitor_precondition_target_pack_f", (float) preconditionTargetPackF);
        else e.remove("last_monitor_precondition_target_pack_f");
        e.apply();

        NotificationCenter.updateStatus(
                context, "OK", score, state, currentSoc, packF, pack6hF,
                outsideF, outside6hF, heaterOn, preconditioning,
                Double.isNaN(preconditionStartTs) ? 0L : (long) (preconditionStartTs * 1000.0),
                preconditionMinutes, preconditionSource, preconditionConfidence,
                preconditionExpectedPackF, preconditionTargetPackF, dataAt
        );

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

        thresholdLowPercent(
                context, p, "alert_current_soc", "current_soc_threshold",
                "monitor_current_soc_low", currentSoc, 20,
                1120, 1121,
                "Current SOC is low",
                "Current SOC recovered",
                "Current battery SOC",
                "morning"
        );

        thresholdLowPercent(
                context, p, "alert_departure_soc", "departure_soc_threshold",
                "monitor_departure_soc_low", departureSoc, 70,
                1122, 1123,
                "Projected departure SOC is low",
                "Projected departure SOC recovered",
                "Projected departure SOC",
                "morning"
        );

        thresholdLowPercent(
                context, p, "alert_arrival_soc", "arrival_soc_threshold",
                "monitor_arrival_low", arrivalSoc, 20,
                1124, 1125,
                "Projected arrival SOC is low",
                "Projected arrival SOC recovered",
                "Projected arrival SOC",
                "morning"
        );

        thresholdLowTemp(
                context, p, "alert_pack_temp", "pack_temp_threshold_f",
                "monitor_pack_temp_low", packF, 40,
                1150, 1151,
                "Battery pack is cold",
                "Battery pack temperature recovered",
                "Current pack temperature",
                "thermal"
        );

        thresholdLowTemp(
                context, p, "alert_departure_pack", "departure_pack_threshold_f",
                "monitor_departure_pack_low", departurePackF, 45,
                1152, 1153,
                "Projected departure pack temperature is low",
                "Projected departure pack temperature recovered",
                "Projected departure pack temperature",
                "morning"
        );

        thresholdHighTemp(
                context, p, "alert_module_spread", "module_spread_threshold_f",
                "monitor_module_spread_high", moduleSpreadF, 8,
                1160, 1161,
                "Battery module spread is high",
                "Battery module spread recovered",
                "Current module temperature spread",
                "thermal"
        );

        thresholdLowTemp(
                context, p, "alert_outside_temp", "outside_temp_threshold_f",
                "monitor_outside_temp_low", outsideF, 20,
                1170, 1171,
                "Outside temperature crossed your cold limit",
                "Outside temperature recovered",
                "Outside temperature",
                "morning"
        );

        if (p.getBoolean("alert_warmup", true)) {
            String last = p.getString("monitor_last_precondition", "");
            if (!preconditionKey.isEmpty() && !preconditionKey.equals(last)) {
                String msg = preconditionMinutes > 0
                        ? "GHOST recommends about " + preconditionMinutes + " minutes of warm-up before the learned departure." +
                          ((!Double.isNaN(preconditionExpectedPackF) && !Double.isNaN(preconditionTargetPackF))
                                  ? " Expected pack " + Math.round(preconditionExpectedPackF) + "°F → " + Math.round(preconditionTargetPackF) + "°F." : "")
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

    private static void thresholdLowPercent(
            Context context, SharedPreferences p,
            String enabledKey, String thresholdKey, String stateKey,
            double value, int defaultThreshold,
            int alertId, int recoveryId,
            String alertTitle, String recoveryTitle,
            String metricLabel, String view
    ) {
        if (!p.getBoolean(enabledKey, false) || Double.isNaN(value)) return;
        int threshold = p.getInt(thresholdKey, defaultThreshold);
        boolean active = value < threshold;
        boolean previous = p.getBoolean(stateKey, false);

        if (active && !previous) {
            NotificationCenter.post(
                    context, alertId, alertTitle,
                    metricLabel + " is " + Math.round(value) + "%, below your " + threshold + "% limit.",
                    view
            );
        } else if (!active && previous) {
            NotificationCenter.post(
                    context, recoveryId, recoveryTitle,
                    metricLabel + " is back to " + Math.round(value) + "%.",
                    view
            );
        }
        p.edit().putBoolean(stateKey, active).apply();
    }

    private static void thresholdLowTemp(
            Context context, SharedPreferences p,
            String enabledKey, String thresholdKey, String stateKey,
            double value, int defaultThreshold,
            int alertId, int recoveryId,
            String alertTitle, String recoveryTitle,
            String metricLabel, String view
    ) {
        if (!p.getBoolean(enabledKey, false) || Double.isNaN(value)) return;
        int threshold = p.getInt(thresholdKey, defaultThreshold);
        boolean active = value < threshold;
        boolean previous = p.getBoolean(stateKey, false);

        if (active && !previous) {
            NotificationCenter.post(
                    context, alertId, alertTitle,
                    metricLabel + " is " + Math.round(value) + "°F, below your " + threshold + "°F limit.",
                    view
            );
        } else if (!active && previous) {
            NotificationCenter.post(
                    context, recoveryId, recoveryTitle,
                    metricLabel + " is back to " + Math.round(value) + "°F.",
                    view
            );
        }
        p.edit().putBoolean(stateKey, active).apply();
    }

    private static void thresholdHighTemp(
            Context context, SharedPreferences p,
            String enabledKey, String thresholdKey, String stateKey,
            double value, int defaultThreshold,
            int alertId, int recoveryId,
            String alertTitle, String recoveryTitle,
            String metricLabel, String view
    ) {
        if (!p.getBoolean(enabledKey, false) || Double.isNaN(value)) return;
        int threshold = p.getInt(thresholdKey, defaultThreshold);
        boolean active = value > threshold;
        boolean previous = p.getBoolean(stateKey, false);

        if (active && !previous) {
            NotificationCenter.post(
                    context, alertId, alertTitle,
                    metricLabel + " is " + Math.round(value) + "°F, above your " + threshold + "°F limit.",
                    view
            );
        } else if (!active && previous) {
            NotificationCenter.post(
                    context, recoveryId, recoveryTitle,
                    metricLabel + " is back to " + Math.round(value) + "°F.",
                    view
            );
        }
        p.edit().putBoolean(stateKey, active).apply();
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
