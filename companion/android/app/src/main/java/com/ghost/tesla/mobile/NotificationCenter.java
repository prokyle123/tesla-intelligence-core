package com.ghost.tesla.mobile;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;

public final class NotificationCenter {
    public static final String CHANNEL_ALERTS = "tic_alerts";
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
