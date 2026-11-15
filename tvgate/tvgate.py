#!/usr/bin/env python3
"""tvgate — 电视观看时长闸门（Mac 原型）。

看满 N 分钟 → 暂停 → 弹一道题；答对继续，答错换一道同难度的题；
每过一个 N 分钟，难度档 +1。数据写 SQLite，家长端网页看统计、改设置。

当前用「模拟播放器」验证完整流程；真实部署时把 SimPlayer 换成
HDMI-CEC / Kodi 适配器即可，其余逻辑不用动。
"""

import argparse
import hmac
import html
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tvgate.db")
BANK_PATH = os.path.join(BASE_DIR, "questions.json")

tk = None  # 延迟导入：Pi 上没装 python3-tk 时，--admin-only 仍能跑


def ensure_tk():
    global tk
    if tk is None:
        import tkinter
        tk = tkinter


DEFAULT_SETTINGS = {
    "interval_seconds": "600",
    "poll_seconds": "2",
    "max_difficulty": "3",
    "answer_timeout_seconds": "120",
    "quiz_enabled": "1",
    "correct_required": "1",
    "require_consecutive": "1",
    "prefer_wrong": "1",
    "view_gap_seconds": "180",
    "max_view_minutes": "0",
    "drill_minutes": "10",
    "cooldown_minutes": "0",
    "parent_suspend_minutes": "30",
    "parent_reset_minutes": "10",
    "suspend_until": "0",
    "admin_pin": "1234",
}

FIRE_CONTROLLER = None  # --firetv / --quiz-test 模式下由 main() 赋值


# ---------------------------------------------------------------- 数据库

def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_bank(conn, path=BANK_PATH):
    """把 questions.json 里的题目导入数据库（按 id 覆盖）。"""
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        bank = json.load(f)
    count = 0
    for q in bank.get("questions", []):
        conn.execute(
            "INSERT OR REPLACE INTO questions"
            "(id, subject, grade, kp, difficulty, stem, options, answer, explain)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (q["id"], q["subject"], q.get("grade", 0), q["kp"], q["difficulty"],
             q["stem"], json.dumps(q["options"], ensure_ascii=False),
             q.get("answer", 0), q.get("explain", "")),
        )
        count += 1
    conn.commit()
    return count


def init_db(conn, bank_path=BANK_PATH):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id         TEXT PRIMARY KEY,
            subject    TEXT NOT NULL,
            grade      INTEGER DEFAULT 0,
            kp         TEXT NOT NULL,
            difficulty INTEGER NOT NULL,
            stem       TEXT NOT NULL,
            options    TEXT NOT NULL,
            answer     INTEGER NOT NULL,
            explain    TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            session_id  TEXT,
            question_id TEXT,
            subject     TEXT,
            kp          TEXT,
            difficulty  INTEGER,
            correct     INTEGER NOT NULL DEFAULT 0,
            timed_out   INTEGER NOT NULL DEFAULT 0,
            response_ms INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wrong_book (
            question_id    TEXT PRIMARY KEY,
            first_wrong_ts REAL,
            last_wrong_ts  REAL,
            wrong_count    INTEGER NOT NULL DEFAULT 0,
            resolved_ts    REAL
        );
        CREATE TABLE IF NOT EXISTS view_sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            device           TEXT,
            app_pkg          TEXT,
            started_ts       REAL NOT NULL,
            ended_ts         REAL,
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            updated_ts       REAL NOT NULL,
            date             TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_kp ON attempts(kp);
        CREATE INDEX IF NOT EXISTS idx_view_sessions_date ON view_sessions(date);
        """
    )
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value))
    # 只在首次初始化时导入题库；之后以数据库为准，网页里的增删改不会被重启覆盖。
    if conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0:
        load_bank(conn, bank_path)
    # 用历史作答回填错题本（只补不覆盖）
    conn.execute(
        "INSERT OR IGNORE INTO wrong_book(question_id, first_wrong_ts, last_wrong_ts,"
        " wrong_count) SELECT question_id, MIN(ts), MAX(ts), COUNT(*) FROM attempts"
        " WHERE correct=0 AND question_id IS NOT NULL GROUP BY question_id"
    )
    conn.commit()


def read_settings(conn):
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, str(value)))
    conn.commit()


def log_attempt(conn, session_id, q, correct, timed_out, response_ms):
    now = time.time()
    conn.execute(
        "INSERT INTO attempts(ts, session_id, question_id, subject, kp, difficulty,"
        " correct, timed_out, response_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now, session_id, q["id"], q["subject"], q["kp"], q["difficulty"],
         1 if correct else 0, 1 if timed_out else 0, response_ms),
    )
    if not correct and q["id"]:
        row = conn.execute(
            "SELECT wrong_count FROM wrong_book WHERE question_id=?", (q["id"],)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE wrong_book SET last_wrong_ts=?, wrong_count=?, resolved_ts=NULL"
                " WHERE question_id=?",
                (now, row["wrong_count"] + 1, q["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO wrong_book(question_id, first_wrong_ts, last_wrong_ts,"
                " wrong_count, resolved_ts) VALUES(?, ?, ?, 1, NULL)",
                (q["id"], now, now),
            )
    conn.commit()


def pick_question(conn, difficulty, kp=None, exclude=frozenset(), used=frozenset(),
                  prefer_wrong=False):
    """同知识点优先；排除本次检查点已出过的题；尽量不出重复题。

    prefer_wrong=True 时先从未掌握的错题本里选（难度不高于当前档），
    再回退到普通题库。
    """
    if prefer_wrong:
        sql = (
            "SELECT q.* FROM wrong_book w JOIN questions q ON q.id = w.question_id"
            " WHERE w.resolved_ts IS NULL AND q.difficulty <= ?"
        )
        args = [difficulty]
        if kp:
            sql += " AND q.kp = ?"
            args.append(kp)
        sql += " ORDER BY w.last_wrong_ts DESC"
        rows = [r for r in conn.execute(sql, args).fetchall() if r["id"] not in exclude]
        if rows:
            fresh = [r for r in rows if r["id"] not in used]
            return random.choice(fresh or rows)

    def rows_for(kp_filter):
        if kp_filter:
            return conn.execute(
                "SELECT * FROM questions WHERE difficulty=? AND kp=?", (difficulty, kp_filter)
            ).fetchall()
        return conn.execute("SELECT * FROM questions WHERE difficulty=?", (difficulty,)).fetchall()

    for kp_filter in ([kp] if kp else []) + [None]:
        rows = [r for r in rows_for(kp_filter) if r["id"] not in exclude]
        fresh = [r for r in rows if r["id"] not in used]
        pool = fresh or rows
        if pool:
            return random.choice(pool)
    return None


def compute_stats(conn):
    """每个知识点：作答数、正确率、掌握度（正确率 × 置信系数）。"""
    rows = conn.execute(
        "SELECT kp, MAX(subject) AS subject, COUNT(*) AS n, SUM(correct) AS c, MAX(ts) AS last"
        " FROM attempts GROUP BY kp"
    ).fetchall()
    out = []
    for r in rows:
        n = r["n"]
        correct = r["c"] or 0
        accuracy = correct / n if n else 0.0
        confidence = min(1.0, n / 5.0)  # 作答太少时不让掌握度虚高
        out.append({
            "kp": r["kp"], "subject": r["subject"], "n": n, "correct": correct,
            "accuracy": accuracy, "mastery": accuracy * confidence, "last": r["last"],
        })
    out.sort(key=lambda x: (x["mastery"], -x["n"]))
    return out


# ---------------------------------------------------------------- 播放器与答题界面

class SimPlayer:
    """模拟播放器：真实部署时替换为 CEC/Kodi 适配器。"""

    def __init__(self, root, on_quit):
        self.root = root
        self.alive = True
        self.paused = False
        self.progress = 0.0
        self.interval = 600

        root.title("tvgate · 模拟播放器")
        root.geometry("900x520")
        root.configure(bg="#08090c")
        root.protocol("WM_DELETE_WINDOW", on_quit)

        self.status = tk.Label(root, text="▶ 模拟播放中", fg="#e8edf5", bg="#08090c",
                               font=("Helvetica", 34))
        self.status.place(relx=0.5, rely=0.40, anchor="center")
        tk.Label(root, text="真实部署时这里是电视画面 · Pi 通过 HDMI-CEC 切回自己的输入显示题目",
                 fg="#66707f", bg="#08090c", font=("Helvetica", 13)).place(
            relx=0.5, rely=0.50, anchor="center")

        track = tk.Frame(root, bg="#1a1e27", height=6)
        track.place(relx=0.5, rely=0.66, anchor="center", relwidth=0.7)
        self.fill = tk.Frame(track, bg="#3d7df6")
        self.fill.place(x=0, y=0, relheight=1, relwidth=0)

        self.hint = tk.Label(root, text="", fg="#8b95a5", bg="#08090c", font=("Helvetica", 12))
        self.hint.place(relx=0.5, rely=0.72, anchor="center")
        tk.Label(root, text="Ctrl+Q 退出", fg="#3d4450", bg="#08090c",
                 font=("Helvetica", 11)).place(relx=0.5, rely=0.90, anchor="center")
        self._tick()

    def _tick(self):
        if not self.alive:
            return
        if not self.paused:
            self.progress = min(1.0, self.progress + 0.25 / max(1, self.interval))
            try:
                self.fill.place_configure(relwidth=self.progress)
            except Exception:
                return
            remain = max(0, int(round(self.interval * (1 - self.progress))))
            self.hint.configure(text="距下次检查约 %d:%02d" % (remain // 60, remain % 60))
        self.root.after(250, self._tick)

    def set_interval(self, seconds):
        self.interval = max(1, int(seconds))

    def reset(self):
        self.progress = 0.0
        try:
            self.fill.place_configure(relwidth=0)
        except Exception:
            pass

    def pause(self):
        self.paused = True
        self.status.configure(text="⏸ 已暂停 · 答题中", fg="#ffc46b")
        self.hint.configure(text="答对后继续播放")

    def resume(self):
        self.paused = False
        self.status.configure(text="▶ 模拟播放中", fg="#e8edf5")

    def stop(self):
        self.alive = False


class QuizUI:
    """全屏答题层。只负责显示和收集输入，对错判断与选下一题交给 App。"""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.q = None
        self.buttons = []
        self.feedback = None
        self.countdown = None
        self.callback = None
        self.locked = True
        self.shown_at = 0.0
        self.timeout_s = 120
        self._tick_id = None

    def show(self, q, block, difficulty, max_diff, timeout_s, callback):
        self.close()
        self.q = q
        self.callback = callback
        self.timeout_s = max(5, int(timeout_s))
        self.shown_at = time.time()
        self.locked = False

        win = tk.Toplevel(self.root)
        self.win = win
        win.configure(bg="#0f1117")
        win.title("答题")
        win.geometry("%dx%d+0+0" % (self.root.winfo_screenwidth(), self.root.winfo_screenheight()))
        try:
            win.attributes("-fullscreen", True)
            win.attributes("-topmost", True)
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.bind("<Escape>", lambda e: "break")

        box = tk.Frame(win, bg="#0f1117", padx=70, pady=50)
        box.pack(fill="both", expand=True)

        tk.Label(box, text="检查点 %d · 难度 %d/%d" % (block, difficulty, max_diff),
                 fg="#7f8ea3", bg="#0f1117", font=("Helvetica", 16)).pack(anchor="w")
        tk.Label(box, text=q["stem"], fg="#f2f5f9", bg="#0f1117", font=("Helvetica", 30),
                 wraplength=1100, justify="left").pack(anchor="w", pady=(26, 34))

        self.buttons = []
        for i, opt in enumerate(json.loads(q["options"])):
            btn = tk.Button(box, text="%d.  %s" % (i + 1, opt), font=("Helvetica", 20),
                            anchor="w", padx=20, pady=14, relief="flat", highlightthickness=0,
                            bg="#1c2230", fg="#e6ebf2", activebackground="#2a3346",
                            activeforeground="#ffffff", command=lambda i=i: self.pick(i))
            btn.pack(fill="x", pady=7)
            self.buttons.append(btn)
            win.bind(str(i + 1), lambda e, i=i: self.pick(i))

        self.feedback = tk.Label(box, text="", fg="#61d095", bg="#0f1117", font=("Helvetica", 18))
        self.feedback.pack(anchor="w", pady=(26, 6))
        self.countdown = tk.Label(box, text="", fg="#7f8ea3", bg="#0f1117", font=("Helvetica", 14))
        self.countdown.pack(anchor="w")

        try:
            win.lift()
            win.focus_force()
        except Exception:
            pass
        self._tick()

    def _tick(self):
        self._tick_id = None
        if self.win is None or self.locked:
            return
        remain = int(self.timeout_s - (time.time() - self.shown_at))
        if remain <= 0:
            self.locked = True
            if self.countdown is not None:
                self.countdown.configure(text="时间到")
            cb = self.callback
            if cb:
                cb(self.q, None, int(self.timeout_s * 1000))
            return
        if self.countdown is not None:
            self.countdown.configure(text="剩余 %d 秒" % remain)
        self._tick_id = self.root.after(500, self._tick)

    def pick(self, idx):
        if self.locked or self.win is None:
            return
        self.locked = True
        if self._tick_id:
            try:
                self.root.after_cancel(self._tick_id)
            except Exception:
                pass
            self._tick_id = None
        response_ms = int((time.time() - self.shown_at) * 1000)
        cb = self.callback
        if cb:
            cb(self.q, idx, response_ms)

    def mark(self, ok, idx):
        if self.win is None:
            return
        answer = self.q["answer"]
        for i, btn in enumerate(self.buttons):
            if i == answer:
                btn.configure(bg="#1f6f43")
            elif idx is not None and i == idx:
                btn.configure(bg="#7a2b2b")
        if self.feedback is not None:
            if ok:
                self.feedback.configure(text="✔ 答对了，继续观看", fg="#61d095")
            else:
                self.feedback.configure(text="✘ 答错了，换一道同难度的题", fg="#ff8a8a")

    def set_feedback(self, text):
        if self.feedback is not None:
            self.feedback.configure(text=text, fg="#ffc46b")

    def close(self):
        if self._tick_id:
            try:
                self.root.after_cancel(self._tick_id)
            except Exception:
                pass
            self._tick_id = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
        self.q = None
        self.callback = None
        self.buttons = []
        self.feedback = None
        self.countdown = None
        self.locked = True


# ---------------------------------------------------------------- 主流程

class App:
    def __init__(self, conn, auto=False, max_blocks=0):
        ensure_tk()
        self.conn = conn
        self.auto = auto
        self.max_blocks = max_blocks
        self.root = tk.Tk()
        self.player = SimPlayer(self.root, self.quit)
        self.ui = QuizUI(self.root)
        self.block = 0
        self.current_diff = 1
        self.checkpoint_shown = set()
        self.session_used = set()
        self.session_id = time.strftime("%Y%m%d-%H%M%S")
        self._timer_id = None

        settings = read_settings(self.conn)
        self.player.set_interval(int(settings["interval_seconds"]))
        self.root.bind("<Control-q>", lambda e: self.quit())
        self.root.after(1500, self.schedule_next)

    def schedule_next(self):
        self.cancel_timer()
        settings = read_settings(self.conn)
        seconds = max(5, int(settings["interval_seconds"]))
        self.player.set_interval(seconds)
        self._timer_id = self.root.after(seconds * 1000, self.checkpoint)

    def cancel_timer(self):
        if self._timer_id:
            try:
                self.root.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def checkpoint(self):
        self._timer_id = None
        settings = read_settings(self.conn)
        if settings["quiz_enabled"] != "1":
            self.schedule_next()
            return

        self.block += 1
        self.current_diff = min(self.block, max(1, int(settings["max_difficulty"])))
        self.checkpoint_shown = set()

        question = pick_question(self.conn, self.current_diff,
                                 exclude=self.checkpoint_shown, used=self.session_used)
        if question is None:
            print("[tvgate] 难度 %d 暂无可用题目，跳过本次检查" % self.current_diff)
            self.schedule_next()
            return

        self.checkpoint_shown.add(question["id"])
        self.session_used.add(question["id"])
        self.player.pause()
        self.show_question(question)

    def show_question(self, question):
        settings = read_settings(self.conn)
        self.ui.show(question, self.block, self.current_diff,
                     int(settings["max_difficulty"]),
                     int(settings["answer_timeout_seconds"]), self.handle_answer)
        if self.auto:
            self.root.after(600, lambda: self.ui.pick(question["answer"]))

    def handle_answer(self, question, idx, response_ms):
        timed_out = idx is None
        correct = (idx == question["answer"])
        log_attempt(self.conn, self.session_id, question, correct, timed_out, response_ms)
        self.ui.mark(correct, idx)

        if correct:
            self.root.after(700, self.finish_checkpoint)
            return

        # 答错：同难度、优先同知识点的另一道题
        nxt = pick_question(self.conn, self.current_diff, kp=question["kp"],
                            exclude=self.checkpoint_shown, used=self.session_used)
        if nxt is not None:
            self.checkpoint_shown.add(nxt["id"])
            self.session_used.add(nxt["id"])
            self.root.after(900, lambda: self.show_question(nxt))
        else:
            self.ui.set_feedback("同难度的题已经出完了，先继续观看。")
            self.root.after(1200, self.finish_checkpoint)

    def finish_checkpoint(self):
        self.ui.close()
        self.player.resume()
        self.player.reset()
        if self.max_blocks and self.block >= self.max_blocks:
            print("[smoke] 已完成 %d 个检查点，自动退出" % self.block)
            self.root.after(300, self.quit)
            return
        self.schedule_next()

    def quit(self):
        self.cancel_timer()
        self.ui.close()
        self.player.stop()
        self.root.destroy()


# ---------------------------------------------------------------- 家长端网页

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0b0d12;color:#e6ebf2;font:15px/1.6 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 12px;color:#9fb0c7;font-weight:600}
.sub{color:#6f7d90;font-size:13px;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:#141821;border:1px solid #1f2531;border-radius:12px;padding:14px 16px}
.card .k{color:#7f8ea3;font-size:12px}
.card .v{font-size:24px;font-weight:700;margin-top:2px}
table{width:100%;border-collapse:collapse;background:#141821;border:1px solid #1f2531;border-radius:12px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #1c2230;font-size:14px}
th{color:#8b9ab0;font-weight:600;background:#11151d}
tr:last-child td{border-bottom:none}
.bar{display:inline-block;width:90px;height:6px;background:#232a38;border-radius:3px;vertical-align:middle;margin-right:8px;overflow:hidden}
.bar i{display:block;height:100%;background:#3d7df6}
form{background:#141821;border:1px solid #1f2531;border-radius:12px;padding:18px}
label{display:block;margin:10px 0;color:#b9c5d6;font-size:14px}
input[type=number],input[type=text],input[type=password]{width:160px;background:#0e1219;border:1px solid #2a3346;border-radius:8px;color:#e6ebf2;padding:8px 10px;font-size:14px}
button{background:#3d7df6;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;margin-top:8px}
ul.tips{margin:0;padding-left:20px;color:#c8d3e2}
ul.tips li{margin:6px 0}
.err{color:#ff8a8a}
a{color:#7aa7ff}
"""


