package com.tvgate.quiz;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.StateListDrawable;
import android.media.AudioManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * 全屏答题界面。本身不存题目，只负责显示和提交；
 * 计时、判题、题库、统计都在树莓派的 tvgate 控制器上。
 *
 * 启动参数：
 *   --es server  http://<树莓派IP>:8765
 *   --es session <本次会话ID>
 */
public class QuizActivity extends Activity {

    private String server = "";
    private String session = "default";
    private SharedPreferences prefs;

    private final Handler ui = new Handler(Looper.getMainLooper());

    private LinearLayout optionsBox;
    private TextView stemView;
    private TextView metaView;
    private TextView messageView;
    private TextView countdownView;

    private JSONObject current;
    private int timeLeft;
    private int lastChoice = -1;
    private boolean locked;
    private boolean finished;
    private long shownAt;
    private Runnable ticker;

    private AudioManager audioManager;
    private AudioManager.OnAudioFocusChangeListener focusListener;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        hideSystemBars();

        prefs = getSharedPreferences("tvgate", MODE_PRIVATE);
        String extraServer = getIntent().getStringExtra("server");
        if (!TextUtils.isEmpty(extraServer)) {
            server = extraServer;
            prefs.edit().putString("server", server).apply();
        } else {
            server = prefs.getString("server", "");
        }
        String extraSession = getIntent().getStringExtra("session");
        if (!TextUtils.isEmpty(extraSession)) {
            session = extraSession;
        }

