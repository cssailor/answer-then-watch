package com.tvgate.quiz;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * 管理页面 HTML 与报告生成。样式与 Python 版保持一致。
 */
public class Pages {

    private static final String CSS =
            ":root{--bg:#0b0d12;--panel:#141821;--line:#1f2531;--text:#e6ebf2;--muted:#8b9ab0;--blue:#3d7df6;--green:#2e9e63;--red:#b84444;--amber:#c98a2e}" +
            "*{box-sizing:border-box}" +
            "body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,\"PingFang SC\",\"Microsoft YaHei\",Arial,sans-serif}" +
            "a{color:#7aa7ff;text-decoration:none}.wrap{max-width:960px;margin:0 auto;padding:26px 20px 70px}" +
            "h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 12px;color:#a9b8cc}" +
            ".sub{color:var(--muted);font-size:13px;margin-bottom:18px}" +
            ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}" +
            ".card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}" +
            ".card .k{color:var(--muted);font-size:12px}.card .v{font-size:24px;font-weight:700;margin-top:2px}" +
            "table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}" +
            "th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #1c2230;font-size:14px;vertical-align:top}" +
            "th{color:var(--muted);background:#11151d}tr:last-child td{border-bottom:none}" +
            ".bar{display:inline-block;width:90px;height:7px;background:#232a38;border-radius:4px;vertical-align:middle;margin-right:8px;overflow:hidden}" +
            ".bar i{display:block;height:100%;background:var(--blue)}" +
            "form{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;max-width:560px}" +
            "label{display:block;margin:10px 0 4px;color:#b9c5d6;font-size:13px}" +
            "input[type=number],input[type=text],input[type=password],select,textarea{width:100%;background:#0e1219;border:1px solid #2a3346;border-radius:9px;color:var(--text);padding:9px 11px;font-size:14px}" +
            "textarea{min-height:80px}.btn{display:inline-block;background:var(--blue);color:#fff;border:none;border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}" +
            ".btn.ghost{background:#1c2230;color:#cfd9e8}.btn.small{padding:5px 10px;font-size:13px}.btn.danger{background:#7a2b2b}" +
            ".toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0}" +
            ".help{color:#6f7d90;font-size:12px;margin-top:3px}.good{color:#61d095}.bad{color:#ff8a8a}" +
            ".pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#1c2230;color:#b9c5d6;font-size:12px;margin-right:4px}" +
            "pre.report{white-space:pre-wrap;background:#0e1219;border:1px solid var(--line);border-radius:14px;padding:18px;font:13px/1.7 ui-monospace,monospace;color:#cfd9e8;max-height:70vh;overflow:auto}";

    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;");
    }

    private static String layout(String title, String body) {
        return "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>" +
                "<meta name='viewport' content='width=device-width,initial-scale=1'>" +
                "<title>" + esc(title) + "</title><style>" + CSS + "</style></head>" +
                "<body><div class='wrap'>" + body + "</div></body></html>";
    }

    private static String pct(int n, int c) {
        return n == 0 ? "—" : String.format("%.0f%%", 100.0 * c / n);
    }

    private static String fmtTime(double ts) {
        return new SimpleDateFormat("MM-dd HH:mm").format(new Date((long) (ts * 1000)));
    }

    private static String fmtDuration(long secs) {
        long h = secs / 3600, m = (secs % 3600) / 60;
        if (h > 0) return h + " 小时 " + m + " 分";
        if (m > 0) return m + " 分钟";
        return secs + " 秒";
    }

    // ---------------------------------------------------------------- 登录

    static String login(boolean err) {
        String e = err ? "<p class='bad'>PIN 不对</p>" : "";
        String body = "<h1>答完再看 家长端</h1><div class='sub'>输入 PIN 进入</div>" + e +
                "<form method='post' action='/login'>" +
                "<label>PIN</label><input type='password' name='pin' autofocus>" +
                "<div style='margin-top:14px'><button class='btn' type='submit'>进入</button></div></form>" +
                "<p class='sub' style='margin-top:16px'>默认 PIN 1234，第一次进入后请在设置里改掉。</p>";
        return layout("登录", body);
    }

    // ---------------------------------------------------------------- 总览

    static String dashboard(Core core) {
        JSONObject st = core.stats();
        int total = st.optInt("total"), correct = st.optInt("correct");
        int wrongCount = st.optInt("wrong_count");
        Map<String, Object> view = core.viewSummary();
        long viewSecs = (long) view.get("total_seconds");
        int viewN = (int) view.get("sessions");

        String cards = "<div class='cards'>" +
                card("累计作答", String.valueOf(total)) +
                card("累计正确率", pct(total, correct)) +
                card("待复习错题", String.valueOf(wrongCount)) +
                card("累计观看", fmtDuration(viewSecs)) +
                card("观看次数", String.valueOf(viewN)) +
                "</div>";

        List<Map<String, Object>> know = core.knowledge();
        StringBuilder tips = new StringBuilder("<ul>");
        int cnt = 0;
        for (Map<String, Object> k : know) {
            if (cnt++ >= 3) break;
            int n = (int) k.get("n"), c = (int) k.get("correct");
            double mastery = (double) k.get("mastery");
            tips.append("<li><b>").append(esc((String) k.get("kp")))
                .append("</b>（").append(esc((String) k.get("subject")))
                .append("）—— 作答 ").append(n).append(" 次，正确率 ").append(pct(n, c))
                .append("，掌握度 ").append((int) (mastery * 100)).append("%</li>");
        }
        if (cnt == 0) tips.append("<li>还没有答题记录。</li>");
        tips.append("</ul>");

        StringBuilder recent = new StringBuilder(
                "<table><tr><th>时间</th><th>知识点</th><th>难度</th><th>结果</th></tr>");
        for (Map<String, Object> r : core.recent(10)) {
            int correctI = (int) r.get("correct");
            String mark = correctI == 1 ? "✔" : ((int) r.get("timed_out") == 1 ? "⏱" : "✘");
            recent.append("<tr><td>").append(fmtTime((double) r.get("ts")))
                .append("</td><td>").append(esc((String) r.get("kp")))
                .append("</td><td>").append(r.get("difficulty"))
                .append("</td><td>").append(mark).append("</td></tr>");
        }
        recent.append("</table>");

        String body = "<h1>总览</h1><div class='sub'>孩子的观看与答题情况</div>" + cards +
                "<div class='toolbar'><a class='btn' href='/report'>导出学习报告</a>" +
                "<a class='btn ghost' href='/knowledge'>知识点</a>" +
                "<a class='btn ghost' href='/wrong'>错题本</a>" +
                "<a class='btn ghost' href='/settings'>系统设置</a></div>" +
                "<h2>复习建议</h2>" + tips +
                "<h2>最近答题</h2>" + recent;
        return layout("总览", body);
    }

    private static String card(String k, String v) {
        return "<div class='card'><div class='k'>" + k + "</div><div class='v'>" + v + "</div></div>";
    }

    // ---------------------------------------------------------------- 知识点

    static String knowledge(Core core) {
        List<Map<String, Object>> list = core.knowledge();
        StringBuilder sb = new StringBuilder("<table><tr><th>科目</th><th>知识点</th><th>作答</th><th>正确率</th><th>掌握度</th></tr>");
        for (Map<String, Object> k : list) {
            int n = (int) k.get("n"), c = (int) k.get("correct");
            double mastery = (double) k.get("mastery");
            int p = (int) (mastery * 100);
            sb.append("<tr><td>").append(esc((String) k.get("subject")))
                .append("</td><td>").append(esc((String) k.get("kp")))
                .append("</td><td>").append(n)
                .append("</td><td>").append(pct(n, c))
                .append("</td><td><div class='bar'><i style='width:").append(p).append("%'></i></div>")
                .append(p).append("%</td></tr>");
        }
        sb.append("</table>");
        String body = "<h1>知识点掌握</h1><div class='sub'>按掌握度从低到高排序。</div>" + sb;
        return layout("知识点", body);
    }

    // ---------------------------------------------------------------- 错题本

    static String wrongBook(Core core) {
        List<Map<String, Object>> list = core.wrongBook();
        StringBuilder sb = new StringBuilder();
        for (Map<String, Object> w : list) {
            String options = (String) w.get("options");
            int answer = (int) w.get("answer");
            StringBuilder opts = new StringBuilder();
            try {
                org.json.JSONArray arr = new org.json.JSONArray(options);
                for (int i = 0; i < arr.length(); i++) {
                    char letter = (char) ('A' + i);
                    String mark = i == answer ? " ✅" : "";
                    opts.append("<div style='color:").append(i == answer ? "#7fe0a6" : "#c8d3e2")
                        .append("'>").append(letter).append(". ").append(esc(arr.getString(i)))
                        .append(mark).append("</div>");
                }
            } catch (Exception ignored) {
            }
            sb.append("<div class='card' style='margin-bottom:12px'>")
                .append("<span class='pill'>").append(esc((String) w.get("subject"))).append("</span>")
                .append("<span class='pill'>").append(esc((String) w.get("kp"))).append("</span>")
                .append("<span class='pill'>难度 ").append(w.get("difficulty")).append("</span>")
                .append("<span class='sub' style='font-size:12px'>错 ").append(w.get("wrong_count"))
                .append(" 次 · ").append(fmtTime((double) w.get("last_wrong_ts"))).append("</span>")
                .append("<form method='post' action='/wrong/resolve' style='display:inline;float:right'>")
                .append("<input type='hidden' name='id' value='").append(esc((String) w.get("id"))).append("'>")
                .append("<input type='hidden' name='action' value='resolve'>")
                .append("<button class='btn small' type='submit'>标记已掌握</button></form>")
                .append("<div style='font-size:17px;font-weight:600;margin:8px 0'>")
                .append(esc((String) w.get("stem"))).append("</div>").append(opts)
                .append("<div class='sub' style='margin:10px 0 0'>").append(esc((String) w.get("explain")))
                .append("</div></div>");
        }
        if (list.isEmpty()) sb.append("<p class='sub'>暂时没有未掌握的错题。</p>");
        String body = "<h1>错题本</h1><div class='sub'>答错过的题；确认掌握后点「标记已掌握」。</div>" + sb;
        return layout("错题本", body);
    }

    // ---------------------------------------------------------------- 题库

    static String questions(Core core) {
        List<Map<String, Object>> list = core.listQuestions();
        StringBuilder sb = new StringBuilder(
                "<table><tr><th>科目</th><th>知识点</th><th>难度</th><th>题干</th><th>答案</th><th>操作</th></tr>");
        int shown = 0;
        for (Map<String, Object> q : list) {
            if (shown++ >= 200) break;
            String options = (String) q.get("options");
            int answer = (int) q.get("answer");
            String answerText = "";
            try {
                org.json.JSONArray arr = new org.json.JSONArray(options);
                if (answer >= 0 && answer < arr.length()) answerText = arr.getString(answer);
            } catch (Exception ignored) {
            }
            String stem = (String) q.get("stem");
            if (stem.length() > 60) stem = stem.substring(0, 60) + "…";
            sb.append("<tr><td><span class='pill'>").append(esc((String) q.get("subject"))).append("</span></td>")
                .append("<td>").append(esc((String) q.get("kp"))).append("</td>")
                .append("<td>").append(q.get("difficulty")).append("</td>")
                .append("<td>").append(esc(stem)).append("</td>")
                .append("<td class='good'>").append(esc(answerText)).append("</td>")
                .append("<td><form method='post' action='/questions/delete' style='display:inline'")
                .append(" onsubmit=\"return confirm('确定删除这道题？')\">")
                .append("<input type='hidden' name='id' value='").append(esc((String) q.get("id"))).append("'>")
                .append("<button class='btn small danger' type='submit'>删除</button></form></td></tr>");
        }
        sb.append("</table>");

        String form = "<form method='post' action='/questions/save'>" +
                "<h2>新增题目</h2>" +
                "<label>科目</label><input type='text' name='subject' value='数学'>" +
                "<label>知识点</label><input type='text' name='kp' required>" +
                "<label>难度（1–5）</label><input type='number' name='difficulty' value='1' min='1' max='5'>" +
                "<label>题干</label><textarea name='stem' required></textarea>" +
                "<label>选项（每行一个）</label><textarea name='options' required></textarea>" +
                "<label>正确答案（第几个，从 1 开始）</label><input type='number' name='answer' value='1' min='1'>" +
                "<label>解析（可选）</label><textarea name='explain'></textarea>" +
                "<div style='margin-top:12px'><button class='btn' type='submit'>保存</button></div></form>";

        String importForm = "<form method='post' action='/questions/import' style='margin-top:14px'>" +
                "<h2>批量导入（JSON）</h2>" +
                "<textarea name='payload' style='min-height:120px;font-family:monospace'></textarea>" +
                "<div style='margin-top:12px'><button class='btn' type='submit'>导入</button></div></form>";

        String body = "<h1>题库</h1><div class='sub'>共 " + list.size() + " 题</div>" +
                "<div class='toolbar'><a class='btn ghost' href='/questions/export'>导出 JSON</a></div>" +
                sb + form + importForm;
        return layout("题库", body);
    }

    // ---------------------------------------------------------------- 设置

    static String settings(Core core) {
        String suspended = "1".equals(core.get("suspended", "0"))
                ? "<div class='card' style='margin-bottom:14px'><div class='k'>家长模式</div>" +
                  "<div class='v'>本次会话不检查</div><div class='help'>关机再开机后自动恢复管控。</div>" +
                  "<form method='post' action='/suspend/clear' style='margin-top:10px'>" +
                  "<button class='btn small' type='submit'>立即恢复管控</button></form></div>"
                : "";

        String f = "";
        f += field("检查间隔（秒）", "interval_seconds", "每看满多少秒弹一次题。", core.get("interval_seconds", "600"), 5, 0);
        f += field("最高难度档", "max_difficulty", "控制器最多用到第几档难度。", core.get("max_difficulty", "3"), 1, 10);
        f += field("每题限时（秒）", "answer_timeout_seconds", "超时按答错处理。", core.get("answer_timeout_seconds", "120"), 10, 0);
        f += field("每次暂停需答对题数", "correct_required", "一次暂停要答对几题。", core.get("correct_required", "1"), 1, 5);
        f += field("错题复习延迟（小时）", "wrong_review_delay_hours", "答错的题多久后再优先；24=第二天。", core.get("wrong_review_delay_hours", "24"), 1, 168);

        f += field("ADB 轮询间隔（秒）", "poll_seconds", "本机检测间隔（独立模式保留字段）。", core.get("poll_seconds", "2"), 1, 10);
        f += field("观看会话间隔（秒）", "view_gap_seconds", "统计用：离开多久算新一次观看。", core.get("view_gap_seconds", "180"), 60, 3600);
        f += field("单次观看上限（分钟）", "max_view_minutes", "连续观看达到后强制刷题；0=关闭。", core.get("max_view_minutes", "0"), 0, 240);
        f += field("强制刷题时长（分钟）", "drill_minutes", "触发上限后刷题多久。", core.get("drill_minutes", "10"), 1, 60);
        f += field("两次观看间隔（分钟）", "cooldown_minutes", "间隔内重开直接刷题；0=关闭。", core.get("cooldown_minutes", "0"), 0, 720);
        f += field("家长模式闲置重置（分钟）", "parent_reset_minutes", "家长退出后闲置多久自动恢复管控。", core.get("parent_reset_minutes", "10"), 1, 120);
        f += "<label>家长端 PIN（4–12 位字母数字，留空不改）</label>" +
             "<input type='text' name='admin_pin' maxlength='12' style='max-width:200px'>";

        String checks = check("require_consecutive", core.get("require_consecutive", "1"), "必须连续答对", "答错会清零进度") +
                check("prefer_wrong", core.get("prefer_wrong", "1"), "优先出错题本里的题", "隔天优先，答对移出") +
                check("quiz_enabled", core.get("quiz_enabled", "1"), "开启答题检查", "关闭后不弹常规检查点");

        String body = "<h1>系统设置</h1><div class='sub'>修改后保存生效。</div>" + suspended +
                "<form method='post' action='/settings'>" +
                "<h2>通用设置</h2><div class='sub'>题目与答题相关</div>" + f +
                checks +
                "<div style='margin-top:14px'><button class='btn' type='submit'>保存设置</button></div></form>";
        return layout("系统设置", body);
    }

    private static String field(String label, String name, String help, String value, int min, int max) {
        String limits = " min='" + min + "'" + (max > 0 ? " max='" + max + "'" : "");
        return "<label>" + label + "</label><input type='number' name='" + name +
                "' value='" + value + "'" + limits + "><div class='help'>" + help + "</div>";
    }

    private static String check(String name, String value, String label, String help) {
        String ck = "1".equals(value) ? " checked" : "";
        return "<div style='margin:12px 0'><label style='display:inline'><input type='checkbox' name='" +
                name + "' value='1'" + ck + "> " + label + "</label><div class='help'>" + help + "</div></div>";
    }

    // ---------------------------------------------------------------- 报告

    static String report(Core core) {
        String md = reportMarkdown(core);
        String body = "<h1>学习报告</h1><div class='sub'>下载后可直接发给大模型分析。</div>" +
                "<div class='toolbar'><a class='btn' href='/report.md'>下载 Markdown</a>" +
                "<a class='btn ghost' href='/report.json'>下载 JSON</a></div>" +
                "<pre class='report'>" + esc(md) + "</pre>";
        return layout("报告", body);
    }

    static String reportMarkdown(Core core) {
        StringBuilder sb = new StringBuilder();
        JSONObject st = core.stats();
        int total = st.optInt("total"), correct = st.optInt("correct");
        int wrongCount = st.optInt("wrong_count");
        Map<String, Object> view = core.viewSummary();

        sb.append("# 孩子电视学习报告\n\n");
        sb.append("- 生成时间：").append(new SimpleDateFormat("yyyy-MM-dd HH:mm").format(new Date())).append("\n");
        sb.append("- 总作答：").append(total).append(" 次\n");
        sb.append("- 总体正确率：").append(total == 0 ? "—" : String.format("%.0f%%", 100.0 * correct / total)).append("\n");
        sb.append("- 待复习错题：").append(wrongCount).append(" 道\n");
        sb.append("- 累计观看：").append(fmtDuration((long) view.get("total_seconds"))).append("\n\n");
        sb.append("## 给大模型的提示词\n\n");
        sb.append("你是一位经验丰富的小学四年级老师。请根据下面的学习报告，分析孩子的薄弱环节，")
          .append("指出需要优先复习的 3–5 个知识点，并给出未来两周可执行的复习计划（每天 15–20 分钟）。")
          .append("要求：先肯定进步，再指出问题；建议要具体到知识点和练习方式。\n\n");
        sb.append("## 知识点掌握\n\n");
        sb.append("| 科目 | 知识点 | 作答 | 正确率 | 掌握度 |\n|---|---|---:|---:|---:|\n");
        for (Map<String, Object> k : core.knowledge()) {
            int n = (int) k.get("n"), c = (int) k.get("correct");
            double mastery = (double) k.get("mastery");
            sb.append("| ").append(k.get("subject")).append(" | ").append(k.get("kp"))
              .append(" | ").append(n).append(" | ").append(pct(n, c))
              .append(" | ").append((int) (mastery * 100)).append("% |\n");
        }
        sb.append("\n## 错题本（未掌握）\n\n");
        List<Map<String, Object>> wrong = core.wrongBook();
        if (wrong.isEmpty()) {
            sb.append("暂无未掌握的错题。\n");
        } else {
            for (int i = 0; i < wrong.size(); i++) {
                Map<String, Object> w = wrong.get(i);
                sb.append(i + 1).append(". [").append(w.get("subject")).append("] ")
                  .append(w.get("kp")).append(" · 难度 ").append(w.get("difficulty"))
                  .append(" · 错 ").append(w.get("wrong_count")).append(" 次\n");
                sb.append("   **题干**：").append(String.valueOf(w.get("stem")).replace("\n", " ")).append("\n");
            }
        }
        return sb.toString();
    }

    static String reportJson(Core core) {
        JSONObject o = new JSONObject();
        try {
            o.put("stats", core.stats());
            org.json.JSONArray know = new org.json.JSONArray();
            for (Map<String, Object> k : core.knowledge()) know.put(new JSONObject(k));
            o.put("knowledge", know);
        } catch (Exception ignored) {
        }
        return o.toString();
    }

    static String exportQuestions(Core core) {
        return core.exportQuestions();
    }
}