def page(title, body):
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>%s</title><style>%s</style></head>"
        '<body><div class="wrap">%s</div></body></html>'
        % (html.escape(title), CSS, body)
    )


ADMIN_CSS = """
:root{--bg:#0b0d12;--panel:#141821;--panel2:#11151d;--line:#1f2531;--text:#e6ebf2;--muted:#8b9ab0;--blue:#3d7df6;--green:#2e9e63;--red:#b84444;--amber:#c98a2e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif}
a{color:#7aa7ff;text-decoration:none}
a:hover{text-decoration:underline}
.nav{position:sticky;top:0;z-index:10;background:rgba(11,13,18,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.nav .inner{max-width:1120px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:10px;height:56px;overflow:auto}
.brand{font-weight:700;font-size:17px;margin-right:8px;white-space:nowrap}
.nav a{color:var(--muted);padding:6px 11px;border-radius:8px;font-size:14px;white-space:nowrap}
.nav a.active,.nav a:hover{color:#fff;background:#1c2230;text-decoration:none}
.nav .spacer{flex:1}
.wrap{max-width:1120px;margin:0 auto;padding:26px 20px 70px}
h1{font-size:23px;margin:0 0 4px}
h2{font-size:16px;margin:30px 0 12px;color:#a9b8cc;font-weight:600}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px 17px}
.card .k{color:var(--muted);font-size:12px}
.card .v{font-size:26px;font-weight:700;margin-top:2px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:11px 12px;text-align:left;border-bottom:1px solid #1c2230;font-size:14px;vertical-align:top}
th{color:#8b9ab0;font-weight:600;background:var(--panel2);white-space:nowrap}
tr:last-child td{border-bottom:none}
.bar{display:inline-block;width:96px;height:7px;background:#232a38;border-radius:4px;vertical-align:middle;margin-right:8px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--blue)}
.bar i.low{background:#c05a5a}.bar i.mid{background:#c98a2e}.bar i.ok{background:#2e9e63}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#1c2230;color:#b9c5d6;font-size:12px}
.pill.d1{background:#20304a}.pill.d2{background:#243a52}.pill.d3{background:#3a3320}.pill.d4{background:#3f2a2a}.pill.d5{background:#3d2338}
.btn{display:inline-block;background:var(--blue);color:#fff;border:none;border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer;line-height:1.3}
.btn:hover{filter:brightness(1.08);text-decoration:none}
.btn.ghost{background:#1c2230;color:#cfd9e8}
.btn.danger{background:#7a2b2b}
.btn.small{padding:5px 10px;font-size:13px}
form{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}
label{display:block;margin:10px 0 4px;color:#b9c5d6;font-size:13px}
input[type=number],input[type=text],input[type=password],select,textarea{width:100%;max-width:560px;background:#0e1219;border:1px solid #2a3346;border-radius:9px;color:var(--text);padding:9px 11px;font-size:14px;font-family:inherit}
textarea{min-height:84px;resize:vertical}
textarea.code{min-height:180px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}th,td{padding:9px 8px}}
.muted{color:var(--muted)}
.good{color:#61d095}.bad{color:#ff8a8a}.warn{color:#ffc46b}
.empty{padding:28px;text-align:center;color:var(--muted);background:var(--panel);border:1px dashed var(--line);border-radius:14px}
.opt{padding:3px 0;color:#c8d3e2}
.opt.correct{color:#7fe0a6;font-weight:600}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.toolbar form{margin:0;padding:0;background:none;border:none;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.toolbar input,.toolbar select{width:auto;min-width:120px;max-width:220px}
details{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-top:12px}
summary{cursor:pointer;color:#b9c5d6;font-weight:600}
ul.tips{margin:0;padding-left:20px;color:#c8d3e2}
ul.tips li{margin:6px 0}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.tab{padding:6px 12px;border-radius:999px;background:#141821;border:1px solid var(--line);color:#b9c5d6;font-size:13px}
.tab.active{background:#1c2a44;border-color:#2a4a7f;color:#fff}
.tab b{color:#7aa7ff;margin-left:4px}
pre.report{white-space:pre-wrap;word-break:break-word;background:#0e1219;border:1px solid var(--line);border-radius:14px;padding:18px;font:13px/1.7 ui-monospace,Menlo,Consolas,monospace;color:#cfd9e8;max-height:70vh;overflow:auto}
.help{color:#6f7d90;font-size:12px;line-height:1.5;margin-top:3px;max-width:560px}
"""

NAV_ITEMS = [
    ("home", "/", "总览"),
    ("knowledge", "/knowledge", "知识点"),
    ("wrong", "/wrong", "错题本"),
    ("questions", "/questions", "题库"),
    ("view", "/view", "观看"),
    ("report", "/report", "报告"),
    ("settings", "/settings", "设置"),
]


def layout(title, active, body):
    links = "".join(
        "<a class='%s' href='%s'>%s</a>"
        % ("active" if key == active else "", href, label)
        for key, href, label in NAV_ITEMS
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>%s</title><style>%s</style></head><body>"
        "<div class='nav'><div class='inner'><span class='brand'>答完再看</span>%s"
        "<span class='spacer'></span><a href='/logout'>退出</a></div></div>"
        "<div class='wrap'>%s</div></body></html>"
        % (html.escape(title), ADMIN_CSS, links, body)
    )


def pct_text(n, c):
    return ("%.0f%%" % (100.0 * c / n)) if n else "—"


def mastery_bar(value):
    v = int(max(0.0, min(1.0, value)) * 100)
    cls = "ok" if v >= 70 else ("mid" if v >= 40 else "low")
    return "<div class='bar'><i class='%s' style='width:%d%%'></i></div>%d%%" % (cls, v, v)


def _form_first(form, key, default=""):
    return form.get(key, [default])[0]


