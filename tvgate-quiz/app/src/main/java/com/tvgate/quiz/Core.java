package com.tvgate.quiz;

import android.content.Context;
import android.database.Cursor;
import android.content.ContentValues;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.concurrent.locks.ReentrantLock;

/**
 * 后端核心：出题、判题、错题、统计、报告、管理页面生成。
 * 逻辑与 Python 版保持一致。
 */
public class Core {

    private static Core instance;
    public static synchronized Core get(Context ctx) {
        if (instance == null) instance = new Core(ctx);
        return instance;
    }

    private final Db db;
    private final Random rnd = new Random();
    private final ReentrantLock lock = new ReentrantLock();

    // 当前检查点状态
    private JSONObject current;
    private int block = 0;
    private int difficulty = 1;
    private int correctCount = 0;
    private final Set<String> shown = new HashSet<>();
    private final Set<String> sessionUsed = new HashSet<>();
    private String sessionId = "";

    private Core(Context ctx) {
        db = Db.get(ctx);
    }

    // ---------------------------------------------------------------- 出题

    private JSONObject pick(int difficulty, String kp, Set<String> exclude,
                            Set<String> used, boolean preferWrong) {
        Cursor c;
        if (preferWrong) {
            String sql = "SELECT q.* FROM wrong_book w JOIN questions q ON q.id=w.question_id" +
                    " WHERE w.resolved_ts IS NULL AND q.difficulty<=?" +
                    " AND (w.review_after_ts IS NULL OR w.review_after_ts<=?)";
            List<String> args = new ArrayList<>();
            args.add(String.valueOf(difficulty));
            args.add(String.valueOf(System.currentTimeMillis() / 1000.0));
            if (kp != null) {
                sql += " AND q.kp=?";
                args.add(kp);
            }
            sql += " ORDER BY w.review_after_ts ASC, w.last_wrong_ts ASC";
            c = db.getReadableDatabase().rawQuery(sql, args.toArray(new String[0]));
            List<JSONObject> rows = toQuestions(c, exclude);
            if (!rows.isEmpty()) return rows.get(rnd.nextInt(rows.size()));
        }
        // 普通题库：同知识点优先，尽量不重复
        List<String> kpList = new ArrayList<>();
        if (kp != null) kpList.add(kp);
        kpList.add(null);
        for (String kpf : kpList) {
            String sql = kpf == null
                    ? "SELECT * FROM questions WHERE difficulty=?"
                    : "SELECT * FROM questions WHERE difficulty=? AND kp=?";
            List<String> args = new ArrayList<>();
            args.add(String.valueOf(difficulty));
            if (kpf != null) args.add(kpf);
            c = db.getReadableDatabase().rawQuery(sql, args.toArray(new String[0]));
            List<JSONObject> rows = toQuestions(c, exclude);
            List<JSONObject> fresh = new ArrayList<>();
            for (JSONObject r : rows) {
                if (!used.contains(r.optString("id"))) fresh.add(r);
            }
            if (!fresh.isEmpty()) return fresh.get(rnd.nextInt(fresh.size()));
            if (!rows.isEmpty()) return rows.get(rnd.nextInt(rows.size()));
        }
        return null;
    }

    private List<JSONObject> toQuestions(Cursor c, Set<String> exclude) {
        List<JSONObject> out = new ArrayList<>();
        while (c.moveToNext()) {
            try {
                JSONObject q = new JSONObject();
                q.put("id", c.getString(c.getColumnIndex("id")));
                q.put("subject", c.getString(c.getColumnIndex("subject")));
                q.put("kp", c.getString(c.getColumnIndex("kp")));
                q.put("difficulty", c.getInt(c.getColumnIndex("difficulty")));
                q.put("stem", c.getString(c.getColumnIndex("stem")));
                q.put("options", new JSONArray(c.getString(c.getColumnIndex("options"))));
                q.put("answer", c.getInt(c.getColumnIndex("answer")));
                q.put("explain", c.getString(c.getColumnIndex("explain")));
                if (exclude != null && exclude.contains(q.optString("id"))) continue;
                out.add(q);
            } catch (Exception ignored) {
            }
        }
        c.close();
        return out;
    }

