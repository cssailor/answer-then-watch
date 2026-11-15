package com.tvgate.quiz;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 极简 HTTP server：跑在 StandaloneService 里，端口 8765。
 * 提供管理页面（浏览器访问）和答题 API（QuizActivity 调用）。
 */
public class WebServer {

    public static final int PORT = 8765;
    private final Core core;
    private volatile boolean running = false;
    private ServerSocket server;

    public WebServer(Core core) {
        this.core = core;
    }

    public void start() {
        new Thread(() -> {
            try {
                server = new ServerSocket(PORT);
                running = true;
                while (running) {
                    final Socket s = server.accept();
                    new Thread(() -> handle(s)).start();
                }
            } catch (IOException ignored) {
            }
        }).start();
    }

    public void stop() {
        running = false;
        try {
            if (server != null) server.close();
        } catch (IOException ignored) {
        }
    }

    // ---------------------------------------------------------------- 请求处理

    private void handle(Socket socket) {
        try {
            socket.setSoTimeout(10000);
            BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), "UTF-8"));
            String line = in.readLine();
            if (line == null) { socket.close(); return; }
            String[] parts = line.split(" ");
            String method = parts[0];
            String path = parts.length > 1 ? parts[1] : "/";

            Map<String, String> headers = new HashMap<>();
            String h;
            while ((h = in.readLine()) != null && !h.isEmpty()) {
                int idx = h.indexOf(':');
                if (idx > 0) headers.put(h.substring(0, idx).trim().toLowerCase(), h.substring(idx + 1).trim());
            }
            int contentLength = 0;
            try { contentLength = Integer.parseInt(headers.getOrDefault("content-length", "0")); }
            catch (NumberFormatException ignored) {}
            char[] bodyChars = new char[contentLength];
            if (contentLength > 0) {
                int read = 0;
                while (read < contentLength) {
                    int r = in.read(bodyChars, read, contentLength - read);
                    if (r < 0) break;
                    read += r;
                }
            }
            String body = new String(bodyChars);
            String cookie = headers.getOrDefault("cookie", "");

            Response resp = route(method, path, body, cookie);
            send(socket, resp);
            socket.close();
        } catch (IOException ignored) {
            try { socket.close(); } catch (IOException ignored2) {}
        }
    }

    private void send(Socket socket, Response r) throws IOException {
        byte[] data = r.body.getBytes("UTF-8");
        OutputStream out = socket.getOutputStream();
        StringBuilder head = new StringBuilder();
        head.append("HTTP/1.1 ").append(r.status).append(" ").append(statusText(r.status)).append("\r\n");
        head.append("Content-Type: ").append(r.contentType).append("\r\n");
        head.append("Content-Length: ").append(data.length).append("\r\n");
        head.append("Access-Control-Allow-Origin: *\r\n");
        for (String hd : r.headers) head.append(hd).append("\r\n");
        head.append("Connection: close\r\n\r\n");
        out.write(head.toString().getBytes("UTF-8"));
        out.write(data);
        out.flush();
    }

    private String statusText(int code) {
        switch (code) {
            case 200: return "OK";
            case 302: return "Found";
            case 400: return "Bad Request";
            case 403: return "Forbidden";
            case 404: return "Not Found";
            default: return "OK";
        }
    }

    private static class Response {
        int status = 200;
        String contentType = "text/html; charset=utf-8";
        String body = "";
        final java.util.List<String> headers = new java.util.ArrayList<>();
    }

    private Response html(String body, int status) {
        Response r = new Response();
        r.body = body;
        r.status = status;
        r.contentType = "text/html; charset=utf-8";
        return r;
    }

    private Response json(String body) {
        Response r = new Response();
        r.body = body;
        r.contentType = "application/json; charset=utf-8";
        return r;
    }

    private Response redirect(String location) {
        Response r = new Response();
        r.status = 302;
        r.headers.add("Location: " + location);
        r.body = "";
        return r;
    }

    // ---------------------------------------------------------------- 路由

    private boolean authed(String cookie) {
        String pin = core.getPin();
        if (pin == null || pin.isEmpty()) return true;
        for (String pair : cookie.split(";")) {
            String[] kv = pair.trim().split("=", 2);
            if (kv.length == 2 && "tvgate_pin".equals(kv[0]) && pin.equals(kv[1])) return true;
        }
        return false;
    }

    private Response route(String method, String path, String body, String cookie) {
        // 答题 API（QuizActivity 调用，不需要 PIN）
        if (path.equals("/api/quiz/current")) {
            return json(core.currentPayload().toString());
        }
        if (path.equals("/api/quiz/answer") && method.equals("POST")) {
            try {
                return json(core.answer(new JSONObject(body)).toString());
            } catch (Exception e) {
                return json("{\"correct\":false,\"finished\":true}");
            }
        }
        if (path.equals("/api/quiz/exit") && method.equals("POST")) {
            try {
                return json(core.parentExit(new JSONObject(body).optString("pin", "")).toString());
            } catch (Exception e) {
                return json("{\"ok\":false,\"error\":\"bad json\"}");
            }
        }

        if (path.equals("/logout")) {
            return redirect("/");
        }

        // 登录
        if (path.equals("/login") && method.equals("POST")) {
            Map<String, String> form = parseForm(body);
            String pin = form.getOrDefault("pin", "");
            if (core.checkPin(pin)) {
                Response r = redirect("/");
                r.headers.add("Set-Cookie: tvgate_pin=" + pin + "; Path=/; HttpOnly; SameSite=Lax");
                return r;
            }
            return html(Pages.login(true), 200);
        }

        if (!authed(cookie)) {
            return html(Pages.login(false), 200);
        }

        // 管理页面（需要 PIN）
        if (method.equals("GET")) {
            switch (path) {
                case "/": return html(Pages.dashboard(core), 200);
                case "/knowledge": return html(Pages.knowledge(core), 200);
                case "/wrong": return html(Pages.wrongBook(core), 200);
                case "/questions": return html(Pages.questions(core), 200);
                case "/settings": return html(Pages.settings(core), 200);
                case "/report": return html(Pages.report(core), 200);
                case "/report.md": {
                    Response r = new Response();
                    r.body = Pages.reportMarkdown(core);
                    r.contentType = "text/markdown; charset=utf-8";
                    return r;
                }
                case "/report.json": {
                    Response r = new Response();
                    r.body = Pages.reportJson(core);
                    r.contentType = "application/json; charset=utf-8";
                    return r;
                }
                case "/questions/export": {
                    Response r = new Response();
                    r.body = Pages.exportQuestions(core);
                    r.contentType = "application/json; charset=utf-8";
                    return r;
                }
            }
            return html("not found", 404);
        }

        if (method.equals("POST")) {
            Map<String, String> form = parseForm(body);
            switch (path) {
                case "/settings": {
                    core.applySettings(form);
                    return redirect("/settings");
                }
                case "/suspend/clear": {
                    core.setSetting("suspended", "0");
                    return redirect("/settings");
                }
                case "/wrong/resolve": {
                    core.resolveWrong(form.getOrDefault("id", ""),
                            "reopen".equals(form.getOrDefault("action", "")));
                    return redirect("/wrong");
                }
                case "/questions/save": {
                    core.saveQuestion(form);
                    return redirect("/questions");
                }
                case "/questions/delete": {
                    core.deleteQuestion(form.getOrDefault("id", ""));
                    return redirect("/questions");
                }
                case "/questions/import": {
                    core.importQuestions(form.getOrDefault("payload", ""));
                    return redirect("/questions");
                }
            }
            return html("not found", 404);
        }

        return html("not found", 404);
    }

    private Map<String, String> parseForm(String body) {
        Map<String, String> out = new HashMap<>();
        if (body == null) return out;
        for (String pair : body.split("&")) {
            int idx = pair.indexOf('=');
            if (idx < 0) continue;
            try {
                String k = URLDecoder.decode(pair.substring(0, idx), "UTF-8");
                String v = URLDecoder.decode(pair.substring(idx + 1), "UTF-8");
                out.put(k, v);
            } catch (Exception ignored) {
            }
        }
        return out;
    }
}
