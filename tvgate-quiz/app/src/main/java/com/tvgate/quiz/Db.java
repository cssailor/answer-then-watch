package com.tvgate.quiz;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;

/**
 * SQLite 数据层：题库、作答、错题、设置、观看会话。
 * 表结构与 Python 版后端保持一致，管理逻辑不变。
 */
public class Db extends SQLiteOpenHelper {

    private static final int VERSION = 2;
    private static Db instance;
    private final Context ctx;

    public static synchronized Db get(Context ctx) {
        if (instance == null) {
            instance = new Db(ctx.getApplicationContext());
        }
        return instance;
    }

    private Db(Context ctx) {
        super(ctx, "tvgate.db", null, VERSION);
        this.ctx = ctx.getApplicationContext();
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS questions (" +
                "id TEXT PRIMARY KEY, subject TEXT NOT NULL, grade INTEGER DEFAULT 0," +
                " kp TEXT NOT NULL, difficulty INTEGER NOT NULL, stem TEXT NOT NULL," +
                " options TEXT NOT NULL, answer INTEGER NOT NULL, explain TEXT DEFAULT '')");
        db.execSQL("CREATE TABLE IF NOT EXISTS attempts (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, session_id TEXT," +
                " question_id TEXT, subject TEXT, kp TEXT, difficulty INTEGER," +
                " correct INTEGER NOT NULL DEFAULT 0, timed_out INTEGER NOT NULL DEFAULT 0," +
                " response_ms INTEGER)");
        db.execSQL("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS wrong_book (" +
                "question_id TEXT PRIMARY KEY, first_wrong_ts REAL, last_wrong_ts REAL," +
                " wrong_count INTEGER NOT NULL DEFAULT 0, resolved_ts REAL," +
                " review_after_ts REAL NOT NULL DEFAULT 0)");
        db.execSQL("CREATE TABLE IF NOT EXISTS view_sessions (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT, app_pkg TEXT," +
                " started_ts REAL NOT NULL, ended_ts REAL, duration_seconds INTEGER NOT NULL DEFAULT 0," +
                " updated_ts REAL NOT NULL, date TEXT NOT NULL)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_attempts_kp ON attempts(kp)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_view_sessions_date ON view_sessions(date)");
        seedSettings(db);
        loadBank(db);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // 兼容历史版本：补 review_after_ts 列
        Cursor c = db.rawQuery("PRAGMA table_info(wrong_book)", null);
        boolean hasReviewAfter = false;
        while (c.moveToNext()) {
            if ("review_after_ts".equals(c.getString(1))) hasReviewAfter = true;
        }
        c.close();
        if (!hasReviewAfter) {
            db.execSQL("ALTER TABLE wrong_book ADD COLUMN review_after_ts REAL NOT NULL DEFAULT 0");
        }
    }

    private void seedSettings(SQLiteDatabase db) {
        put(db, "interval_seconds", "600");
        put(db, "poll_seconds", "2");
        put(db, "max_difficulty", "3");
        put(db, "answer_timeout_seconds", "120");
        put(db, "quiz_enabled", "1");
        put(db, "correct_required", "1");
        put(db, "require_consecutive", "1");
        put(db, "prefer_wrong", "1");
        put(db, "wrong_review_delay_hours", "24");
        put(db, "view_gap_seconds", "180");
        put(db, "max_view_minutes", "0");
        put(db, "drill_minutes", "10");
        put(db, "cooldown_minutes", "0");
        put(db, "parent_reset_minutes", "10");
        put(db, "suspended", "0");
        put(db, "admin_pin", "1234");
    }

    private void put(SQLiteDatabase db, String key, String value) {
        ContentValues cv = new ContentValues();
        cv.put("key", key);
        cv.put("value", value);
        db.insertWithOnConflict("settings", null, cv, SQLiteDatabase.CONFLICT_IGNORE);
    }

    private void loadBank(SQLiteDatabase db) {
        Cursor c = db.rawQuery("SELECT COUNT(*) FROM questions", null);
        c.moveToFirst();
        long n = c.getLong(0);
        c.close();
        if (n > 0) return;
        try {
            InputStream in = ctx.getAssets().open("questions.json");
            byte[] buf = new byte[in.available()];
            in.read(buf);
            in.close();
            JSONObject root = new JSONObject(new String(buf, "UTF-8"));
            JSONArray arr = root.getJSONArray("questions");
            db.beginTransaction();
            try {
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject q = arr.getJSONObject(i);
                    ContentValues cv = new ContentValues();
                    cv.put("id", q.getString("id"));
                    cv.put("subject", q.optString("subject", "其他"));
                    cv.put("grade", q.optInt("grade", 0));
                    cv.put("kp", q.optString("kp", "未分类"));
                    cv.put("difficulty", q.optInt("difficulty", 1));
                    cv.put("stem", q.getString("stem"));
                    cv.put("options", q.getJSONArray("options").toString());
                    cv.put("answer", q.optInt("answer", 0));
                    cv.put("explain", q.optString("explain", ""));
                    db.insertWithOnConflict("questions", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
                }
                db.setTransactionSuccessful();
            } finally {
                db.endTransaction();
            }
        } catch (Exception e) {
            // 题库加载失败不致命，可后续通过导入补充
        }
    }

    public String get(String key, String def) {
        Cursor c = getReadableDatabase().rawQuery(
                "SELECT value FROM settings WHERE key=?", new String[]{key});
        String v = def;
        if (c.moveToFirst()) v = c.getString(0);
        c.close();
        return v;
    }

    public void set(String key, String value) {
        ContentValues cv = new ContentValues();
        cv.put("key", key);
        cv.put("value", value);
        getWritableDatabase().insertWithOnConflict("settings", null, cv,
                SQLiteDatabase.CONFLICT_REPLACE);
    }
}