    private int maxDifficulty() {
        try {
            return Math.max(1, Integer.parseInt(db.get("max_difficulty", "3")));
        } catch (NumberFormatException e) {
            return 3;
        }
    }

    private boolean preferWrong() {
        return "1".equals(db.get("prefer_wrong", "1"));
    }

    // ---------------------------------------------------------------- 检查点

    public synchronized void startQuiz() {
        lock.lock();
        try {
            block++;
            difficulty = Math.min(block, maxDifficulty());
            shown.clear();
            correctCount = 0;
            current = pick(difficulty, null, new HashSet<String>(), sessionUsed, preferWrong());
            if (current == null) {
                block--;
                return;
            }
            shown.add(current.optString("id"));
            sessionUsed.add(current.optString("id"));
            sessionId = "s-" + (System.currentTimeMillis() / 1000);
        } finally {
            lock.unlock();
        }
    }

    public JSONObject currentPayload() {
        lock.lock();
        try {
            if (current == null) {
                JSONObject r = new JSONObject();
                try { r.put("finished", true); } catch (Exception ignored) {}
                return r;
            }
            return payload(current, "quiz");
        } finally {
            lock.unlock();
        }
    }

    private JSONObject payload(JSONObject q, String mode) {
        JSONObject p = new JSONObject();
        try {
            int need = Math.max(1, Math.min(5, parseInt(db.get("correct_required", "1"), 1)));
            int timeout = Math.max(10, parseInt(db.get("answer_timeout_seconds", "120"), 120));
            p.put("mode", mode);
            p.put("block", block);
            p.put("difficulty", difficulty);
            p.put("max", maxDifficulty());
            p.put("timeout", timeout);
            p.put("need", need);
            p.put("done", correctCount);
            JSONObject qq = new JSONObject();
            qq.put("id", q.optString("id"));
            qq.put("stem", q.optString("stem"));
            qq.put("options", q.optJSONArray("options"));
            p.put("question", qq);
        } catch (Exception ignored) {
        }
        return p;
    }

    public JSONObject answer(JSONObject body) {
        lock.lock();
        try {
            if (current == null) {
                JSONObject r = new JSONObject();
                try { r.put("correct", true); r.put("finished", true); r.put("answer", -1); }
                catch (Exception ignored) {}
                return r;
            }
            JSONObject q = current;
            String qid = body.optString("question_id", "");
            if (!qid.equals(q.optString("id"))) {
                return wrong(q, "题目已过期", payload(q, "quiz"));
            }
            int choice = body.optInt("choice", -1);
            boolean timedOut = body.optBoolean("timeout", false) || choice < 0;
            int answer = q.optInt("answer", 0);
            boolean correct = !timedOut && choice == answer;
            int elapsed = body.optInt("elapsed_ms", 0);
            logAttempt(q, correct, timedOut, elapsed);

            if (correct) {
                correctCount++;
                int need = Math.max(1, parseInt(db.get("correct_required", "1"), 1));
                if (correctCount < need) {
                    JSONObject nxt = pick(difficulty, null, shown, sessionUsed, preferWrong());
                    if (nxt != null) {
                        shown.add(nxt.optString("id"));
                        sessionUsed.add(nxt.optString("id"));
                        current = nxt;
                        JSONObject r = new JSONObject();
                        try {
                            r.put("correct", true);
                            r.put("finished", false);
                            r.put("answer", answer);
                            r.put("message", "答对了，还需答对 " + (need - correctCount) + " 题");
                            r.put("next", payload(nxt, "quiz"));
                        } catch (Exception ignored) {}
                        return r;
                    }
                }
                current = null;
                JSONObject r = new JSONObject();
                try {
                    r.put("correct", true);
                    r.put("answer", answer);
                    r.put("finished", true);
                    r.put("message", "答对了，继续观看");
                } catch (Exception ignored) {}
                return r;
            }

            if ("1".equals(db.get("require_consecutive", "1"))) correctCount = 0;
            JSONObject nxt = pick(difficulty, q.optString("kp"), shown, sessionUsed, preferWrong());
            if (nxt == null) {
                current = null;
                JSONObject r = new JSONObject();
                try {
                    r.put("correct", false);
                    r.put("answer", answer);
                    r.put("finished", true);
                    r.put("message", "同难度的题出完了，先继续观看");
                } catch (Exception ignored) {}
                return r;
            }
            shown.add(nxt.optString("id"));
            sessionUsed.add(nxt.optString("id"));
            current = nxt;
            return wrong(q, "✘ 答错了，换一道同难度的题", payload(nxt, "quiz"));
        } finally {
            lock.unlock();
        }
    }

