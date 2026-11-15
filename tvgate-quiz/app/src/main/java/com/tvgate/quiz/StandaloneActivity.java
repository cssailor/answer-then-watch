package com.tvgate.quiz;

import android.Manifest;
import android.app.Activity;
import android.app.AppOpsManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.MultiFormatWriter;
import com.google.zxing.common.BitMatrix;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.Enumeration;

/**
 * 桌面入口：首次打开引导授予「使用情况访问权限」，授权后显示管理端网址和二维码。
 * App 不隐藏，开机后用户点开即可看到地址。
 */
public class StandaloneActivity extends Activity {

    private static final int REQ_NOTIF = 1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Intent svc = new Intent(this, StandaloneService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }

        render();
    }

    @Override
    protected void onResume() {
        super.onResume();
        render(); // 从系统设置页返回后重新检查权限并刷新界面
    }

    private boolean hasUsageStats() {
        try {
            AppOpsManager appOps = (AppOpsManager) getSystemService(APP_OPS_SERVICE);
            int mode = appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                    android.os.Process.myUid(), getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private boolean hasNotif() {
        if (Build.VERSION.SDK_INT < 33) return true;
        return checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void render() {
        if (!hasUsageStats()) {
            setContentView(buildPermissionUi());
            return;
        }
        if (!hasNotif()) {
            if (Build.VERSION.SDK_INT >= 33) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
            }
            // 通知权限不是必须的，继续显示主界面
        }
        setContentView(buildMainUi());
    }

    // ---------------------------------------------------------------- 权限引导

    private LinearLayout buildPermissionUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0B0D12"));
        root.setGravity(Gravity.CENTER);
        int pad = (int) (32 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("需要授予权限");
        title.setTextColor(Color.parseColor("#F2F5F9"));
        title.setTextSize(30);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        TextView tip = new TextView(this);
        tip.setText("答完再看需要「使用情况访问权限」，\n用来判断孩子当前正在使用哪个 App，\n以便在观看视频时按时弹出题目。\n\n" +
                "该权限只在本地使用，不会上传任何数据。");
        tip.setTextColor(Color.parseColor("#B9C5D6"));
        tip.setTextSize(20);
        tip.setGravity(Gravity.CENTER);
        tip.setPadding(0, (int) (24 * getResources().getDisplayMetrics().density), 0,
                (int) (28 * getResources().getDisplayMetrics().density));
        root.addView(tip);

        Button grant = new Button(this);
        grant.setText("去开启权限");
        grant.setTextSize(22);
        grant.setOnClickListener(v -> {
            try {
                startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
            } catch (Exception e) {
                Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                i.setData(Uri.parse("package:" + getPackageName()));
                startActivity(i);
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                (int) (280 * getResources().getDisplayMetrics().density),
                (int) (60 * getResources().getDisplayMetrics().density));
        lp.gravity = Gravity.CENTER;
        grant.setLayoutParams(lp);
        root.addView(grant);

        TextView skip = new TextView(this);
        skip.setText("跳过：将以音频播放粗略判断观看状态");
        skip.setTextColor(Color.parseColor("#6F7D90"));
        skip.setTextSize(16);
        skip.setGravity(Gravity.CENTER);
        skip.setPadding(0, (int) (20 * getResources().getDisplayMetrics().density), 0, 0);
        root.addView(skip);

        return root;
    }

    // ---------------------------------------------------------------- 主界面

    private LinearLayout buildMainUi() {
        String ip = localIp();
        String url = "http://" + ip + ":" + WebServer.PORT + "/";

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0B0D12"));
        root.setGravity(Gravity.CENTER);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("答完再看");
        title.setTextColor(Color.parseColor("#F2F5F9"));
        title.setTextSize(34);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        TextView urlView = new TextView(this);
        urlView.setText(url);
        urlView.setTextColor(Color.parseColor("#7AA7FF"));
        urlView.setTextSize(30);
        urlView.setGravity(Gravity.CENTER);
        urlView.setPadding(0, (int) (16 * getResources().getDisplayMetrics().density), 0,
                (int) (8 * getResources().getDisplayMetrics().density));
        root.addView(urlView);

        TextView tip = new TextView(this);
        tip.setText("手机连同一 WiFi，扫描二维码或输入上面网址\n即可打开家长管理后台");
        tip.setTextColor(Color.parseColor("#8B95A5"));
        tip.setTextSize(18);
        tip.setGravity(Gravity.CENTER);
        tip.setPadding(0, 0, 0, (int) (20 * getResources().getDisplayMetrics().density));
        root.addView(tip);

        ImageView qr = new ImageView(this);
        Bitmap qrBitmap = makeQr(url, 512);
        if (qrBitmap != null) {
            qr.setImageBitmap(qrBitmap);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    (int) (320 * getResources().getDisplayMetrics().density),
                    (int) (320 * getResources().getDisplayMetrics().density));
            lp.gravity = Gravity.CENTER;
            qr.setLayoutParams(lp);
        }
        root.addView(qr);

        return root;
    }

    private Bitmap makeQr(String text, int size) {
        try {
            BitMatrix matrix = new MultiFormatWriter().encode(text, BarcodeFormat.QR_CODE, size, size);
            Bitmap bmp = Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565);
            for (int x = 0; x < size; x++) {
                for (int y = 0; y < size; y++) {
                    bmp.setPixel(x, y, matrix.get(x, y) ? Color.BLACK : Color.WHITE);
                }
            }
            return bmp;
        } catch (Exception e) {
            return null;
        }
    }

    private String localIp() {
        try {
            Enumeration<NetworkInterface> en = NetworkInterface.getNetworkInterfaces();
            while (en.hasMoreElements()) {
                NetworkInterface ni = en.nextElement();
                Enumeration<java.net.InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    java.net.InetAddress a = addrs.nextElement();
                    if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                        return a.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return "127.0.0.1";
    }
}
