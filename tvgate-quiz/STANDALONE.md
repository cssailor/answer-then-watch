# 独立模式（standalone-apk 分支）

这个分支把后端管理逻辑整合进 APK，盒子（Fire TV / Android TV）自己运行后端，
**不需要单独的 NAS / 树莓派**。手机连同一 WiFi 扫码即可打开家长后台。

## 与 main 分支的区别

| | main（瘦 APK） | standalone-apk（本分支） |
|---|---|---|
| 后端 | NAS/树莓派上的 Python + Docker | 盒子上的 Android 前台服务（Java） |
| 管理后台 | 后端提供 | APK 内的极简 HTTP server |
| 打开 App | 隐藏入口 | 桌面可见，显示网址 + 二维码 |
| 出题/判题/错题/统计 | Python 实现 | Java 重写，逻辑一致 |
| 观看判断 | ADB 读 `dumpsys` | `AudioManager.isMusicActive()`（粗略） |

## 构建

```bash
cd tvgate-quiz
./gradlew assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

依赖 `com.google.zxing:core`（二维码），仓库已配阿里云镜像。

## 安装与使用

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

1. 安装后 App 显示在盒子桌面（不隐藏），点开即可看到：
   - 管理端网址，例如 `http://192.168.1.10:8765/`
   - 二维码
2. 手机连同一 WiFi，扫码或浏览器输入网址，进入家长后台（默认 PIN `1234`）
3. 后台功能与 main 分支一致：总览、知识点、错题本、题库、设置、学习报告

## 后端如何常驻

- `StandaloneService` 是**前台服务**（带常驻通知），Android 不会轻易杀掉
- 开机自启：`BootReceiver` 监听 `BOOT_COMPLETED` 自动拉起服务
- 服务用 `START_STICKY`，被系统回收后会重启

## 弹题与暂停

- 服务用 `AudioManager.isMusicActive()` 判断是否有视频/音频在播放，
  累计到「检查间隔」就拉起 `QuizActivity`（全屏答题界面）
- `QuizActivity` 启动时抢音频焦点，让播放器暂停；答对后释放焦点恢复播放
- 答题 App 通过 `http://127.0.0.1:8765/` 与本机后端通信

## 已知限制（需要真机验证）

独立模式是本分支的**实验性方案**，以下问题需要在真实设备上验证：

1. **观看判断是粗略的**：`isMusicActive()` 无法区分「视频播放」和「音乐/后台音频」，
   也没有区分「暂停」。桌面播放背景音乐时也会被当成在看。
   精确判断前台 App 需要 UsageStats 权限（一次 `adb shell appops` 授权），
   后续可加。
2. **暂停依赖音频焦点**：与 main 分支相同，少数 App 不响应。
3. **保活依赖前台服务**：正常不会被杀；但 Fire OS 的「强制停止」或低电耗模式
   仍可能影响。没有外部看门狗（后端跑在盒子里，后端被停 = 管控失效）。
4. **单设备**：后端跑在盒子自己身上，数据存在盒子本地 SQLite；
   换盒子/恢复出厂会丢数据。
5. **HTTP server 是极简实现**：只实现了管理所需的路由，并发能力有限；
   仅供局域网家庭使用，不要暴露公网。
6. **二维码依赖 ZXing**：已打包进 APK，不依赖网络。
7. **端口 8765 冲突**：盒子其他 App 占用 8765 时会启动失败，代码里暂未做换端口。
8. **Android 14+ 前台服务类型**：已声明 `specialUse`；Android 15+ 可能需要额外处理。

## 与 main 分支共享

- `QuizActivity`：答题界面（两个分支共用）
- 题库 `questions.json`：复制到 `assets/`
- 错题优先节奏、家长退出、统计口径等逻辑保持一致

## 路线建议

- 追求稳定、家里已有 NAS：用 **main 分支**（外部看门狗最可靠）
- 只想用一个盒子、愿意接受上述限制：用 **standalone-apk**