    private JSONObject wrong(JSONObject q, String msg, JSONObject next) {
        JSONObject r = new JSONObject();
        try {
            r.put("correct", false);
            r.put("answer", q.optInt("answer", 0));
            r.put("message", msg);
            r.put("next", next);
        } catch (Exception ignored) {}
        return r;
    }

    private void logAttempt(JSONObject q, boolean correct, boolean timedOut, int elapsed) {
        double now = System.currentTimeMillis() / 1000.0;
        ContentValues cv = new ContentValues();
        cv.put("ts", now);
        cv.put("session_id", sessionId);
        cv.put("question_id", q.optString("id"));
        cv.put("subject", q.optString("subject"));
        cv.put("kp", q.optString("kp"));
        cv.put("difficulty", q.optInt("difficulty", 1));
        cv.put("correct", correct ? 1 : 0);
        cv.put("timed_out", timedOut ? 1 : 0);
        cv.put("response_ms", elapsed);
        db.getWritableDatabase().insert("attempts", null, cv);

        String qid = q.optString("id");
        if (qid.isEmpty()) return;
        if (correct) {
            ContentValues up = new ContentValues();
            up.put("resolved_ts", now);
            db.getWritableDatabase().update("wrong_book", up,
                    "question_id=? AND resolved_ts IS NULL", new String[]{qid});
        } else {
            int delay = parseInt(db.get("wrong_review_delay_hours", "24"), 24);
            double reviewAfter = now + delay * 3600.0;
            Cursor c = db.getReadableDatabase().rawQuery(
                    "SELECT wrong_count FROM wrong_book WHERE question_id=?",
                    new String[]{qid});
            if (c.moveToFirst()) {
                int cnt = c.getInt(0);
                c.close();
                ContentValues up = new ContentValues();
                up.put("last_wrong_ts", now);
                up.put("wrong_count", cnt + 1);
                up.putNull("resolved_ts");
                up.put("review_after_ts", reviewAfter);
                db.getWritableDatabase().update("wrong_book", up,
                        "question_id=?", new String[]{qid});
            } else {
                c.close();
                ContentValues cv2 = new ContentValues();
                cv2.put("question_id", qid);
                cv2.put("first_wrong_ts", now);
                cv2.put("last_wrong_ts", now);
                cv2.put("wrong_count", 1);
                cv2.putNull("resolved_ts");
                cv2.put("review_after_ts", reviewAfter);
                db.getWritableDatabase().insert("wrong_book", null, cv2);
            }
        }
    }

    // ---------------------------------------------------------------- 家长退出

    public JSONObject parentExit(String pin) {
        String actual = db.get("admin_pin", "");
        if (pin == null || pin.isEmpty() || actual.isEmpty() || !constantTimeEq(pin, actual)) {
            JSONObject r = new JSONObject();
            try { r.put("ok", false); r.put("error", "密码错误"); } catch (Exception ignored) {}
            return r;
        }
        db.set("suspended", "1");
        lock.lock();
        try {
            current = null;
            correctCount = 0;
        } finally {
            lock.unlock();
        }
        JSONObject r = new JSONObject();
        try { r.put("ok", true); } catch (Exception ignored) {}
        return r;
    }

    private boolean constantTimeEq(String a, String b) {
        if (a.length() != b.length()) return false;
        int r = 0;
        for (int i = 0; i < a.length(); i++) r |= a.charAt(i) ^ b.charAt(i);
        return r == 0;
    }

    private int parseInt(String s, int def) {
        try {
            return Integer.parseInt(s.trim());
        } catch (Exception e) {
            return def;
        }
    }

    // ---------------------------------------------------------------- 统计

