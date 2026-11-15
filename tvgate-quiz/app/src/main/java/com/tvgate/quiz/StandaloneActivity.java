package com.tvgate.quiz;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
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
 * 桌面入口：显示管理端网址和二维码，手机扫码即可打开家长后台。
 * App 不隐藏，开机后用户点开这个界面就能看到地址。
 */
public class StandaloneActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 确保后端服务在运行
        Intent svc = new Intent(this, StandaloneService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }

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

        setContentView(root);
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