def _clean_options(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


# ---------------------------------------------------------------- 查询

def compute_weak_by_subject(conn):
    rows = conn.execute(
        "SELECT subject, kp, COUNT(*) AS n, SUM(correct) AS c, MAX(ts) AS last"
        " FROM attempts GROUP BY subject, kp"
    ).fetchall()
    grouped = {}
    for r in rows:
        n = r["n"]
        correct = r["c"] or 0
        accuracy = correct / n if n else 0.0
        confidence = min(1.0, n / 5.0)
        grouped.setdefault(r["subject"] or "未分类", []).append({
            "kp": r["kp"], "n": n, "correct": correct, "accuracy": accuracy,
            "mastery": accuracy * confidence, "last": r["last"],
        })
    for items in grouped.values():
        items.sort(key=lambda x: (x["mastery"], -x["n"]))
    return grouped


def compute_wrong_book(conn, include_resolved=False):
    sql = (
        "SELECT w.question_id, w.first_wrong_ts, w.last_wrong_ts, w.wrong_count,"
        " w.resolved_ts, q.subject, q.kp, q.difficulty, q.stem, q.options,"
        " q.answer, q.explain"
        " FROM wrong_book w LEFT JOIN questions q ON q.id = w.question_id"
    )
    if not include_resolved:
        sql += " WHERE w.resolved_ts IS NULL"
    sql += " ORDER BY w.resolved_ts IS NOT NULL, w.last_wrong_ts DESC"
    out = []
    for r in conn.execute(sql).fetchall():
        try:
            options = json.loads(r["options"]) if r["options"] else []
        except (TypeError, ValueError):
            options = []
        out.append({
            "id": r["question_id"], "subject": r["subject"] or "",
            "kp": r["kp"] or "", "difficulty": r["difficulty"] or 0,
            "stem": r["stem"] or "（题目已删除）", "options": options,
            "answer": r["answer"], "explain": r["explain"] or "",
            "wrong_count": r["wrong_count"],
            "first_wrong_ts": r["first_wrong_ts"], "last_wrong_ts": r["last_wrong_ts"],
            "resolved_ts": r["resolved_ts"],
        })
    return out


def list_questions(conn, subject="", kp="", difficulty="", search=""):
    where, args = [], []
    if subject:
        where.append("subject=?")
        args.append(subject)
    if kp:
        where.append("kp LIKE ?")
        args.append("%" + kp + "%")
    if difficulty:
        try:
            args.append(int(difficulty))
            where.append("difficulty=?")
        except ValueError:
            pass
    if search:
        where.append("(stem LIKE ? OR explain LIKE ?)")
        args.extend(["%" + search + "%", "%" + search + "%"])
    sql = "SELECT * FROM questions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY subject, difficulty, kp, id"
    return conn.execute(sql, args).fetchall()


def get_question(conn, qid):
    return conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()


def upsert_question(conn, data):
    conn.execute(
        "INSERT OR REPLACE INTO questions(id, subject, grade, kp, difficulty, stem,"
        " options, answer, explain) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (data["id"], data["subject"], data["grade"], data["kp"], data["difficulty"],
         data["stem"], json.dumps(data["options"], ensure_ascii=False),
         data["answer"], data["explain"]),
    )
    conn.commit()


def delete_question(conn, qid):
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    conn.commit()


def export_questions_payload(conn):
    items = []
    for r in conn.execute("SELECT * FROM questions ORDER BY subject, difficulty, kp, id"):
        try:
            options = json.loads(r["options"])
        except (TypeError, ValueError):
            options = []
        items.append({
            "id": r["id"], "subject": r["subject"], "grade": r["grade"],
            "kp": r["kp"], "difficulty": r["difficulty"], "stem": r["stem"],
            "options": options, "answer": r["answer"], "explain": r["explain"],
        })
    return json.dumps({"version": 1, "questions": items}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 页面

def login_page(err=""):
    body = (
        "<h1>答完再看 家长端</h1><div class='sub'>输入 PIN 进入</div>"
        + ("<p class='bad'>%s</p>" % html.escape(err) if err else "")
        + "<form method='post' action='/login' style='max-width:360px'>"
          "<label>PIN</label><input type='password' name='pin' autofocus>"
          "<div style='margin-top:14px'><button class='btn' type='submit'>进入</button></div>"
          "</form>"
          "<p class='sub' style='margin-top:16px'>默认 PIN 1234，第一次进入后请在设置里改掉。</p>"
    )
    return layout("登录", "", body)


def dashboard_page(conn):
    grouped = compute_weak_by_subject(conn)
    flat = []
    for subject, items in grouped.items():
        for item in items:
            item["subject"] = subject
            flat.append(item)
    flat.sort(key=lambda x: (x["mastery"], -x["n"]))

    total = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(correct),0) AS c FROM attempts").fetchone()
    day = conn.execute(
        "SELECT COUNT(*) AS n FROM attempts WHERE ts >= ?",
        (time.time() - 86400,)).fetchone()
    week = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(correct),0) AS c FROM attempts WHERE ts >= ?",
        (time.time() - 7 * 86400,)).fetchone()
    wrong_count = conn.execute(
        "SELECT COUNT(*) AS n FROM wrong_book WHERE resolved_ts IS NULL").fetchone()["n"]
    view = view_summary(conn, 0, 14)

    cards = (
        "<div class='cards'>"
        "<div class='card'><div class='k'>累计作答</div><div class='v'>%d</div></div>"
        "<div class='card'><div class='k'>累计正确率</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>最近 24 小时</div><div class='v'>%d</div></div>"
        "<div class='card'><div class='k'>最近 7 天正确率</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>待复习错题</div><div class='v'>%d</div></div>"
        "<div class='card'><div class='k'>今日观看</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>今日次数</div><div class='v'>%d</div></div>"
        "</div>"
        % (total["n"], pct_text(total["n"], total["c"]), day["n"],
           pct_text(week["n"], week["c"]), wrong_count,
           format_duration(view["today_seconds"]), view["today_sessions"])
    )

    tips = []
    for item in flat[:3]:
        tips.append(
            "<li><b>%s</b>（%s）—— 作答 %d 次，正确率 %s，掌握度 %d%%。"
            "<a href='/questions?kp=%s'>看题</a></li>"
            % (html.escape(item["kp"]), html.escape(item["subject"]), item["n"],
               pct_text(item["n"], item["correct"]), int(item["mastery"] * 100),
               urllib.parse.quote(item["kp"]))
        )
    if not tips:
        tips.append("<li>还没有答题记录，先在电视端看满一个检查周期试试。</li>")
    tips_html = "<ul class='tips'>%s</ul>" % "".join(tips)

    recent_rows = []
    for r in conn.execute(
            "SELECT ts, kp, difficulty, correct, timed_out FROM attempts"
            " ORDER BY id DESC LIMIT 10"):
        when = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
        mark = "✔" if r["correct"] else ("⏱" if r["timed_out"] else "✘")
        recent_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>"
            % (when, html.escape(r["kp"] or ""), r["difficulty"] or 0, mark)
        )
    if not recent_rows:
        recent_rows.append("<tr><td colspan='4' class='muted'>暂无记录</td></tr>")
    recent = (
        "<table><tr><th>时间</th><th>知识点</th><th>难度</th><th>结果</th></tr>%s</table>"
        % "".join(recent_rows)
    )

    body = (
        "<h1>总览</h1><div class='sub'>孩子的观看与答题情况</div>"
        + cards
        + "<div class='toolbar' style='margin-top:14px'>"
          "<a class='btn' href='/report'>导出学习报告</a>"
          "<a class='btn ghost' href='/view'>观看统计</a>"
          "<a class='btn ghost' href='/wrong'>打开错题本</a>"
          "<a class='btn ghost' href='/settings'>系统设置</a></div>"
        + "<h2>复习建议</h2>" + tips_html
        + "<h2>最近答题</h2>" + recent
    )
    return layout("总览", "home", body)


def knowledge_page(conn):
    grouped = compute_weak_by_subject(conn)
    if not grouped:
        return layout("知识点", "knowledge",
                      "<h1>知识点掌握</h1><div class='empty'>还没有答题记录。</div>")
    sections = []
    for subject in sorted(grouped):
        rows = []
        for item in grouped[subject]:
            rows.append(
                "<tr><td><a href='/questions?kp=%s'>%s</a></td><td>%d</td>"
                "<td>%s</td><td>%s</td></tr>"
                % (urllib.parse.quote(item["kp"]), html.escape(item["kp"]), item["n"],
                   pct_text(item["n"], item["correct"]), mastery_bar(item["mastery"]))
            )
        sections.append(
            "<h2>%s</h2><table><tr><th>知识点</th><th>作答</th>"
            "<th>正确率</th><th>掌握度</th></tr>%s</table>"
            % (html.escape(subject), "".join(rows))
        )
    return layout(
        "知识点", "knowledge",
        "<h1>知识点掌握</h1><div class='sub'>按掌握度从低到高排序，点知识点查看对应题目。</div>"
        + "".join(sections)
    )


def wrong_page(conn, include_resolved=False):
    items = compute_wrong_book(conn, include_resolved)
    cards = []
    for it in items:
        options_html = "".join(
            "<div class='opt%s'>%s. %s</div>"
            % (" correct" if i == it["answer"] else "", chr(65 + i),
               html.escape(str(opt)))
            for i, opt in enumerate(it["options"])
        )
        last = (time.strftime("%m-%d %H:%M", time.localtime(it["last_wrong_ts"]))
                if it["last_wrong_ts"] else "—")
        resolved = it["resolved_ts"] is not None
        action = "reopen" if resolved else "resolve"
        label = "重新加入" if resolved else "标记已掌握"
        btn_cls = "ghost" if resolved else ""
        cards.append(
            "<div class='card' style='margin-bottom:12px'>"
            "<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px'>"
            "<span class='pill'>%s</span><span class='pill'>%s</span>"
            "<span class='pill d%d'>难度 %d</span>"
            "<span class='muted' style='font-size:12px'>错 %d 次 · 最近 %s</span>"
            "<span style='flex:1'></span>"
            "<form method='post' action='/wrong/resolve' style='display:inline'>"
            "<input type='hidden' name='id' value='%s'>"
            "<input type='hidden' name='action' value='%s'>"
            "<button class='btn small %s' type='submit'>%s</button></form>"
            "</div>"
            "<div style='font-size:17px;font-weight:600;margin:4px 0 8px'>%s</div>"
            "%s"
            "<div class='sub' style='margin:10px 0 0'>%s</div>"
            "</div>"
            % (html.escape(it["subject"]), html.escape(it["kp"]),
               it["difficulty"], it["difficulty"], it["wrong_count"], last,
               html.escape(it["id"]), action, btn_cls, label,
               html.escape(it["stem"]), options_html, html.escape(it["explain"]))
        )
    if not cards:
        cards.append("<div class='empty'>%s</div>"
                     % ("暂时没有未掌握的错题" if not include_resolved else "还没有错题记录"))
    toggle = ("<a class='btn ghost' href='/wrong'>只看未掌握</a>"
              if include_resolved else "<a class='btn ghost' href='/wrong?all=1'>查看全部</a>")
    body = (
        "<h1>错题本</h1><div class='sub'>答错过的题按最近错误时间排序；"
        "答对不会自动移除，确认掌握后点「标记已掌握」。</div>"
        "<div class='toolbar'>%s</div>%s" % (toggle, "".join(cards))
    )
    return layout("错题本", "wrong", body)


