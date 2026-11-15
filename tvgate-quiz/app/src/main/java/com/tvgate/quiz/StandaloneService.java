package com.tvgate.quiz;

import android.app.AppOpsManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 常驻后端服务：前台服务保活，内嵌 HTTP server，本地计时并在到点时拉起答题界面。
 * 观看判断优先用 UsageStats（精确前台 App），未授权时回退到 isMusicActive。
 */
public class StandaloneService extends Service {

    private static final int NOTIF_ID = 1;
    private static final String CHANNEL_ID = "tvgate";

    /** 桌面 / 设置 / 系统类包名：这些前台 App 不算「在看」。 */
    private static final Set<String> LAUNCHER = new HashSet<>(Arrays.asList(
            "com.tvgate.quiz",
            "com.amazon.tv.launcher", "com.amazon.venezia",
            "com.amazon.tv.settings", "com.amazon.tv.settings.v2",
            "com.amazon.device.settings", "com.amazon.tv.notificationcenter",
            "com.amazon.ftv.screensaver", "com.amazon.tv.oobe",
            "com.dangbei.tvlauncher", "com.dangbeimarket",
            "com.google.android.tvlauncher",
            "com.android.tv.settings", "com.android.settings",
            "com.android.systemui",
            "com.xiaomi.mitv.tvhome", "com.xiaomi.mitv.settings",
            "com.xiaomi.mitv.appstore"
    ));

    private Core core;
    private WebServer web;
    private Handler handler = new Handler(Looper.getMainLooper());
    private AudioManager audio;
    private double accumulated = 0;
    private long lastTick = 0;

    @Override
    public void onCreate() {
        super.onCreate();
        core = Core.get(this);
        web = new WebServer(core);
        web.start();
        audio = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        startForeground(NOTIF_ID, buildNotification());
        lastTick = System.currentTimeMillis();
        handler.post(tick);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(tick);
        web.stop();
        super.onDestroy();
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            try {
                step();
            } finally {
                handler.postDelayed(this, pollMs());
            }
        }
    };

    private int pollMs() {
        try {
            return Math.max(1000, Integer.parseInt(core.get("poll_seconds", "2")) * 1000);
        } catch (NumberFormatException e) {
            return 2000;
        }
    }

    private void step() {
        long now = System.currentTimeMillis();
        double delta = (now - lastTick) / 1000.0;
        lastTick = now;

        if ("1".equals(core.get("suspended", "0"))) {
            accumulated = 0;
            return;
        }

        if (isWatching()) {
            accumulated += delta;
            core.recordView(delta);
        }

        int interval = parseInt(core.get("interval_seconds", "600"), 600);
        if (accumulated >= interval) {
            accumulated = 0;
            if ("1".equals(core.get("quiz_enabled", "1"))) {
                launchQuiz();
            }
        }
    }

    private boolean isWatching() {
        String fg = foregroundPackage();
        if (fg != null) {
            return !isLauncher(fg);
        }
        // UsageStats 未授权时回退到音频判断
        return audio != null && audio.isMusicActive();
    }

    private boolean isLauncher(String pkg) {
        return pkg != null && LAUNCHER.contains(pkg);
    }

    // ---------------------------------------------------------------- UsageStats

    public boolean hasUsageStats() {
        try {
            AppOpsManager appOps = (AppOpsManager) getSystemService(Context.APP_OPS_SERVICE);
            int mode = appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                    android.os.Process.myUid(), getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private String foregroundPackage() {
        if (!hasUsageStats()) return null;
        try {
            UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
            long now = System.currentTimeMillis();
            String current = null;
            UsageEvents events = usm.queryEvents(now - 10 * 60 * 1000L, now);
            UsageEvents.Event e = new UsageEvents.Event();
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                int t = e.getEventType();
                if (t == UsageEvents.Event.MOVE_TO_FOREGROUND
                        || t == UsageEvents.Event.ACTIVITY_RESUMED) {
                    current = e.getPackageName();
                } else if (t == UsageEvents.Event.MOVE_TO_BACKGROUND) {
                    current = null;
                }
            }
            if (current != null) return current;
            // 事件窗口内没有前台切换：取最近使用的 App
            List<UsageStats> stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY,
                    now - 60 * 60 * 1000L, now);
            UsageStats top = null;
            for (UsageStats s : stats) {
                if (top == null || s.getLastTimeUsed() > top.getLastTimeUsed()) top = s;
            }
            if (top != null && top.getLastTimeUsed() > now - 60 * 1000L) {
                return top.getPackageName();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private void launchQuiz() {
        core.startQuiz();
        if (core.currentPayload().optBoolean("finished", true)) {
            return; // 没题可出
        }
        Intent i = new Intent(this, QuizActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        i.putExtra("server", "http://127.0.0.1:" + WebServer.PORT);
        i.putExtra("session", "standalone");
        startActivity(i);
    }

    private int parseInt(String s, int def) {
        try {
            return Integer.parseInt(s.trim());
        } catch (Exception e) {
            return def;
        }
    }

    private Notification buildNotification() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "答完再看",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("后台管控服务");
            nm.createNotificationChannel(ch);
        }
        Intent open = new Intent(this, StandaloneActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .setContentTitle("答完再看 运行中")
                .setContentText("打开 App 查看管理端地址")
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }
}
