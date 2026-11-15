package com.tvgate.quiz;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * 常驻后端服务：前台服务保活，内嵌 HTTP server，本地计时并在到点时拉起答题界面。
 * 开机自启由 BootReceiver 触发。
 */
public class StandaloneService extends Service {

    private static final int NOTIF_ID = 1;
    private static final String CHANNEL_ID = "tvgate";

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

        boolean suspended = "1".equals(core.get("suspended", "0"));
        if (suspended) {
            accumulated = 0;
            return;
        }

        boolean watching = audio != null && audio.isMusicActive();
        if (watching) {
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