def questions_page(conn, query):
    subject = _form_first(query, "subject")
    kp = _form_first(query, "kp")
    difficulty = _form_first(query, "difficulty")
    search = _form_first(query, "q")
    imported = _form_first(query, "imported")
    rows = list_questions(conn, subject, kp, difficulty, search)

    subject_counts = {r["subject"]: r["n"] for r in conn.execute(
        "SELECT subject, COUNT(*) AS n FROM questions GROUP BY subject")}
    total_count = sum(subject_counts.values())
    tab_items = ["<a class='tab %s' href='/questions'>全部 <b>%d</b></a>"
                 % ("active" if not subject else "", total_count)]
    for s in ("数学", "语文", "英语", "科学", "其他"):
        if s in subject_counts:
            tab_items.append(
                "<a class='tab %s' href='/questions?subject=%s'>%s <b>%d</b></a>"
                % ("active" if subject == s else "", urllib.parse.quote(s), s,
                   subject_counts[s]))
    tabs_html = "<div class='tabs'>%s</div>" % "".join(tab_items)

    subjects = [r["subject"] for r in conn.execute(
        "SELECT DISTINCT subject FROM questions ORDER BY subject")]
    subject_options = "<option value=''>全部科目</option>" + "".join(
        "<option value='%s'%s>%s</option>"
        % (html.escape(s), " selected" if s == subject else "", html.escape(s))
        for s in subjects)
    diff_options = "<option value=''>全部难度</option>" + "".join(
        "<option value='%d'%s>%d</option>"
        % (d, " selected" if str(d) == difficulty else "", d)
        for d in range(1, 6))

    trs = []
    for r in rows[:200]:
        try:
            options = json.loads(r["options"])
        except (TypeError, ValueError):
            options = []
        answer_text = options[r["answer"]] if 0 <= r["answer"] < len(options) else "—"
        stem = r["stem"]
        if len(stem) > 64:
            stem = stem[:64] + "…"
        trs.append(
            "<tr><td><span class='pill'>%s</span></td><td>%s</td>"
            "<td><span class='pill d%d'>%d</span></td><td>%s</td><td class='good'>%s</td>"
            "<td style='white-space:nowrap'>"
            "<a class='btn small ghost' href='/questions/edit?id=%s'>编辑</a> "
            "<form method='post' action='/questions/delete' style='display:inline' "
            "onsubmit=\"return confirm('确定删除这道题？')\">"
            "<input type='hidden' name='id' value='%s'>"
            "<button class='btn small danger' type='submit'>删除</button></form></td></tr>"
            % (html.escape(r["subject"]), html.escape(r["kp"]),
               r["difficulty"], r["difficulty"], html.escape(stem),
               html.escape(str(answer_text)), urllib.parse.quote(r["id"]),
               html.escape(r["id"]))
        )
    if not trs:
        trs.append("<tr><td colspan='6' class='muted'>没有符合条件的题目</td></tr>")

    table = (
        "<table><tr><th>科目</th><th>知识点</th><th>难度</th><th>题干</th>"
        "<th>答案</th><th>操作</th></tr>%s</table>" % "".join(trs)
    )
    count = len(rows)
    note = ("<div class='sub'>共 %d 题；列表最多显示 200 题，用筛选缩小范围。</div>" % count
            if count > 200 else "<div class='sub'>共 %d 题</div>" % count)
    if imported:
        note = "<p class='good'>已导入 %s 道题。</p>" % html.escape(imported) + note

    body = (
        "<h1>题库</h1><div class='sub'>新增、编辑、删除、导入导出都在这里。</div>"
        + tabs_html
        + "<div class='toolbar'>"
        "<a class='btn' href='/questions/new'>+ 新增题目</a>"
        "<a class='btn ghost' href='/questions/export'>导出 JSON</a>"
        "<form method='post' action='/questions/reload' style='display:inline'>"
        "<button class='btn ghost' type='submit'>从 questions.json 重新载入</button></form>"
        "</div>"
        "<form method='get' action='/questions' class='toolbar'>"
        "<select name='subject'>%s</select>"
        "<input type='text' name='kp' value='%s' placeholder='知识点'>"
        "<select name='difficulty'>%s</select>"
        "<input type='text' name='q' value='%s' placeholder='题干/解析关键词'>"
        "<button class='btn small' type='submit'>筛选</button>"
        "</form>"
        + note + table
        + "<details><summary>批量导入（粘贴 JSON）</summary>"
          "<form method='post' action='/questions/import'>"
          "<p class='sub'>支持整个 questions.json 内容或题目数组；同 id 会覆盖。</p>"
          "<textarea class='code' name='payload' "
          "placeholder='把 questions.json 的内容粘贴到这里'></textarea>"
          "<div style='margin-top:12px'><button class='btn' type='submit'>导入</button></div>"
          "</form></details>"
    )
    return layout("题库", "questions", body)


def question_form_page(data=None, error=""):
    data = data or {}
    options = data.get("options") or []
    options_text = "\n".join(str(o) for o in options)
    subject = data.get("subject", "数学")
    kp = data.get("kp", "")
    stem = data.get("stem", "")
    explain = data.get("explain", "")
    qid = data.get("id", "")
    try:
        grade = int(data.get("grade", 4) or 0)
    except (TypeError, ValueError):
        grade = 0
    try:
        difficulty = int(data.get("difficulty", 1) or 1)
    except (TypeError, ValueError):
        difficulty = 1
    try:
        answer = int(data.get("answer", 1) or 1)
    except (TypeError, ValueError):
        answer = 1

    subject_options = ["数学", "语文", "英语", "科学", "其他"]
    if subject not in subject_options:
        subject_options.append(subject)
    subject_html = "".join(
        "<option value='%s'%s>%s</option>"
        % (html.escape(str(s)), " selected" if s == subject else "", html.escape(str(s)))
        for s in subject_options)
    difficulty_html = "".join(
        "<option value='%d'%s>%d</option>"
        % (d, " selected" if int(difficulty) == d else "", d)
        for d in range(1, 6))

    body = (
        "<h1>%s</h1><div class='sub'><a href='/questions'>← 返回题库</a></div>"
        % ("编辑题目" if qid else "新增题目")
        + ("<p class='bad'>%s</p>" % html.escape(error) if error else "")
        + "<form method='post' action='/questions/save'>"
          "<input type='hidden' name='id' value='%s'>"
          "<div class='grid2'>"
          "<div><label>科目</label><select name='subject'>%s</select></div>"
          "<div><label>年级</label><input type='number' name='grade' min='0' max='9' value='%d'></div>"
          "<div><label>知识点</label><input type='text' name='kp' value='%s' required></div>"
          "<div><label>难度（1–5）</label><select name='difficulty'>%s</select></div>"
          "</div>"
          "<label>题干</label><textarea name='stem' required>%s</textarea>"
          "<label>选项（每行一个，至少 2 个）</label><textarea name='options' required>%s</textarea>"
          "<label>正确答案（第几个选项，从 1 开始）</label>"
          "<input type='number' name='answer' min='1' value='%d'>"
          "<label>解析（可选）</label><textarea name='explain'>%s</textarea>"
          "<div style='margin-top:16px'><button class='btn' type='submit'>保存</button>"
          "<a class='btn ghost' href='/questions' style='margin-left:8px'>取消</a></div>"
          "</form>"
          % (html.escape(str(qid)), subject_html, grade, html.escape(str(kp)),
             difficulty_html, html.escape(str(stem)), html.escape(options_text),
             answer, html.escape(str(explain)))
    )
    return layout("编辑题目" if qid else "新增题目", "questions", body)


def format_duration(seconds):
    seconds = int(seconds or 0)
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return "%d 小时 %d 分" % (hours, minutes)
    if minutes:
        return "%d 分钟" % minutes
    return "%d 秒" % seconds


def view_summary(conn, days=0, daily_days=14):
    since = 0 if days <= 0 else time.time() - days * 86400
    params = (since,) if since else ()
    extra = " AND started_ts >= ?" if since else ""
    rows = conn.execute(
        "SELECT date, COUNT(*) AS sessions, SUM(duration_seconds) AS seconds"
        " FROM view_sessions WHERE duration_seconds >= 60" + extra
        + " GROUP BY date ORDER BY date DESC", params).fetchall()
    by_date = {r["date"]: (r["sessions"], r["seconds"] or 0) for r in rows}

    today = time.strftime("%Y-%m-%d")
    today_sessions, today_seconds = by_date.get(today, (0, 0))
    total_sessions = sum(n for n, _ in by_date.values())
    total_seconds = sum(s for _, s in by_date.values())

    last7 = []
    for i in range(7):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        last7.append(by_date.get(d, (0, 0))[1])
    avg7 = sum(last7) / 7.0

    daily = []
    for i in range(daily_days):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        n, s = by_date.get(d, (0, 0))
        daily.append({"date": d, "sessions": n, "seconds": s})

    apps = conn.execute(
        "SELECT app_pkg, SUM(duration_seconds) AS seconds, COUNT(*) AS n"
        " FROM view_sessions WHERE duration_seconds >= 60 AND app_pkg != ''"
        + extra + " GROUP BY app_pkg ORDER BY seconds DESC LIMIT 6",
        params).fetchall()
    return {
        "today_seconds": today_seconds, "today_sessions": today_sessions,
        "total_seconds": total_seconds, "total_sessions": total_sessions,
        "avg7_seconds": avg7, "daily": daily,
        "apps": [{"pkg": r["app_pkg"], "seconds": r["seconds"] or 0,
                  "sessions": r["n"]} for r in apps],
    }


def view_stats_page(conn):
    data = view_summary(conn, 0, 14)
    peak = max([d["seconds"] for d in data["daily"]] + [1])
    rows = []
    for d in data["daily"]:
        width = int(100 * d["seconds"] / peak)
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%d</td>"
            "<td><div class='bar'><i style='width:%d%%'></i></div></td></tr>"
            % (d["date"], format_duration(d["seconds"]), d["sessions"], width))
    daily_table = (
        "<table><tr><th>日期</th><th>观看时长</th><th>次数</th><th></th></tr>"
        "%s</table>" % "".join(rows))

    app_rows = []
    for a in data["apps"]:
        app_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%d</td></tr>"
            % (html.escape(a["pkg"]), format_duration(a["seconds"]),
               a["sessions"]))
    if not app_rows:
        app_rows.append("<tr><td colspan='3' class='muted'>暂无数据</td></tr>")
    app_table = (
        "<table><tr><th>App</th><th>观看时长</th><th>次数</th></tr>%s</table>"
        % "".join(app_rows))

    cards = (
        "<div class='cards'>"
        "<div class='card'><div class='k'>今日观看</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>今日次数</div><div class='v'>%d</div></div>"
        "<div class='card'><div class='k'>最近 7 天日均</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>累计观看</div><div class='v'>%s</div></div>"
        "<div class='card'><div class='k'>累计次数</div><div class='v'>%d</div></div>"
        "</div>"
        % (format_duration(data["today_seconds"]), data["today_sessions"],
           format_duration(data["avg7_seconds"]),
           format_duration(data["total_seconds"]), data["total_sessions"])
    )
    body = (
        "<h1>观看统计</h1>"
        "<div class='sub'>按 Fire TV 前台是视频 App 的时间累计；桌面、设置、答题界面不计入。"
        "一次观看 = 连续观看且中途离开不超过 3 分钟。</div>"
        + cards
        + "<h2>最近 14 天</h2>" + daily_table
        + "<h2>常用 App</h2>" + app_table
        + "<p class='sub'>说明：云视听等不注册 MediaSession 的 App 无法区分暂停，"
          "暂停时间可能被计入；跨午夜的会话记在开始那天。</p>"
    )
    return layout("观看统计", "view", body)


def report_data(conn, days=30):
    since = 0 if days <= 0 else time.time() - days * 86400
    params = (since,) if since else ()
    where = " WHERE ts >= ?" if since else ""
    rows = conn.execute(
        "SELECT ts, subject, kp, difficulty, correct, timed_out, response_ms"
        " FROM attempts" + where + " ORDER BY id DESC", params).fetchall()

    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    grouped = {}
    for r in rows:
        subject = r["subject"] or "未分类"
        kp = r["kp"] or "未分类"
        bucket = grouped.setdefault(subject, {}).setdefault(kp, {"n": 0, "c": 0})
        bucket["n"] += 1
        bucket["c"] += 1 if r["correct"] else 0

    subjects = []
    for subject in sorted(grouped):
        kps = []
        for kp, bucket in grouped[subject].items():
            accuracy = bucket["c"] / bucket["n"] if bucket["n"] else 0.0
            mastery = accuracy * min(1.0, bucket["n"] / 5.0)
            kps.append({"kp": kp, "n": bucket["n"], "correct": bucket["c"],
                        "accuracy": accuracy, "mastery": mastery})
        kps.sort(key=lambda x: (x["mastery"], -x["n"]))
        subjects.append({"subject": subject, "kps": kps,
                         "n": sum(k["n"] for k in kps),
                         "correct": sum(k["correct"] for k in kps)})

    wrong = [w for w in compute_wrong_book(conn, False)
             if not since or (w["last_wrong_ts"] or 0) >= since]
    recent = [{
        "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])),
        "subject": r["subject"] or "", "kp": r["kp"] or "",
        "difficulty": r["difficulty"] or 0,
        "result": "正确" if r["correct"] else ("超时" if r["timed_out"] else "错误"),
    } for r in rows[:20]]

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "days": days,
        "since": time.strftime("%Y-%m-%d", time.localtime(since)) if since else "全部",
        "total": total, "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "wrong_count": len(wrong),
        "subjects": subjects, "wrong_book": wrong, "recent": recent,
        "view": view_summary(conn, days,
                             daily_days=min(days, 30) if days > 0 else 14),
    }