    public JSONObject stats() {
        JSONObject o = new JSONObject();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT COUNT(*) AS n, COALESCE(SUM(correct),0) AS c FROM attempts", null);
        c.moveToFirst();
        int n = c.getInt(0), corr = c.getInt(1);
        c.close();
        int wrongCount = count("SELECT COUNT(*) FROM wrong_book WHERE resolved_ts IS NULL");
        try {
            o.put("total", n);
            o.put("correct", corr);
            o.put("accuracy", n == 0 ? 0 : (double) corr / n);
            o.put("wrong_count", wrongCount);
        } catch (Exception ignored) {}
        return o;
    }

    public List<Map<String, Object>> knowledge() {
        List<Map<String, Object>> out = new ArrayList<>();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT subject, kp, COUNT(*) AS n, SUM(correct) AS c FROM attempts GROUP BY subject, kp", null);
        while (c.moveToNext()) {
            String subject = c.getString(0) == null ? "未分类" : c.getString(0);
            String kp = c.getString(1) == null ? "未分类" : c.getString(1);
            int n = c.getInt(2);
            int corr = c.getInt(3);
            double acc = n == 0 ? 0 : (double) corr / n;
            double mastery = acc * Math.min(1.0, n / 5.0);
            Map<String, Object> m = new HashMap<>();
            m.put("subject", subject);
            m.put("kp", kp);
            m.put("n", n);
            m.put("correct", corr);
            m.put("accuracy", acc);
            m.put("mastery", mastery);
            out.add(m);
        }
        c.close();
        out.sort((a, b) -> Double.compare((double) a.get("mastery"), (double) b.get("mastery")));
        return out;
    }