        // 抢音频焦点，让正在播放的视频 App 自己暂停（云视听等不响应媒体键的 App 走这条路）。
        audioManager = (AudioManager) getSystemService(AUDIO_SERVICE);
        focusListener = change -> { };
        audioManager.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);

        buildUi();
        if (TextUtils.isEmpty(server)) {
            showServerDialog(true);
        } else {
            loadCurrent();
        }
    }

    @Override
    protected void onDestroy() {
        if (audioManager != null && focusListener != null) {
            audioManager.abandonAudioFocus(focusListener);
        }
        super.onDestroy();
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemBars();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemBars();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String extraServer = intent.getStringExtra("server");
        if (!TextUtils.isEmpty(extraServer)) {
            server = extraServer;
            prefs.edit().putString("server", server).apply();
        }
        String extraSession = intent.getStringExtra("session");
        if (!TextUtils.isEmpty(extraSession)) {
            session = extraSession;
        }
        loadCurrent();
    }

    @Override
    public void onBackPressed() {
        // 必须答完才能退出；Home 键由树莓派控制器兜底。
    }

    private void hideSystemBars() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics());
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0B0D12"));
        root.setPadding(dp(72), dp(44), dp(72), dp(44));

        metaView = new TextView(this);
        metaView.setTextColor(Color.parseColor("#7F8EA3"));
        metaView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        root.addView(metaView);

        stemView = new TextView(this);
        stemView.setTextColor(Color.parseColor("#F2F5F9"));
        stemView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 32);
        stemView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        stemView.setPadding(0, dp(22), 0, dp(26));
        root.addView(stemView);

        optionsBox = new LinearLayout(this);
        optionsBox.setOrientation(LinearLayout.VERTICAL);
        root.addView(optionsBox, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        messageView = new TextView(this);
        messageView.setTextColor(Color.WHITE);
        messageView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        root.addView(messageView);

        countdownView = new TextView(this);
        countdownView.setTextColor(Color.parseColor("#7F8EA3"));
        countdownView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        countdownView.setPadding(0, dp(6), 0, 0);
        root.addView(countdownView);

        Button exitButton = new Button(this);
        exitButton.setText("家长退出");
        exitButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        exitButton.setTextColor(Color.parseColor("#8b95a5"));
        exitButton.setBackground(optionBackground());
        exitButton.setPadding(dp(18), dp(6), dp(18), dp(6));
        exitButton.setOnClickListener(v -> showExitDialog());
        exitButton.setOnLongClickListener(v -> {
            showServerDialog(false);
            return true;
        });
        LinearLayout.LayoutParams exitLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        exitLp.gravity = Gravity.END;
        exitLp.topMargin = dp(8);
        root.addView(exitButton, exitLp);

        setContentView(root);
    }

    private Drawable optionBackground() {
        StateListDrawable drawable = new StateListDrawable();
        drawable.addState(new int[]{android.R.attr.state_focused},
                new ColorDrawable(Color.parseColor("#2A4A7F")));
        drawable.addState(new int[]{android.R.attr.state_pressed},
                new ColorDrawable(Color.parseColor("#3D7DF6")));
        drawable.addState(new int[]{}, new ColorDrawable(Color.parseColor("#1C2230")));
        return drawable;
    }

    private void loadCurrent() {
        if (TextUtils.isEmpty(server)) {
            showServerDialog(true);
            return;
        }
        setMessage("正在连接 " + server + " …", "#7F8EA3");
        new Thread(() -> {
            try {
                String body = get(server + "/api/quiz/current?session=" + session);
                JSONObject resp = new JSONObject(body);
                ui.post(() -> render(resp));
            } catch (Exception e) {
                ui.post(() -> {
                    setMessage("连接失败：" + e.getMessage() + "，3 秒后重试", "#FF8A8A");
                    ui.postDelayed(this::loadCurrent, 3000);
                });
            }
        }).start();
    }

    private void render(JSONObject resp) {
        try {
            if (resp.optBoolean("finished", false)) {
                finished = true;
                setMessage("检查结束", "#7F8EA3");
                ui.postDelayed(this::finish, 800);
                return;
            }

            current = resp.getJSONObject("question");
            timeLeft = resp.optInt("timeout", 120);
            locked = false;
            finished = false;
            lastChoice = -1;
            shownAt = System.currentTimeMillis();

            int need = resp.optInt("need", 1);
            int done = resp.optInt("done", 0);
            String mode = resp.optString("mode", "quiz");
            String meta;
            if ("drill".equals(mode)) {
                meta = "刷题模式 · 已答 " + resp.optInt("drill_count", 0) + " 题";
            } else {
                meta = "检查点 " + resp.optInt("block", 1)
                        + " · 难度 " + resp.optInt("difficulty", 1)
                        + "/" + resp.optInt("max", 5);
                if (need > 1) {
                    meta += " · 已答对 " + done + "/" + need;
                }
            }
            metaView.setText(meta);
            stemView.setText(current.getString("stem"));
            setMessage("", "#FFFFFF");

            optionsBox.removeAllViews();
            JSONArray options = current.getJSONArray("options");
            for (int i = 0; i < options.length(); i++) {
                final int index = i;
                Button button = new Button(this);
                button.setText((i + 1) + ".  " + options.getString(i));
                button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 23);
                button.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
                button.setPadding(dp(24), dp(12), dp(24), dp(12));
                button.setAllCaps(false);
                button.setBackground(optionBackground());
                button.setTextColor(Color.parseColor("#E6EBF2"));
                button.setOnClickListener(v -> submit(index));

                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
                lp.bottomMargin = dp(12);
                optionsBox.addView(button, lp);
            }
            if (optionsBox.getChildCount() > 0) {
                optionsBox.getChildAt(0).requestFocus();
            }
            startCountdown();
        } catch (Exception e) {
            setMessage("数据格式错误：" + e.getMessage(), "#FF8A8A");
        }
    }

    private void startCountdown() {
        if (ticker != null) {
            ui.removeCallbacks(ticker);
        }
        ticker = new Runnable() {
            @Override
            public void run() {
                if (locked || finished) {
                    return;
                }
                timeLeft -= 1;
                countdownView.setText("剩余 " + Math.max(0, timeLeft) + " 秒");
                if (timeLeft <= 0) {
                    submit(-1);
                } else {
                    ui.postDelayed(this, 1000);
                }
            }
        };
        countdownView.setText("剩余 " + timeLeft + " 秒");
        ui.postDelayed(ticker, 1000);
    }

    private void submit(int choice) {
        if (locked || finished || current == null) {
            return;
        }
        locked = true;
        lastChoice = choice;
        if (ticker != null) {
            ui.removeCallbacks(ticker);
        }
        int elapsed = (int) (System.currentTimeMillis() - shownAt);
        String questionId;
        try {
            questionId = current.getString("id");
        } catch (Exception e) {
            questionId = "";
        }

        setMessage(choice < 0 ? "时间到，正在换题…" : "提交中…", "#FFC46B");
        final String qid = questionId;
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("session", session);
                body.put("question_id", qid);
                body.put("choice", choice);
                body.put("timeout", choice < 0);
                body.put("elapsed_ms", elapsed);
                String respText = post(server + "/api/quiz/answer", body.toString());
                JSONObject resp = new JSONObject(respText);
                ui.post(() -> handleAnswer(resp));
            } catch (Exception e) {
                ui.post(() -> {
                    locked = false;
                    setMessage("提交失败，请重试：" + e.getMessage(), "#FF8A8A");
                    ui.postDelayed(ticker, 1000);
                });
            }
        }).start();
    }

    private void handleAnswer(JSONObject resp) {
        boolean correct = resp.optBoolean("correct", false);
        int answer = resp.optInt("answer", -1);

        if (correct) {
            JSONObject next = resp.optJSONObject("next");
            if (next != null) {
                setMessage(resp.optString("message", "答对了，继续下一题"), "#61D095");
                markOptions(answer, -1);
                ui.postDelayed(() -> render(next), 900);
                return;
            }
            setMessage("✔ 答对了，继续观看", "#61D095");
            markOptions(answer, -1);
            finished = true;
            ui.postDelayed(this::finish, 1500);
            return;
        }

        setMessage(resp.optString("message", "✘ 答错了，换一道同难度的题"), "#FF8A8A");
        markOptions(answer, lastChoice);

        JSONObject next = resp.optJSONObject("next");
        if (resp.optBoolean("finished", false) || next == null) {
            finished = true;
            ui.postDelayed(this::finish, 1500);
        } else {
            ui.postDelayed(() -> render(next), 1300);
        }
    }

    private void markOptions(int correctIdx, int chosenIdx) {
        for (int i = 0; i < optionsBox.getChildCount(); i++) {
            View child = optionsBox.getChildAt(i);
            if (i == correctIdx) {
                child.setBackgroundColor(Color.parseColor("#1F6F43"));
            } else if (i == chosenIdx) {
                child.setBackgroundColor(Color.parseColor("#7A2B2B"));
            }
        }
    }

    private void setMessage(String text, String color) {
        messageView.setText(text);
        messageView.setTextColor(Color.parseColor(color));
    }

    private void showServerDialog(boolean firstRun) {
        EditText input = new EditText(this);
        input.setText(server);
        input.setHint("http://192.168.1.10:8765");
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        input.setPadding(dp(16), dp(10), dp(16), dp(10));

        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle("服务器地址")
                .setMessage("填写运行 tvgate 控制器的地址。示例：http://192.168.1.10:8765")
                .setView(input)
                .setPositiveButton("保存", null);
        if (!firstRun) {
            builder.setNegativeButton("取消", null);
        }
        AlertDialog dialog = builder.create();
        dialog.setCancelable(!firstRun);
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String url = input.getText().toString().trim();
                if (url.endsWith("/")) {
                    url = url.substring(0, url.length() - 1);
                }
                if (!url.startsWith("http://") && !url.startsWith("https://")) {
                    Toast.makeText(this, "地址要以 http:// 开头", Toast.LENGTH_SHORT).show();
                    return;
                }
                server = url;
                prefs.edit().putString("server", server).apply();
                dialog.dismiss();
                loadCurrent();
            });
            input.requestFocus();
        });
        dialog.show();
    }

    private void showExitDialog() {
        EditText input = new EditText(this);
        input.setHint("请输入家长 PIN");
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        input.setPadding(dp(16), dp(10), dp(16), dp(10));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("家长退出")
                .setMessage("输入 PIN 后可退出答题并暂停管控。")
                .setView(input)
                .setPositiveButton("确认", null)
                .setNegativeButton("取消", null)
                .create();
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String pin = input.getText().toString().trim();
                if (pin.isEmpty()) {
                    Toast.makeText(this, "请输入 PIN", Toast.LENGTH_SHORT).show();
                    return;
                }
                exitWithPin(pin, dialog, input);
            });
            input.requestFocus();
        });
        dialog.show();
    }

    private void exitWithPin(String pin, AlertDialog dialog, EditText input) {
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("pin", pin);
                String respText = post(server + "/api/quiz/exit", body.toString());
                JSONObject resp = new JSONObject(respText);
                ui.post(() -> {
                    if (resp.optBoolean("ok", false)) {
                        int minutes = resp.optInt("minutes", 30);
                        dialog.dismiss();
                        Toast.makeText(this, "已退出，家长模式 " + minutes + " 分钟",
                                Toast.LENGTH_LONG).show();
                        finished = true;
                        finish();
                    } else {
                        Toast.makeText(this, resp.optString("error", "密码错误"),
                                Toast.LENGTH_SHORT).show();
                        input.setText("");
                        input.requestFocus();
                    }
                });
            } catch (Exception e) {
                ui.post(() -> Toast.makeText(this, "连接失败：" + e.getMessage(),
                        Toast.LENGTH_LONG).show());
            }
        }).start();
    }

    private String get(String urlText) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setConnectTimeout(3000);
        connection.setReadTimeout(5000);
        try (InputStream in = connection.getInputStream()) {
            return readAll(in);
        } finally {
            connection.disconnect();
        }
    }

    private String post(String urlText, String body) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(3000);
        connection.setReadTimeout(5000);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");

        byte[] data = body.getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(data.length);
        try (OutputStream out = connection.getOutputStream()) {
            out.write(data);
        }
        try (InputStream in = connection.getInputStream()) {
            return readAll(in);
        } finally {
            connection.disconnect();
        }
    }

    private String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = in.read(chunk)) > 0) {
            buffer.write(chunk, 0, n);
        }
        return new String(buffer.toByteArray(), StandardCharsets.UTF_8);
    }
}