def report_markdown(conn, days=30):
    data = report_data(conn, days)
    lines = [
        "# 孩子电视学习报告",
        "",
        "- 生成时间：%s" % data["generated_at"],
        "- 统计区间：%s" % ("最近 %d 天" % days if days > 0 else "全部"),
        "- 总作答：%d 次" % data["total"],
        "- 总体正确率：%s" % ("%.0f%%" % (data["accuracy"] * 100) if data["total"] else "—"),
        "- 待复习错题：%d 道" % data["wrong_count"],
        "",
        "## 给大模型的提示词",
        "",
        "你是一位经验丰富的小学四年级老师。请根据下面的学习报告，分析孩子的薄弱环节，"
        "指出需要优先复习的 3–5 个知识点，并给出未来两周可执行的复习计划"
        "（每天 15–20 分钟）。要求：先肯定进步，再指出问题；建议要具体到知识点和练习方式。"
        "同时结合观看时长和次数，判断是否存在长时间连续观看，并给出作息建议。",
        "",
        "## 分科掌握情况",
        "",
    ]
    for subject in data["subjects"]:
        lines.append("### %s" % subject["subject"])
        lines.append("")
        lines.append("| 知识点 | 作答 | 正确 | 正确率 | 掌握度 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for item in subject["kps"]:
            lines.append("| %s | %d | %d | %.0f%% | %d%% |"
                         % (item["kp"], item["n"], item["correct"],
                            item["accuracy"] * 100, item["mastery"] * 100))
        lines.append("")
    if not data["subjects"]:
        lines.append("暂无答题数据。")
        lines.append("")

    view = data["view"]
    lines.append("## 观看统计")
    lines.append("")
    lines.append("- 区间内观看：%s，共 %d 次"
                 % (format_duration(view["total_seconds"]), view["total_sessions"]))
    lines.append("- 最近 7 天日均：%s" % format_duration(view["avg7_seconds"]))
    lines.append("- 今日观看：%s，共 %d 次"
                 % (format_duration(view["today_seconds"]), view["today_sessions"]))
    lines.append("")
    lines.append("| 日期 | 时长 | 次数 |")
    lines.append("| --- | ---: | ---: |")
    for d in view["daily"]:
        lines.append("| %s | %s | %d |"
                     % (d["date"], format_duration(d["seconds"]), d["sessions"]))
    if view["apps"]:
        lines.append("")
        lines.append("### 常用 App")
        lines.append("")
        lines.append("| App | 时长 | 次数 |")
        lines.append("| --- | ---: | ---: |")
        for a in view["apps"]:
            lines.append("| %s | %s | %d |"
                         % (a["pkg"], format_duration(a["seconds"]),
                            a["sessions"]))
    lines.append("")

    weak = []
    for subject in data["subjects"]:
        for item in subject["kps"]:
            weak.append((subject["subject"], item))
    weak.sort(key=lambda x: (x[1]["mastery"], -x[1]["n"]))

    lines.append("## 薄弱知识点（按掌握度升序）")
    lines.append("")
    if weak:
        for idx, (subject, item) in enumerate(weak[:8], 1):
            lines.append("%d. **%s** · %s：作答 %d 次，正确率 %.0f%%，掌握度 %d%%"
                         % (idx, subject, item["kp"], item["n"],
                            item["accuracy"] * 100, item["mastery"] * 100))
    else:
        lines.append("暂无数据。")
    lines.append("")

    lines.append("## 错题本（未掌握）")
    lines.append("")
    if data["wrong_book"]:
        for idx, item in enumerate(data["wrong_book"], 1):
            stem = (item["stem"] or "").replace("\n", " ")
            if len(stem) > 300:
                stem = stem[:300] + "…"
            lines.append("### %d. [%s] %s · 难度 %d · 错 %d 次"
                         % (idx, item["subject"], item["kp"], item["difficulty"],
                            item["wrong_count"]))
            lines.append("")
            lines.append("**题干**：%s" % stem)
            lines.append("")
            for i, opt in enumerate(item["options"]):
                mark = " ✅" if i == item["answer"] else ""
                lines.append("- %s. %s%s" % (chr(65 + i), opt, mark))
            lines.append("")
            lines.append("**正确答案**：%s"
                         % (chr(65 + item["answer"]) if 0 <= item["answer"] < len(item["options"]) else "—"))
            lines.append("")
            lines.append("**解析**：%s" % (item["explain"] or "—"))
            lines.append("")
    else:
        lines.append("暂无未掌握的错题。")
        lines.append("")

    lines.append("## 最近答题记录")
    lines.append("")
    lines.append("| 时间 | 科目 | 知识点 | 难度 | 结果 |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for r in data["recent"]:
        lines.append("| %s | %s | %s | %d | %s |"
                     % (r["time"], r["subject"], r["kp"], r["difficulty"], r["result"]))
    if not data["recent"]:
        lines.append("| — | — | — | — | — |")
    lines.append("")
    lines.append("## 建议的复习方向")
    lines.append("")
    if weak:
        for subject, item in weak[:5]:
            lines.append("- 优先复习 **%s** 的「%s」，建议先做 5–10 道同类题，"
                         "再回顾错题本里的对应题目。" % (subject, item["kp"]))
    else:
        lines.append("- 暂无数据，建议先完成几轮答题后再看报告。")
    lines.append("")
    return "\n".join(lines)


def report_json(conn, days=30):
    return json.dumps(report_data(conn, days), ensure_ascii=False, indent=2)


def report_page(conn, days=30):
    markdown = report_markdown(conn, days)
    options = "".join(
        "<option value='%d'%s>%s</option>"
        % (value, " selected" if days == value else "", label)
        for value, label in [(7, "最近 7 天"), (30, "最近 30 天"),
                             (90, "最近 90 天"), (0, "全部")])
    body = (
        "<h1>学习报告</h1>"
        "<div class='sub'>下载 Markdown 后可以直接发给大模型分析；也可以复制下面的预览内容。</div>"
        "<form method='get' action='/report' class='toolbar'>"
        "<select name='days'>%s</select>"
        "<button class='btn' type='submit'>生成预览</button>"
        "</form>"
        "<div class='toolbar'>"
        "<a class='btn' href='/report.md?days=%d'>下载 Markdown</a>"
        "<a class='btn ghost' href='/report.json?days=%d'>下载 JSON</a>"
        "</div>"
        "<pre class='report'>%s</pre>"
        % (options, days, days, html.escape(markdown))
    )
    return layout("报告", "report", body)


def save_question_payload(conn, form):
    qid = _form_first(form, "id").strip()
    subject = _form_first(form, "subject").strip() or "其他"
    kp = _form_first(form, "kp").strip()
    stem = _form_first(form, "stem").strip()
    explain = _form_first(form, "explain").strip()
    options = _clean_options(_form_first(form, "options"))
    try:
        grade = int(_form_first(form, "grade", "0") or 0)
    except ValueError:
        grade = 0
    try:
        difficulty = int(_form_first(form, "difficulty", "1") or 1)
    except ValueError:
        difficulty = 1
    difficulty = max(1, min(5, difficulty))
    try:
        answer = int(_form_first(form, "answer", "1") or 1)
    except ValueError:
        answer = 1

    data = {
        "id": qid, "subject": subject, "grade": grade, "kp": kp,
        "difficulty": difficulty, "stem": stem, "options": options,
        "answer": answer, "explain": explain,
    }
    if not kp:
        return None, "知识点不能为空", data
    if not stem:
        return None, "题干不能为空", data
    if len(options) < 2:
        return None, "至少需要两个选项", data
    if not (1 <= answer <= len(options)):
        return None, "正确答案必须在 1–%d 之间" % len(options), data
    if not qid:
        qid = "q-%d" % int(time.time() * 1000)
    data["id"] = qid
    data["answer"] = answer - 1
    upsert_question(conn, data)
    return qid, "", data


def import_questions_payload(conn, raw):
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        return 0, "JSON 解析失败：%s" % exc
    items = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return 0, '格式不对：期望 {"questions": [...]} 或题目数组'
    count = 0
    for item in items:
        try:
            options = item["options"]
            if not isinstance(options, list) or len(options) < 2:
                continue
            answer = int(item["answer"])
            if not (0 <= answer < len(options)):
                continue
            qid = str(item.get("id") or ("q-%d-%d" % (int(time.time() * 1000), count)))
            upsert_question(conn, {
                "id": qid,
                "subject": str(item.get("subject", "其他")),
                "grade": int(item.get("grade", 0) or 0),
                "kp": str(item.get("kp", "未分类")),
                "difficulty": max(1, min(5, int(item.get("difficulty", 1)))),
                "stem": str(item["stem"]),
                "options": [str(o) for o in options],
                "answer": answer,
                "explain": str(item.get("explain", "")),
            })
            count += 1
        except (KeyError, TypeError, ValueError):
            continue
    return count, ""


def settings_page(conn):
    s = read_settings(conn)

    until = float(s.get("suspend_until", "0") or 0)
    remaining = max(0, int((until - time.time()) / 60))
    suspend_note = ""
    if remaining > 0:
        suspend_note = (
            "<div class='card' style='margin-bottom:14px'>"
            "<div class='k'>家长模式</div>"
            "<div class='v'>剩余约 %d 分钟</div>"
            "<form method='post' action='/suspend/clear' style='margin-top:10px'>"
            "<button class='btn small' type='submit'>立即恢复管控</button>"
            "</form></div>" % remaining
        )

    def field(label, name, help_text, value="", minv="", maxv="", kind="number"):
        limits = ""
        if minv != "":
            limits += " min='%s'" % minv
        if maxv != "":
            limits += " max='%s'" % maxv
        return (
            "<div><label>%s</label>"
            "<input type='%s' name='%s' value='%s'%s>"
            "<div class='help'>%s</div></div>"
            % (label, kind, name, value, limits, help_text)
        )

    def check(name, value, label, help_text):
        return (
            "<div style='margin:12px 0'>"
            "<label style='display:inline'><input type='checkbox' name='%s'"
            " value='1'%s> %s</label>"
            "<div class='help'>%s</div></div>"
            % (name, " checked" if value == "1" else "", label, help_text)
        )

    general = (
        field("检查间隔（秒）", "interval_seconds",
              "每看满多少秒弹一次题。这是弹题频率，不是单次观看上限。",
              s.get("interval_seconds", "600"), "5")
        + field("最高难度档", "max_difficulty",
                "控制器最多用到第几档难度；题库目前适合 1–3。",
                s.get("max_difficulty", "3"), "1", "10")
        + field("每题限时（秒）", "answer_timeout_seconds",
                "单题最长作答时间，超时按答错处理。",
                s.get("answer_timeout_seconds", "120"), "10")
        + field("每次暂停需答对题数（1–5）", "correct_required",
                "一次暂停要答对几题才恢复播放。",
                s.get("correct_required", "1"), "1", "5")
    )
    general_checks = (
        check("require_consecutive", s.get("require_consecutive", "1"),
              "必须连续答对",
              "勾选后答错会清零已答对进度；不勾则按累计答对数计算。")
        + check("prefer_wrong", s.get("prefer_wrong", "1"),
                "优先出错题本里的题",
                "每次出题先从未掌握的错题里选，再回退到普通题库。")
        + check("quiz_enabled", s.get("quiz_enabled", "1"),
                "开启答题检查",
                "关闭后不弹常规检查点；单次观看上限和两次观看间隔仍会触发刷题。")
    )

    advanced = (
        field("ADB 轮询间隔（秒）", "poll_seconds",
              "控制器多久读取一次 Fire TV 状态。越小反应越快，但 ADB 调用更频繁；"
              "默认 2 秒。",
              s.get("poll_seconds", "2"), "1", "10")
        + field("观看会话间隔（秒）", "view_gap_seconds",
                "统计用：中途离开超过这个秒数就算新的一次观看；不影响弹题。",
                s.get("view_gap_seconds", "180"), "60", "3600")
        + field("单次观看上限（分钟）", "max_view_minutes",
                "连续观看达到这个分钟数后强制进入刷题模式；0 表示关闭。",
                s.get("max_view_minutes", "0"), "0", "240")
        + field("强制刷题时长（分钟）", "drill_minutes",
                "触发单次上限后，强制刷题多久，结束后才能继续看。",
                s.get("drill_minutes", "10"), "1", "60")
        + field("两次观看间隔（分钟）", "cooldown_minutes",
                "一次观看结束后，在这个时间内又开始看，会直接进入刷题，"
                "直到间隔结束；0 表示关闭。",
                s.get("cooldown_minutes", "0"), "0", "720")
        + field("家长退出暂停时长（分钟）", "parent_suspend_minutes",
                "在电视上输入 PIN 退出后，暂停管控多久。",
                s.get("parent_suspend_minutes", "30"), "1", "720")
        + field("家长模式闲置重置（分钟）", "parent_reset_minutes",
                "家长退出后，电视闲置超过这个时间就自动恢复管控；"
                "下次开电视默认受控。",
                s.get("parent_reset_minutes", "10"), "1", "120")
        + field("家长端 PIN", "admin_pin",
                "4–12 位字母数字；后台登录和 TV 端退出共用。留空不改。",
                "", kind="text")
    )

    form = (
        "<form method='post' action='/settings'>"
        "<h2 style='margin-top:0'>通用设置</h2>"
        "<div class='sub'>题目与答题相关</div>"
        "<div class='grid2'>" + general + "</div>"
        + general_checks
        + "<h2>高级设置</h2>"
        "<div class='sub'>时长、ADB 与系统行为</div>"
        "<div class='grid2'>" + advanced + "</div>"
        + "<div style='margin-top:16px'>"
          "<button class='btn' type='submit'>保存设置</button></div>"
          "</form>"
    )
    body = (
        "<h1>系统设置</h1>"
        "<div class='sub'>修改后当前检查周期结束后生效；"
        "容器重启时以 .env 的 INTERVAL 为准。</div>"
        + suspend_note + form
    )
    return layout("系统设置", "settings", body)


def save_settings(conn, form):
    def first(key, default=""):
        return form.get(key, [default])[0]

    def clamp_int(key, default, lo, hi):
        try:
            value = int(first(key, str(default)))
        except (TypeError, ValueError):
            value = default
        return str(max(lo, min(hi, value)))

    set_setting(conn, "interval_seconds", clamp_int("interval_seconds", 600, 5, 86400))
    set_setting(conn, "poll_seconds", clamp_int("poll_seconds", 2, 1, 10))
    set_setting(conn, "max_difficulty", clamp_int("max_difficulty", 3, 1, 10))
    set_setting(conn, "answer_timeout_seconds", clamp_int("answer_timeout_seconds", 120, 10, 3600))
    set_setting(conn, "correct_required", clamp_int("correct_required", 1, 1, 5))
    set_setting(conn, "view_gap_seconds", clamp_int("view_gap_seconds", 180, 60, 3600))
    set_setting(conn, "max_view_minutes", clamp_int("max_view_minutes", 0, 0, 240))
    set_setting(conn, "drill_minutes", clamp_int("drill_minutes", 10, 1, 60))
    set_setting(conn, "cooldown_minutes", clamp_int("cooldown_minutes", 0, 0, 720))
    set_setting(conn, "parent_suspend_minutes",
                clamp_int("parent_suspend_minutes", 30, 1, 720))
    set_setting(conn, "parent_reset_minutes",
                clamp_int("parent_reset_minutes", 10, 1, 120))
    set_setting(conn, "require_consecutive", "1" if "require_consecutive" in form else "0")
    set_setting(conn, "prefer_wrong", "1" if "prefer_wrong" in form else "0")
    set_setting(conn, "quiz_enabled", "1" if "quiz_enabled" in form else "0")

    pin = first("admin_pin", "").strip()
    if pin and 4 <= len(pin) <= 12 and pin.isalnum():
        set_setting(conn, "admin_pin", pin)


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "tvgate/0.1"

    def log_message(self, fmt, *args):
        pass

    def _authed(self):
        conn = connect()
        try:
            pin = read_settings(conn)["admin_pin"]
        finally:
            conn.close()
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("tvgate_pin")
        return bool(morsel) and hmac.compare_digest(morsel.value, pin)

    def _send(self, text, status=200, headers=None,
              content_type="text/html; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or []):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api_quiz_current(self):
        """Fire TV 答题 App 拉取当前题目。"""
        if FIRE_CONTROLLER is None:
            return self._send_json({"finished": True, "error": "firetv mode off"})
        payload = FIRE_CONTROLLER.current_payload()
        print("[api] current from %s -> finished=%s"
              % (self.client_address[0], payload.get("finished")))
        return self._send_json(payload)

    def _api_quiz_answer(self, raw):
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return self._send_json({"error": "bad json"}, 400)
        if FIRE_CONTROLLER is None:
            return self._send_json({"correct": False, "finished": True,
                                    "error": "firetv mode off"}, 503)
        result = FIRE_CONTROLLER.answer(data)
        print("[api] answer from %s: %s -> correct=%s"
              % (self.client_address[0], data.get("question_id"), result.get("correct")))
        return self._send_json(result)

    def _api_quiz_exit(self, raw):
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return self._send_json({"ok": False, "error": "bad json"}, 400)
        if FIRE_CONTROLLER is None:
            return self._send_json({"ok": False, "error": "firetv mode off"}, 503)
        result = FIRE_CONTROLLER.parent_exit(data.get("pin", ""))
        print("[api] parent exit from %s -> %s"
              % (self.client_address[0], result.get("ok")))
        return self._send_json(result)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/quiz/current":
            return self._api_quiz_current()
        if path == "/logout":
            return self._send("", 302, [("Set-Cookie", "tvgate_pin=; Max-Age=0; Path=/"),
                                        ("Location", "/")])
        if path in ("/", "/knowledge", "/wrong", "/questions", "/questions/new",
                    "/questions/edit", "/questions/export", "/view", "/settings",
                    "/report", "/report.md", "/report.json"):
            if not self._authed():
                return self._send(login_page())
            conn = connect()
            try:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                try:
                    days = int(_form_first(query, "days", "30") or 30)
                except ValueError:
                    days = 30
                days = max(0, min(3650, days))
                if path == "/":
                    return self._send(dashboard_page(conn))
                if path == "/knowledge":
                    return self._send(knowledge_page(conn))
                if path == "/wrong":
                    include = _form_first(query, "all") == "1"
                    return self._send(wrong_page(conn, include))
                if path == "/questions":
                    return self._send(questions_page(conn, query))
                if path == "/questions/new":
                    return self._send(question_form_page({}))
                if path == "/questions/edit":
                    row = get_question(conn, _form_first(query, "id"))
                    if row is None:
                        return self._send("", 302, [("Location", "/questions")])
                    try:
                        options = json.loads(row["options"])
                    except (TypeError, ValueError):
                        options = []
                    data = {
                        "id": row["id"], "subject": row["subject"],
                        "grade": row["grade"], "kp": row["kp"],
                        "difficulty": row["difficulty"], "stem": row["stem"],
                        "options": options, "answer": row["answer"] + 1,
                        "explain": row["explain"],
                    }
                    return self._send(question_form_page(data))
                if path == "/questions/export":
                    return self._send(
                        export_questions_payload(conn), 200,
                        [("Content-Disposition",
                          'attachment; filename="questions.json"')],
                        content_type="application/json; charset=utf-8")
                if path == "/view":
                    return self._send(view_stats_page(conn))
                if path == "/settings":
                    return self._send(settings_page(conn))
                if path == "/report":
                    return self._send(report_page(conn, days))
                if path == "/report.md":
                    return self._send(
                        report_markdown(conn, days), 200,
                        [("Content-Disposition",
                          'attachment; filename="tvgate-report-%s.md"'
                          % time.strftime("%Y%m%d"))],
                        content_type="text/markdown; charset=utf-8")
                if path == "/report.json":
                    return self._send(
                        report_json(conn, days), 200,
                        [("Content-Disposition",
                          'attachment; filename="tvgate-report-%s.json"'
                          % time.strftime("%Y%m%d"))],
                        content_type="application/json; charset=utf-8")
            finally:
                conn.close()
        self._send("not found", 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")

        if path == "/api/quiz/answer":
            return self._api_quiz_answer(raw)
        if path == "/api/quiz/exit":
            return self._api_quiz_exit(raw)

        form = urllib.parse.parse_qs(raw)

        if path == "/login":
            conn = connect()
            try:
                pin = read_settings(conn)["admin_pin"]
            finally:
                conn.close()
            got = form.get("pin", [""])[0]
            if got and hmac.compare_digest(got, pin):
                return self._send("", 302, [
                    ("Set-Cookie", "tvgate_pin=%s; Path=/; HttpOnly; SameSite=Lax" % pin),
                    ("Location", "/")])
            return self._send(login_page("PIN 不对"))

        if path == "/settings":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                save_settings(conn, form)
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/settings")])

        if path == "/suspend/clear":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                set_setting(conn, "suspend_until", "0")
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/settings")])

        if path == "/questions/save":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                _, error, data = save_question_payload(conn, form)
                if error:
                    return self._send(question_form_page(data, error), 400)
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/questions")])

        if path == "/questions/delete":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                delete_question(conn, _form_first(form, "id"))
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/questions")])

        if path == "/questions/reload":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                count = load_bank(conn)
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/questions?imported=%d" % count)])

        if path == "/questions/import":
            if not self._authed():
                return self._send("forbidden", 403)
            conn = connect()
            try:
                count, error = import_questions_payload(
                    conn, _form_first(form, "payload"))
            finally:
                conn.close()
            if error:
                return self._send(
                    layout("导入失败", "questions",
                           "<h1>导入失败</h1><p class='bad'>%s</p>"
                           "<p><a class='btn ghost' href='/questions'>返回题库</a></p>"
                           % html.escape(error)), 400)
            return self._send("", 302, [("Location", "/questions?imported=%d" % count)])

        if path == "/wrong/resolve":
            if not self._authed():
                return self._send("forbidden", 403)
            qid = _form_first(form, "id")
            action = _form_first(form, "action")
            conn = connect()
            try:
                if action == "reopen":
                    conn.execute(
                        "UPDATE wrong_book SET resolved_ts=NULL WHERE question_id=?",
                        (qid,))
                else:
                    conn.execute(
                        "UPDATE wrong_book SET resolved_ts=? WHERE question_id=?",
                        (time.time(), qid))
                conn.commit()
            finally:
                conn.close()
            return self._send("", 302, [("Location", "/wrong")])

        self._send("not found", 404)


def start_admin(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), AdminHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def local_ip():
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


# ---------------------------------------------------------------- Fire TV 控制

QUIZ_PACKAGE = "com.tvgate.quiz"
LAUNCHER_PACKAGES = {
    "com.amazon.tv.launcher",
    "com.amazon.venezia",
    "com.amazon.tv.leansettings",
    "com.amazon.tv.settings",
    "com.amazon.tv.settings.v2",
    "com.amazon.device.settings",
    "com.amazon.tv.notificationcenter",
    "com.amazon.ftv.screensaver",
    "com.dangbei.tvlauncher",
    "com.dangbeimarket",
}


def adb_run(serial, *args, timeout=15):
    try:
        proc = subprocess.run(
            ["adb", "-s", serial] + [str(a) for a in args],
            capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "adb 未安装"
    except subprocess.TimeoutExpired:
        return 124, "", "adb 超时"


def adb_connect(ip):
    serial = "%s:5555" % ip
    # Fire TV 休眠后 TCP 会变成半开，直接 connect 会误报「已连接」。
    # 先 disconnect 再 connect，确保拿到新的 transport。
    try:
        subprocess.run(["adb", "disconnect", serial],
                       capture_output=True, text=True, timeout=8)
    except Exception:
        pass
    try:
        subprocess.run(["adb", "connect", serial],
                       capture_output=True, text=True, timeout=12)
    except Exception:
        pass
    return serial


def firetv_media_state(serial):
    """返回 (包名, 播放状态)。状态 3=播放，2=暂停，6=缓冲；没会话返回 ('', -1)。"""
    rc, out, _ = adb_run(serial, "shell", "dumpsys", "media_session", timeout=20)
    if rc != 0:
        return None, -1
    sessions = []
    for block in out.split("Media session:")[1:]:
        match = re.search(r"PlaybackState \{state=(\d+)", block)
        if match:
            pkg = re.search(r"package=([\w.]+)", block)
            sessions.append((pkg.group(1) if pkg else "?", int(match.group(1))))
    for pkg, state in sessions:
        if state == 3:
            return pkg, 3
    if sessions:
        return sessions[0]
    return "", -1


def firetv_playing(serial):
    """正在播放则返回包名，没在播返回 ''，adb 出错返回 None。"""
    pkg, state = firetv_media_state(serial)
    if state == 3:
        return pkg
    if state == -1 and pkg is None:
        return None
    return ""


def firetv_watching(serial):
    """是否在看内容：优先看 MediaSession，其次看前台 App。

    云视听等 App 不注册 MediaSession，只能靠前台 Activity 判断。
    暂停状态无法区分，但「打开视频 App 的时间」本身就算屏幕时间。
    """
    pkg, state = firetv_media_state(serial)
    if state == 3:
        return pkg
    foreground = firetv_foreground(serial)
    if foreground and foreground not in LAUNCHER_PACKAGES \
            and not foreground.startswith(QUIZ_PACKAGE):
        return foreground
    return ""


def firetv_foreground(serial):
    rc, out, _ = adb_run(serial, "shell", "dumpsys", "window", timeout=20)
    if rc != 0:
        return ""
    for line in out.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            match = re.search(r"([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/", line)
            if match:
                return match.group(1)
    return ""


class ViewTracker:
    """把每 2 秒的观看状态聚合成观看会话，写入 view_sessions。

    会话规则：连续观看中离开不超过 gap 秒仍算同一次；
    只在 watching 为真时累加时长，答题/桌面/设置不计入。
    """

    def __init__(self, conn, device="firetv", gap_seconds=180):
        self.conn = conn
        self.device = device
        self.gap = gap_seconds
        self.open_id = None
        self.open_seconds = 0
        self.last_tick = time.time()
        self.last_seen = 0.0
        self.last_ended = self._latest_end()
        self.close_stale()

    def _latest_end(self):
        row = self.conn.execute(
            "SELECT MAX(ended_ts) AS t FROM view_sessions").fetchone()
        return float(row["t"] or 0.0) if row else 0.0

    def close_stale(self):
        # 控制器重启后，把上次没关闭的会话按最后心跳收尾
        self.conn.execute(
            "UPDATE view_sessions SET ended_ts=updated_ts WHERE ended_ts IS NULL")
        self.conn.commit()
        self.open_id = None
        self.open_seconds = 0
        self.last_ended = self._latest_end()

    def pause(self, now):
        """家长/刷题模式：结束当前会话，暂停计时。"""
        if self.open_id is not None:
            self.conn.execute(
                "UPDATE view_sessions SET ended_ts=? WHERE id=?",
                (self.last_seen, self.open_id))
            self.conn.commit()
            self.open_id = None
            if self.last_seen:
                self.last_ended = self.last_seen
        self.open_seconds = 0
        self.last_tick = now

    def update(self, now, app_pkg):
        if app_pkg:
            if self.open_id is None:
                date = time.strftime("%Y-%m-%d", time.localtime(now))
                cur = self.conn.execute(
                    "INSERT INTO view_sessions(device, app_pkg, started_ts,"
                    " duration_seconds, updated_ts, date) VALUES(?, ?, ?, 0, ?, ?)",
                    (self.device, app_pkg, now, now, date))
                self.open_id = cur.lastrowid
                self.open_seconds = 0
                self.last_tick = now
            else:
                delta = max(0, int(round(now - self.last_tick)))
                if delta:
                    self.conn.execute(
                        "UPDATE view_sessions SET duration_seconds=duration_seconds+?,"
                        " updated_ts=?, app_pkg=? WHERE id=?",
                        (delta, now, app_pkg, self.open_id))
                    self.open_seconds += delta
                else:
                    self.conn.execute(
                        "UPDATE view_sessions SET updated_ts=?, app_pkg=? WHERE id=?",
                        (now, app_pkg, self.open_id))
            self.last_seen = now
            self.conn.commit()
        elif self.open_id is not None and now - self.last_seen >= self.gap:
            self.conn.execute(
                "UPDATE view_sessions SET ended_ts=? WHERE id=?",
                (self.last_seen, self.open_id))
            self.conn.commit()
            self.open_id = None
            self.open_seconds = 0
            self.last_ended = self.last_seen
        self.last_tick = now

class FireTVController:
    """轮询 Fire TV 播放状态，到点暂停、拉起答题 App、答对后恢复视频。"""

    def __init__(self, conn, ip, port, dry_run=False, server_url=None):
        self.conn = conn
        self.ip = ip
        self.serial = adb_connect(ip) if ip else ""
        self.adb_failures = 0
        self.dry_run = dry_run
        self.server_url = server_url or ("http://%s:%d" % (local_ip(), port))

        settings = read_settings(conn)
        self.max_difficulty = max(1, int(settings["max_difficulty"]))
        self.timeout = max(10, int(settings["answer_timeout_seconds"]))

        self.lock = threading.RLock()
        self.running = True
        self.block = 0
        self.difficulty = 1
        self.current = None
        self.shown = set()
        self.session_used = set()
        self.session_id = "ft-0"
        self.video_pkg = ""
        self.accumulated = 0.0
        self.last_tick = time.time()
        self.active = False
        self.pending_resume = False
        self.quiz_started = 0.0
        self.last_launch = 0.0
        self.hard_timeout = 600
        self.thread = None
        self.view = ViewTracker(conn, device=ip or "firetv")
        self.correct_required = 1
        self.require_consecutive = True
        self.prefer_wrong = True
        self.correct_count = 0
        self.poll_seconds = 2
        self.suspend_until = 0.0
        self.suspend_activity = time.time()
        self.drill_active = False
        self.drill_until = 0.0
        self.drill_count = 0
        self.drill_question = None
        self.max_view_seconds = 0
        self.drill_seconds = 600
        self.cooldown_seconds = 0
        self.parent_reset_seconds = 600

    # ---- 答题 App 调用的接口 ----

    def current_payload(self):
        with self.lock:
            if self.drill_active:
                if self.drill_question is None:
                    self.drill_question = pick_question(
                        self.conn, max(1, self.max_difficulty),
                        used=self.session_used, prefer_wrong=self.prefer_wrong)
                if self.drill_question is not None:
                    return self._drill_payload(self.drill_question)
                return {"finished": True}
            if not self.active or self.current is None:
                return {"finished": True}
            return self._payload(self.current)

    def answer(self, data):
        with self.lock:
            if self.drill_active:
                return self._answer_drill(data)
            if not self.active or self.current is None:
                return {"correct": True, "finished": True, "answer": -1}

            question = self.current
            if str(data.get("question_id", "")) != question["id"]:
                return {"correct": False, "answer": question["answer"],
                        "message": "题目已过期", "next": self._payload(question)}

            try:
                choice = int(data.get("choice", -1))
            except (TypeError, ValueError):
                choice = -1
            timed_out = bool(data.get("timeout")) or choice < 0
            correct = (not timed_out) and choice == question["answer"]
            try:
                elapsed = int(data.get("elapsed_ms") or 0)
            except (TypeError, ValueError):
                elapsed = 0

            log_attempt(self.conn, self.session_id, question, correct, timed_out, elapsed)

            if correct:
                self.correct_count += 1
                if self.correct_count < self.correct_required:
                    nxt = pick_question(
                        self.conn, self.difficulty, exclude=self.shown,
                        used=self.session_used, prefer_wrong=self.prefer_wrong)
                    if nxt is not None:
                        self.shown.add(nxt["id"])
                        self.session_used.add(nxt["id"])
                        self.current = nxt
                        return {
                            "correct": True, "finished": False,
                            "answer": question["answer"],
                            "message": "答对了，还需答对 %d 题"
                                       % (self.correct_required - self.correct_count),
                            "next": self._payload(nxt),
                        }
                self.active = False
                self.current = None
                self.pending_resume = True
                return {"correct": True, "answer": question["answer"],
                        "finished": True, "message": "答对了，继续观看"}

            if self.require_consecutive:
                self.correct_count = 0
            nxt = pick_question(self.conn, self.difficulty, kp=question["kp"],
                                exclude=self.shown, used=self.session_used,
                                prefer_wrong=self.prefer_wrong)
            if nxt is None:
                self.active = False
                self.current = None
                self.pending_resume = True
                return {"correct": False, "answer": question["answer"],
                        "message": "同难度的题出完了，先继续观看", "finished": True}

            self.shown.add(nxt["id"])
            self.session_used.add(nxt["id"])
            self.current = nxt
            return {"correct": False, "answer": question["answer"],
                    "message": "✘ 答错了，换一道同难度的题",
                    "next": self._payload(nxt)}

    def _answer_drill(self, data):
        question = self.drill_question
        if question is None:
            return {"mode": "drill", "correct": False, "finished": True, "answer": -1}
        if str(data.get("question_id", "")) != question["id"]:
            return {"mode": "drill", "correct": False, "finished": False,
                    "answer": question["answer"], "message": "题目已刷新",
                    "next": self._drill_payload(question)}
        try:
            choice = int(data.get("choice", -1))
        except (TypeError, ValueError):
            choice = -1
        timed_out = bool(data.get("timeout")) or choice < 0
        correct = (not timed_out) and choice == question["answer"]
        try:
            elapsed = int(data.get("elapsed_ms") or 0)
        except (TypeError, ValueError):
            elapsed = 0
        log_attempt(self.conn, self.session_id, question, correct, timed_out, elapsed)
        self.drill_count += 1
        nxt = pick_question(
            self.conn, max(1, self.max_difficulty), exclude={question["id"]},
            used=self.session_used, prefer_wrong=self.prefer_wrong)
        if nxt is None:
            nxt = pick_question(
                self.conn, max(1, self.max_difficulty), exclude={question["id"]},
                used=set(), prefer_wrong=False)
        if nxt is None:
            nxt = pick_question(self.conn, max(1, self.max_difficulty))
        self.drill_question = nxt
        if nxt is None:
            return {"mode": "drill", "correct": correct, "finished": True,
                    "answer": question["answer"], "message": "题库暂时没有更多题了"}
        return {"mode": "drill", "correct": correct, "finished": False,
                "answer": question["answer"], "message": "刷题模式：再来一题",
                "next": self._drill_payload(nxt), "drill_count": self.drill_count}

    def parent_exit(self, pin):
        """家长 PIN 验证通过后退出答题，并暂停管控一段时间。"""
        settings = read_settings(self.conn)
        actual = settings.get("admin_pin", "")
        if not pin or not actual or not hmac.compare_digest(str(pin), str(actual)):
            return {"ok": False, "error": "密码错误"}
        try:
            minutes = int(settings.get("parent_suspend_minutes", "30"))
        except (TypeError, ValueError):
            minutes = 30
        minutes = max(1, min(720, minutes))
        until = time.time() + minutes * 60
        set_setting(self.conn, "suspend_until", str(until))
        with self.lock:
            self.active = False
            self.current = None
            self.pending_resume = True
            self.correct_count = 0
            self.accumulated = 0.0
            self.last_tick = time.time()
            self.drill_active = False
            self.drill_until = 0.0
            self.drill_question = None
            self.drill_count = 0
            self.suspend_activity = time.time()
        return {"ok": True, "minutes": minutes, "until": until}

    def _payload(self, question):
        return {
            "mode": "quiz",
            "block": self.block,
            "difficulty": self.difficulty,
            "max": self.max_difficulty,
            "timeout": self.timeout,
            "need": self.correct_required,
            "done": self.correct_count,
            "question": {
                "id": question["id"],
                "stem": question["stem"],
                "options": json.loads(question["options"]),
            },
        }

    # ---- 控制循环 ----

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def begin_quiz(self):
        self._start_quiz("")

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as exc:
                print("[tvgate] 控制循环异常：%s" % exc)
            time.sleep(max(1, min(10, self.poll_seconds)))

    def _settings(self):
        try:
            return read_settings(self.conn)
        except Exception:
            return dict(DEFAULT_SETTINGS)

    def _tick(self):
        now = time.time()
        settings = self._settings()

        with self.lock:
            interval = max(5, int(settings["interval_seconds"]))
            self.max_difficulty = max(1, int(settings["max_difficulty"]))
            self.timeout = max(10, int(settings["answer_timeout_seconds"]))
            self.poll_seconds = max(1, min(10, int(settings.get("poll_seconds", "2"))))
            self.correct_required = max(1, min(5, int(settings.get("correct_required", "1"))))
            self.require_consecutive = settings.get("require_consecutive", "1") == "1"
            self.prefer_wrong = settings.get("prefer_wrong", "1") == "1"
            self.view.gap = max(60, min(3600, int(settings.get("view_gap_seconds", "180"))))
            self.suspend_until = float(settings.get("suspend_until", "0") or 0)
            self.max_view_seconds = max(0, int(settings.get("max_view_minutes", "0"))) * 60
            self.drill_seconds = max(60, int(settings.get("drill_minutes", "10")) * 60)
            self.cooldown_seconds = max(0, int(settings.get("cooldown_minutes", "0"))) * 60
            self.parent_reset_seconds = max(
                60, int(settings.get("parent_reset_minutes", "10")) * 60)

        media_pkg, media_state = firetv_media_state(self.serial)
        if media_state == -1 and media_pkg is None:
            self.adb_failures += 1
            if self.adb_failures % 3 == 0 and self.ip:
                adb_connect(self.ip)  # Fire TV 休眠/重启后 ADB 会断，隔几次重连
        else:
            self.adb_failures = 0

        foreground = firetv_foreground(self.serial)
        watching = media_pkg if media_state == 3 else ""
        if not watching and foreground and foreground not in LAUNCHER_PACKAGES \
                and not foreground.startswith(QUIZ_PACKAGE):
            watching = foreground

        # 1) 家长模式：不弹题、不计观看；电视闲置超过 parent_reset_minutes 自动恢复管控
        if now < self.suspend_until:
            clear_suspend = False
            with self.lock:
                self.view.pause(now)
                self.accumulated = 0.0
                self.last_tick = now
                if watching:
                    self.suspend_activity = now
                elif now - self.suspend_activity >= self.parent_reset_seconds:
                    clear_suspend = True
                if self.active:
                    self.active = False
                    self.current = None
                    self.pending_resume = True
            if clear_suspend:
                set_setting(self.conn, "suspend_until", "0")
                self.suspend_until = 0.0
                self.view.last_ended = 0.0
            else:
                if self.pending_resume:
                    self._resume()
                return

        # 2) 刷题模式：视频不恢复，循环出题
        if self.drill_active:
            if now >= self.drill_until:
                self._end_drill(now)
                return
            with self.lock:
                self.view.pause(now)
                self.accumulated = 0.0
                self.last_tick = now
            if watching:
                adb_run(self.serial, "shell", "input", "keyevent", "85")
            if foreground and not foreground.startswith(QUIZ_PACKAGE) \
                    and now - self.last_launch > 5:
                self._launch()
            return

        # 3) 两次观看间隔：新会话开始且仍在冷却期，直接进入刷题
        starting = bool(watching) and self.view.open_id is None
        if starting and self.cooldown_seconds and self.view.last_ended \
                and now - self.view.last_ended < self.cooldown_seconds:
            self._start_drill(now, "cooldown",
                              self.view.last_ended + self.cooldown_seconds, watching)
            return

        # 4) 正常观看统计
        with self.lock:
            self.view.update(now, watching)

        # 5) 单次观看上限：到时强制刷题
        if self.max_view_seconds and self.view.open_seconds >= self.max_view_seconds:
            self._start_drill(now, "limit", now + self.drill_seconds, watching)
            return

        # 6) 答题总开关
        if settings["quiz_enabled"] != "1":
            with self.lock:
                self.accumulated = 0.0
                self.last_tick = now
                if self.active:
                    self.active = False
                    self.current = None
                    self.pending_resume = True
            if self.pending_resume:
                self._resume()
            return

        # 7) 常规检查点
        with self.lock:
            active = self.active
            pending = self.pending_resume
            due = False
            relaunch = False
            repause = False
            hard = False

            if active:
                relaunch = (foreground != "" and not foreground.startswith(QUIZ_PACKAGE)
                            and now - self.last_launch > 5)
                repause = bool(watching)
                hard = (now - self.quiz_started) > self.hard_timeout
            elif pending:
                pass
            else:
                if watching:
                    self.accumulated += max(0.0, now - self.last_tick)
                self.last_tick = now
                due = self.accumulated >= interval

        if active:
            if repause:
                adb_run(self.serial, "shell", "input", "keyevent", "85")
            if relaunch:
                self._launch()
            if hard:
                with self.lock:
                    question = self.current
                    if question is not None:
                        log_attempt(self.conn, self.session_id, question, False, True, 0)
                    self.active = False
                    self.current = None
                    self.pending_resume = True
            return

        if pending:
            self._resume()
            return

        if due:
            self._start_quiz(foreground)

    def _start_drill(self, now, reason, until, watching_pkg):
        with self.lock:
            self.drill_active = True
            self.drill_until = max(now + 60, until)
            self.drill_count = 0
            self.drill_question = pick_question(
                self.conn, max(1, self.max_difficulty),
                used=self.session_used, prefer_wrong=self.prefer_wrong)
            self.active = False
            self.current = None
            self.accumulated = 0.0
            self.last_tick = now
            if watching_pkg and watching_pkg not in LAUNCHER_PACKAGES \
                    and not watching_pkg.startswith(QUIZ_PACKAGE):
                self.video_pkg = watching_pkg
            self.view.pause(now)
        print("[tvgate] 进入刷题模式（%s），到 %s"
              % (reason, time.strftime("%H:%M", time.localtime(self.drill_until))))
        if self.dry_run:
            return
        if firetv_watching(self.serial):
            adb_run(self.serial, "shell", "input", "keyevent", "85")
        self._launch()

    def _end_drill(self, now):
        with self.lock:
            self.drill_active = False
            self.drill_until = 0.0
            self.drill_question = None
            self.drill_count = 0
            self.active = False
            self.current = None
            self.pending_resume = True
            self.accumulated = 0.0
            self.last_tick = now
            self.view.last_ended = 0.0  # 刷题结束后不要立刻再触发冷却
        if not self.dry_run:
            adb_run(self.serial, "shell", "am", "force-stop", QUIZ_PACKAGE)
            self._resume()
        print("[tvgate] 刷题结束，恢复视频")

    def _drill_payload(self, question):
        return {
            "mode": "drill",
            "drill_count": self.drill_count,
            "max": self.max_difficulty,
            "timeout": self.timeout,
            "need": 1,
            "done": 0,
            "question": {
                "id": question["id"],
                "stem": question["stem"],
                "options": json.loads(question["options"]),
            },
        }

    def _start_quiz(self, foreground):
        with self.lock:
            self.block += 1
            self.difficulty = min(self.block, self.max_difficulty)
            self.shown = set()
            self.correct_count = 0
            question = pick_question(self.conn, self.difficulty,
                                     used=self.session_used,
                                     prefer_wrong=self.prefer_wrong)
            if question is None:
                self.block -= 1
                self.accumulated = 0.0
                self.last_tick = time.time()
                print("[tvgate] 难度 %d 没有可用题目，跳过" % self.difficulty)
                return

            self.current = question
            self.shown.add(question["id"])
            self.session_used.add(question["id"])
            self.session_id = "ft-%d" % int(time.time())
            self.active = True
            self.quiz_started = time.time()
            self.accumulated = 0.0
            self.last_tick = time.time()
            if foreground and foreground not in LAUNCHER_PACKAGES \
                    and not foreground.startswith(QUIZ_PACKAGE):
                self.video_pkg = foreground

        print("[tvgate] 检查点 %d · 难度 %d · %s"
              % (self.block, self.difficulty, question["kp"]))

        if self.dry_run:
            return
        if firetv_watching(self.serial):
            adb_run(self.serial, "shell", "input", "keyevent", "85")
        self._launch()

    def _launch(self):
        if self.dry_run:
            return
        with self.lock:
            session = self.session_id
            server = self.server_url
        adb_run(self.serial, "shell", "am", "start", "-n",
                "%s/.QuizActivity" % QUIZ_PACKAGE,
                "--es", "server", server, "--es", "session", session, timeout=20)
        with self.lock:
            self.last_launch = time.time()

    def _resume(self):
        with self.lock:
            package = self.video_pkg
            self.pending_resume = False

        if not self.dry_run:
            # 等答题 App 真正退出，再判断要不要重新拉起视频 App
            current = ""
            for _ in range(8):
                current = firetv_foreground(self.serial)
                if current and not current.startswith(QUIZ_PACKAGE):
                    break
                time.sleep(0.5)

            if package and current != package:
                rc, out, err = adb_run(
                    self.serial, "shell", "monkey", "-p", package, "-c",
                    "android.intent.category.LEANBACK_LAUNCHER", "1", timeout=20)
                if rc != 0 or "No activities found" in (out + err):
                    adb_run(self.serial, "shell", "monkey", "-p", package, "1", timeout=20)
                time.sleep(2)

            # 只对注册了 MediaSession 的 App 发播放键；
            # 云视听这类靠音频焦点恢复的 App 不要发，否则会被重新暂停。
            _, state = firetv_media_state(self.serial)
            if state == 2:
                adb_run(self.serial, "shell", "input", "keyevent", "85")

        with self.lock:
            self.accumulated = 0.0
            self.last_tick = time.time()


# ---------------------------------------------------------------- 自检

def selftest():
    tmpdir = tempfile.mkdtemp(prefix="tvgate-test-")
    conn = connect(os.path.join(tmpdir, "test.db"))
    try:
        init_db(conn)
        ok = True

        print("== 题库检查 ==")
        for difficulty in range(1, 6):
            rows = conn.execute(
                "SELECT kp, COUNT(*) AS n FROM questions WHERE difficulty=? GROUP BY kp",
                (difficulty,)).fetchall()
            total = sum(r["n"] for r in rows)
            detail = "、".join("%s×%d" % (r["kp"], r["n"]) for r in rows)
            print("难度 %d：%d 题 / %d 个知识点（%s）"
                  % (difficulty, total, len(rows), detail))
            if total < 2:
                ok = False

        print("\n== 选题逻辑 ==")
        q1 = pick_question(conn, 1)
        print("难度 1 抽到：%s（%s）" % (q1["stem"], q1["kp"]))
        q2 = pick_question(conn, 1, kp=q1["kp"], exclude={q1["id"]}, used={q1["id"]})
        print("答错后换同知识点题：%s" % q2["stem"])
        print("与上一题不同：%s" % (q1["id"] != q2["id"]))
        if q1["id"] == q2["id"]:
            ok = False

        print("\n== 模拟一次观看（5 个检查点）==")
        random.seed(7)
        for block in range(1, 6):
            difficulty = min(block, 5)
            question = pick_question(conn, difficulty)
            correct = (block % 2 == 0)
            log_attempt(conn, "selftest", question, correct, False,
                        random.randint(2000, 20000))
            print("检查点 %d · 难度 %d · %-6s → %s"
                  % (block, difficulty, question["kp"], "答对" if correct else "答错"))

        print("\n== 知识点统计 ==")
        for r in compute_stats(conn):
            print("  %-4s %-6s 作答 %d 次，正确率 %3.0f%%，掌握度 %3.0f%%"
                  % (r["subject"], r["kp"], r["n"], r["accuracy"] * 100,
                     r["mastery"] * 100))

        total = conn.execute("SELECT COUNT(*) AS n FROM attempts").fetchone()["n"]
        print("\n累计写入作答记录：%d 条" % total)
        print("\n结果：%s" % ("PASS" if ok and total == 5 else "FAIL"))
        return 0 if ok and total == 5 else 1
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- 入口

def main():
    global DB_PATH, FIRE_CONTROLLER
    parser = argparse.ArgumentParser(description="tvgate 电视观看闸门")
    parser.add_argument("--interval", type=int, help="检查间隔（秒），会写入设置")
    parser.add_argument("--port", type=int, default=8765, help="家长端端口")
    parser.add_argument("--db", default=DB_PATH, help="数据库路径")
    parser.add_argument("--admin-only", action="store_true", help="只启动家长端，不开窗口")
    parser.add_argument("--selftest", action="store_true", help="不启动界面，跑一遍逻辑自检")
    parser.add_argument("--smoke", action="store_true", help="自动答题跑 3 个检查点后退出（测试窗口）")
    parser.add_argument("--firetv", metavar="IP", help="Fire TV Stick 的 IP，启用 ADB 控制模式")
    parser.add_argument("--server-url", help="答题 App 访问的地址，默认自动探测树莓派 IP")
    parser.add_argument("--quiz-test", action="store_true", help="本地启动答题 API（不连 Fire TV）")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    # HTTP 处理器在别的线程里用 connect()，这里把库路径统一成同一个
    DB_PATH = args.db

    if args.smoke:
        tmpdir = tempfile.mkdtemp(prefix="tvgate-smoke-")
        DB_PATH = os.path.join(tmpdir, "smoke.db")
        conn = connect(DB_PATH)
        init_db(conn)
        set_setting(conn, "interval_seconds", str(max(5, args.interval or 8)))
        app = App(conn, auto=True, max_blocks=3)
        try:
            app.root.mainloop()
        finally:
            conn.close()
            shutil.rmtree(tmpdir, ignore_errors=True)
        return 0

    conn = connect(DB_PATH)
    init_db(conn)
    if args.interval:
        set_setting(conn, "interval_seconds", str(args.interval))

    start_admin(args.port)
    base_url = args.server_url or ("http://%s:%d" % (local_ip(), args.port))
    print("家长端：%s/   （默认 PIN 1234）" % base_url)

    if args.quiz_test:
        FIRE_CONTROLLER = FireTVController(conn, "", args.port, dry_run=True)
        FIRE_CONTROLLER.begin_quiz()
        print("答题 API 测试模式已启动，可用 curl 模拟 Fire TV 答题。")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return 0

    if args.firetv:
        FIRE_CONTROLLER = FireTVController(conn, args.firetv, args.port,
                                           server_url=args.server_url)
        rc, out, err = adb_run(FIRE_CONTROLLER.serial, "shell",
                               "getprop", "ro.product.model", timeout=10)
        if rc != 0:
            print("[!] 连接 Fire TV 失败：%s" % (err or out))
            print("    检查：同一 Wi-Fi、IP 正确、开发者选项里 ADB 调试已开、电视上点了允许。")
        else:
            print("Fire TV 连接正常：%s" % out)
        FIRE_CONTROLLER.start()
        print("Fire TV 控制已启动：%s（答题 App 由 ADB 拉起）" % args.firetv)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            FIRE_CONTROLLER.stop()
        return 0

    if args.admin_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return 0

    app = App(conn)
    try:
        app.root.mainloop()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
