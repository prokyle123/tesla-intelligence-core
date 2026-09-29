package com.ghost.tesla.mobile;

import android.Manifest;
import android.app.*;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public final class NotificationCenter {
    public static final String CHANNEL_ALERTS = "tic_alerts";
    public static final String CHANNEL_STATUS = "tic_status_v1";
    public static final int STATUS_NOTIFICATION_ID = 1080;
    public static final int JOB_ID = 0x544943;
    public static final long INTERVAL_MS = 15L * 60L * 1000L;

    private NotificationCenter() {}

    public static void ensureChannels(Context context) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null) return;

        NotificationChannel alerts = new NotificationChannel(
                CHANNEL_ALERTS,
                "Tesla Intelligence alerts",
                NotificationManager.IMPORTANCE_HIGH
        );
        alerts.setDescription("Winter readiness, charging/departure, connection and warm-up alerts.");
        alerts.enableVibration(true);
        nm.createNotificationChannel(alerts);

        NotificationChannel status = new NotificationChannel(
                CHANNEL_STATUS,
                "GHOST winter status",
                NotificationManager.IMPORTANCE_LOW
        );
        status.setDescription("Persistent Winter Readiness, battery temperature and forecast status.");
        status.setSound(null, null);
        status.enableVibration(false);
        status.setShowBadge(false);
        nm.createNotificationChannel(status);
    }

    public static boolean hasPermission(Context context) {
        if (Build.VERSION.SDK_INT < 33) return true;
        return context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static void schedule(Context context) {
        SharedPreferences p = context.getSharedPreferences("ghost", Context.MODE_PRIVATE);
        if (!p.getBoolean("notifications_enabled", true)) {
            cancelSchedule(context);
            return;
        }

        ensureChannels(context);
        updateStatusFromCache(context);

        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;

        ComponentName component = new ComponentName(context, BackgroundMonitorJobService.class);
        JobInfo job = new JobInfo.Builder(JOB_ID, component)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .setPeriodic(INTERVAL_MS)
                .setBackoffCriteria(60_000L, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .build();

        js.schedule(job);
    }

    public static void cancelSchedule(Context context) {
        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js != null) js.cancel(JOB_ID);

        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(STATUS_NOTIFICATION_ID);
    }

    public static void runCheckNow(Context context) {
        BackgroundMonitorJobService.runImmediate(context.getApplicationContext());
    }

    public static void post(Context context, int id, String title, String text, String view) {
        if (!hasPermission(context)) return;
        ensureChannels(context);

        Intent intent = new Intent(context, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (view != null && !view.isEmpty()) intent.putExtra("tic_view", view);

        PendingIntent pi = PendingIntent.getActivity(
                context,
                id,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, CHANNEL_ALERTS)
                : new Notification.Builder(context);

        b.setSmallIcon(android.R.drawable.stat_notify_more)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setOnlyAlertOnce(true);

        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(id, b.build());
    }

    public static void updateStatusFromCache(Context context) {
        SharedPreferences p = context.getSharedPreferences("ghost", Context.MODE_PRIVATE);
        if (!p.getBoolean("notifications_enabled", true)) {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.cancel(STATUS_NOTIFICATION_ID);
            return;
        }

        updateStatus(
                context,
                p.getString("last_monitor_status", "WAITING"),
                p.getFloat("last_monitor_score", Float.NaN),
                p.getString("last_monitor_state", ""),
                p.getFloat("last_monitor_current_soc", Float.NaN),
                p.getFloat("last_monitor_pack_f", Float.NaN),
                p.getFloat("last_monitor_pack_6h_f", Float.NaN),
                p.getFloat("last_monitor_outside_f", Float.NaN),
                p.getFloat("last_monitor_outside_6h_f", Float.NaN),
                p.getBoolean("last_monitor_heater_on", false),
                p.getBoolean("last_monitor_preconditioning", false),
                p.getLong("last_monitor_precondition_start_ms", 0L),
                p.getInt("last_monitor_precondition_minutes", 0),
                p.getString("last_monitor_precondition_source", ""),
                p.getString("last_monitor_precondition_confidence", ""),
                p.getFloat("last_monitor_precondition_expected_pack_f", Float.NaN),
                p.getFloat("last_monitor_precondition_target_pack_f", Float.NaN),
                p.getLong("last_monitor_data_at", p.getLong("last_monitor_at", 0L))
        );
    }

    public static void updateStatus(
            Context context,
            String monitorStatus,
            double score,
            String state,
            double currentSoc,
            double packF,
            double pack6hF,
            double outsideF,
            double outside6hF,
            boolean heaterOn,
            boolean preconditioning,
            long preconditionStartMs,
            int preconditionMinutes,
            String preconditionSource,
            String preconditionConfidence,
            double preconditionExpectedPackF,
            double preconditionTargetPackF,
            long updatedAt
    ) {
        if (!hasPermission(context)) return;

        SharedPreferences p = context.getSharedPreferences("ghost", Context.MODE_PRIVATE);
        if (!p.getBoolean("notifications_enabled", true)) return;

        ensureChannels(context);

        Intent intent = new Intent(context, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("tic_view", "morning");

        PendingIntent pi = PendingIntent.getActivity(
                context,
                STATUS_NOTIFICATION_ID,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        boolean offline = "OFFLINE".equalsIgnoreCase(monitorStatus);
        boolean waiting = Double.isNaN(score) && Double.isNaN(packF) && Double.isNaN(currentSoc);

        String stateLabel = state == null ? "" : state.trim().toUpperCase(Locale.US);
        String title;
        if (offline) {
            title = "GHOST Winter • OFFLINE";
        } else if (!Double.isNaN(score)) {
            title = "GHOST Winter • " + Math.round(score) + "/100" +
                    (stateLabel.isEmpty() ? "" : " " + stateLabel);
        } else {
            title = "GHOST Winter • MONITORING";
        }

        String compact;
        if (waiting) {
            compact = "Waiting for the first winter-readiness sample";
        } else {
            compact = "Pack " + temp(packF) + " • 6h " + temp(pack6hF) + " • SOC " + percent(currentSoc);
        }

        Notification.InboxStyle style = new Notification.InboxStyle();
        if (waiting) {
            style.addLine("Background monitor is active.");
            style.addLine("Winter data will appear after the next successful check.");
        } else {
            style.addLine("Battery " + temp(packF) + " → " + temp(pack6hF) + " in 6h");
            style.addLine("SOC " + percent(currentSoc) + " • Outside " + temp(outsideF) + " → " + temp(outside6hF));
        }

        if (preconditionMinutes > 0) {
            String when = preconditionStartMs > 0
                    ? new SimpleDateFormat("h:mm a", Locale.getDefault()).format(new Date(preconditionStartMs))
                    : "departure";
            String warm = "Warm-up ~" + preconditionMinutes + " min • start " + when;
            if (!Double.isNaN(preconditionExpectedPackF) && !Double.isNaN(preconditionTargetPackF)) {
                warm += " • " + temp(preconditionExpectedPackF) + " → " + temp(preconditionTargetPackF);
            }
            style.addLine(warm);
            String source = preconditionSource == null ? "" : preconditionSource.trim();
            String conf = preconditionConfidence == null ? "" : preconditionConfidence.trim();
            if (!source.isEmpty()) style.addLine(source + (conf.isEmpty() ? "" : " • " + conf.toUpperCase(Locale.US) + " confidence"));
        }

        String activity;
        if (offline) activity = "Connection unavailable";
        else if (heaterOn) activity = "Battery heater ON";
        else if (preconditioning) activity = "Preconditioning ON";
        else activity = "Background monitor active";

        String stamp = updatedAt > 0
                ? new SimpleDateFormat("h:mm a", Locale.getDefault()).format(new Date(updatedAt))
                : "not checked yet";
        style.addLine(activity + " • " + (offline ? "Last good " : "Updated ") + stamp);

        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, CHANNEL_STATUS)
                : new Notification.Builder(context);

        b.setSmallIcon(android.R.drawable.stat_notify_more)
                .setContentTitle(title)
                .setContentText(compact)
                .setStyle(style)
                .setContentIntent(pi)
                .setOngoing(true)
                .setAutoCancel(false)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setShowWhen(false);

        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(STATUS_NOTIFICATION_ID, b.build());
    }

    private static String temp(double value) {
        return Double.isNaN(value) ? "—" : Math.round(value) + "°F";
    }

    private static String percent(double value) {
        return Double.isNaN(value) ? "—" : Math.round(value) + "%";
    }

    public static void test(Context context) {
        post(
                context,
                1099,
                "Tesla Intelligence Core",
                "Notifications are working. Background monitoring will check the Pi about every 15 minutes.",
                "morning"
        );
    }
}