    public List<Map<String, Object>> wrongBook() {
        List<Map<String, Object>> out = new ArrayList<>();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT w.question_id, w.wrong_count, w.last_wrong_ts, q.subject, q.kp," +
                        " q.difficulty, q.stem, q.options, q.answer, q.explain" +
                        " FROM wrong_book w LEFT JOIN questions q ON q.id=w.question_id" +
                        " WHERE w.resolved_ts IS NULL ORDER BY w.last_wrong_ts DESC", null);
        while (c.moveToNext()) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", c.getString(0));
            m.put("wrong_count", c.getInt(1));
            m.put("last_wrong_ts", c.getDouble(2));
            m.put("subject", c.getString(3) == null ? "" : c.getString(3));
            m.put("kp", c.getString(4) == null ? "" : c.getString(4));
            m.put("difficulty", c.getInt(5));
            m.put("stem", c.getString(6) == null ? "（题目已删除）" : c.getString(6));
            m.put("options", c.getString(7));
            m.put("answer", c.getInt(8));
            m.put("explain", c.getString(9) == null ? "" : c.getString(9));
            out.add(m);
        }
        c.close();
        return out;
    }

    private int count(String sql) {
        Cursor c = db.getReadableDatabase().rawQuery(sql, null);
        c.moveToFirst();
        int n = c.getInt(0);
        c.close();
        return n;
    }

    public List<Map<String, Object>> recent(int limit) {
        List<Map<String, Object>> out = new ArrayList<>();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT ts, kp, difficulty, correct, timed_out FROM attempts ORDER BY id DESC LIMIT ?",
                new String[]{String.valueOf(limit)});
        while (c.moveToNext()) {
            Map<String, Object> m = new HashMap<>();
            m.put("ts", c.getDouble(0));
            m.put("kp", c.getString(1) == null ? "" : c.getString(1));
            m.put("difficulty", c.getInt(2));
            m.put("correct", c.getInt(3));
            m.put("timed_out", c.getInt(4));
            out.add(m);
        }
        c.close();
        return out;
    }

    public void resolveWrong(String id, boolean reopen) {
        ContentValues cv = new ContentValues();
        if (reopen) {
            cv.putNull("resolved_ts");
        } else {
            cv.put("resolved_ts", System.currentTimeMillis() / 1000.0);
        }
        db.getWritableDatabase().update("wrong_book", cv, "question_id=?", new String[]{id});
    }

    public void setSetting(String key, String value) {
        db.set(key, value);
    }

    public String get(String key, String def) {
        return db.get(key, def);
    }

    public String getPin() {
        return db.get("admin_pin", "1234");
    }

    public boolean checkPin(String pin) {
        String actual = getPin();
        return pin != null && !actual.isEmpty() && constantTimeEq(pin, actual);
    }

    public void applySettings(Map<String, String> f) {
        setSetting("interval_seconds", clamp(f, "interval_seconds", "600", 5, 86400));
        setSetting("poll_seconds", clamp(f, "poll_seconds", "2", 1, 10));
        setSetting("max_difficulty", clamp(f, "max_difficulty", "3", 1, 10));
        setSetting("answer_timeout_seconds", clamp(f, "answer_timeout_seconds", "120", 10, 3600));
        setSetting("correct_required", clamp(f, "correct_required", "1", 1, 5));
        setSetting("wrong_review_delay_hours", clamp(f, "wrong_review_delay_hours", "24", 1, 168));
        setSetting("view_gap_seconds", clamp(f, "view_gap_seconds", "180", 60, 3600));
        setSetting("max_view_minutes", clamp(f, "max_view_minutes", "0", 0, 240));
        setSetting("drill_minutes", clamp(f, "drill_minutes", "10", 1, 60));
        setSetting("cooldown_minutes", clamp(f, "cooldown_minutes", "0", 0, 720));
        setSetting("parent_reset_minutes", clamp(f, "parent_reset_minutes", "10", 1, 120));
        setSetting("require_consecutive", f.containsKey("require_consecutive") ? "1" : "0");
        setSetting("prefer_wrong", f.containsKey("prefer_wrong") ? "1" : "0");
        setSetting("quiz_enabled", f.containsKey("quiz_enabled") ? "1" : "0");
        String pin = f.getOrDefault("admin_pin", "").trim();
        if (pin.length() >= 4 && pin.length() <= 12 && pin.matches("[A-Za-z0-9]+")) {
            setSetting("admin_pin", pin);
        }
    }

    private String clamp(Map<String, String> f, String key, String def, int lo, int hi) {
        int v = parseInt(f.getOrDefault(key, def), parseInt(def, 0));
        return String.valueOf(Math.max(lo, Math.min(hi, v)));
    }

    // ---------------------------------------------------------------- 题库管理

    public List<Map<String, Object>> listQuestions() {
        List<Map<String, Object>> out = new ArrayList<>();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT * FROM questions ORDER BY subject, difficulty, kp, id", null);
        while (c.moveToNext()) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", c.getString(c.getColumnIndex("id")));
            m.put("subject", c.getString(c.getColumnIndex("subject")));
            m.put("kp", c.getString(c.getColumnIndex("kp")));
            m.put("difficulty", c.getInt(c.getColumnIndex("difficulty")));
            m.put("stem", c.getString(c.getColumnIndex("stem")));
            m.put("options", c.getString(c.getColumnIndex("options")));
            m.put("answer", c.getInt(c.getColumnIndex("answer")));
            m.put("explain", c.getString(c.getColumnIndex("explain")));
            out.add(m);
        }
        c.close();
        return out;
    }

    public void saveQuestion(Map<String, String> f) {
        String id = f.getOrDefault("id", "").trim();
        String subject = f.getOrDefault("subject", "其他").trim();
        String kp = f.getOrDefault("kp", "").trim();
        String stem = f.getOrDefault("stem", "").trim();
        String explain = f.getOrDefault("explain", "").trim();
        String optionsRaw = f.getOrDefault("options", "");
        String[] opts = optionsRaw.split("\\n");
        java.util.List<String> optsList = new java.util.ArrayList<>();
        for (String o : opts) if (!o.trim().isEmpty()) optsList.add(o.trim());
        if (kp.isEmpty() || stem.isEmpty() || optsList.size() < 2) return;
        int answer = parseInt(f.getOrDefault("answer", "1"), 1);
        if (answer < 1 || answer > optsList.size()) return;
        int grade = parseInt(f.getOrDefault("grade", "0"), 0);
        int difficulty = Math.max(1, Math.min(5, parseInt(f.getOrDefault("difficulty", "1"), 1)));
        if (id.isEmpty()) id = "q-" + System.currentTimeMillis();

        ContentValues cv = new ContentValues();
        cv.put("id", id);
        cv.put("subject", subject);
        cv.put("grade", grade);
        cv.put("kp", kp);
        cv.put("difficulty", difficulty);
        cv.put("stem", stem);
        cv.put("options", new JSONArray(optsList).toString());
        cv.put("answer", answer - 1);
        cv.put("explain", explain);
        db.getWritableDatabase().insertWithOnConflict("questions", null, cv,
                android.database.sqlite.SQLiteDatabase.CONFLICT_REPLACE);
    }

    public void deleteQuestion(String id) {
        if (id == null || id.isEmpty()) return;
        db.getWritableDatabase().delete("questions", "id=?", new String[]{id});
    }

    public int importQuestions(String payload) {
        int count = 0;
        try {
            JSONObject root = new JSONObject(payload);
            JSONArray arr = root.has("questions")
                    ? root.getJSONArray("questions") : new JSONArray();
            for (int i = 0; i < arr.length(); i++) {
                JSONObject q = arr.getJSONObject(i);
                JSONArray opts = q.optJSONArray("options");
                if (opts == null || opts.length() < 2) continue;
                int answer = q.optInt("answer", -1);
                if (answer < 0 || answer >= opts.length()) continue;
                Map<String, String> f = new HashMap<>();
                f.put("id", q.optString("id", ""));
                f.put("subject", q.optString("subject", "其他"));
                f.put("kp", q.optString("kp", "未分类"));
                f.put("difficulty", String.valueOf(q.optInt("difficulty", 1)));
                f.put("stem", q.optString("stem", ""));
                f.put("options", join(opts, "\n"));
                f.put("answer", String.valueOf(answer + 1));
                f.put("explain", q.optString("explain", ""));
                saveQuestion(f);
                count++;
            }
        } catch (Exception ignored) {
        }
        return count;
    }

    public String exportQuestions() {
        JSONObject root = new JSONObject();
        JSONArray arr = new JSONArray();
        for (Map<String, Object> m : listQuestions()) {
            JSONObject q = new JSONObject();
            try {
                q.put("id", m.get("id"));
                q.put("subject", m.get("subject"));
                q.put("kp", m.get("kp"));
                q.put("difficulty", m.get("difficulty"));
                q.put("stem", m.get("stem"));
                q.put("options", new JSONArray(String.valueOf(m.get("options"))));
                q.put("answer", m.get("answer"));
                q.put("explain", m.get("explain"));
                arr.put(q);
            } catch (Exception ignored) {
            }
        }
        try {
            root.put("version", 1);
            root.put("questions", arr);
        } catch (Exception ignored) {
        }
        return root.toString();
    }

    private String join(JSONArray arr, String sep) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < arr.length(); i++) {
            if (i > 0) sb.append(sep);
            sb.append(arr.getString(i));
        }
        return sb.toString();
    }

    // ---------------------------------------------------------------- 观看统计（简化）

    public Map<String, Object> viewSummary() {
        Map<String, Object> out = new HashMap<>();
        Cursor c = db.getReadableDatabase().rawQuery(
                "SELECT COALESCE(SUM(duration_seconds),0) AS s, COUNT(*) AS n FROM view_sessions", null);
        c.moveToFirst();
        long secs = c.getLong(0);
        int n = c.getInt(1);
        c.close();
        out.put("total_seconds", secs);
        out.put("sessions", n);
        return out;
    }

    public void recordView(double deltaSeconds) {
        // 供 Service 定时累计观看时长；按当天日期聚合
        double now = System.currentTimeMillis() / 1000.0;
        String date = new java.text.SimpleDateFormat("yyyy-MM-dd").format(new java.util.Date());
        ContentValues cv = new ContentValues();
        cv.put("device", "standalone");
        cv.put("app_pkg", "audio");
        cv.put("started_ts", now);
        cv.put("ended_ts", now);
        cv.put("duration_seconds", (long) deltaSeconds);
        cv.put("updated_ts", now);
        cv.put("date", date);
        db.getWritableDatabase().insert("view_sessions", null, cv);
    }
}
