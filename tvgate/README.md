# 答完再看 —— 电视观看管控与学习问答

孩子每看满 N 分钟，视频暂停并弹出全屏题；答对继续，答错换一道同难度的题；
每过一个 N 分钟，难度档 +1。家长端网页看知识点掌握情况、复习建议，
也能随时关掉答题功能。

## 当前采用的架构

三星电视（Tizen）系统封闭，第三方程序无法在电视自带 App 上覆盖画面。
所以采用「收口到 Fire TV Stick」的方案：

```
Fire TV Stick 4K ──ADB(局域网)── 树莓派 / 常开电脑
        │                              │
        └──── HDMI ──── 三星电视        └── 家长端网页 + SQLite + 题库
```

1. **三星电视断网**（设置里删除 Wi-Fi，路由器按 MAC 拉黑），收起三星遥控器，
   电视只当显示器用。Fire Stick 自己联网，不受影响。
2. **树莓派**通过 ADB 轮询 Fire Stick 的播放状态，到点暂停、拉起答题 App、
   答对后恢复视频。
3. **答题 App** 是 Fire Stick 上的一个全屏 Android TV 应用，用 Fire 遥控器的
   方向键和 OK 键答题，不依赖手机或平板。

## 文件

| 路径 | 说明 |
|---|---|
| `tvgate/tvgate.py` | 控制器 + 家长端 + 题库逻辑（Mac 原型和树莓派共用） |
| `tvgate/questions.json` | 四年级下册题库（601 题：数学 197、语文 201、英语 203） |
| `tvgate/build_bank.py` | 题库生成器（调用下面三个模块，重新生成 questions.json） |
| `tvgate/bank_math.py` 等 | 分科题库数据与模板 |
| `tvgate/firetv_probe.py` | Fire Stick ADB 连通性和暂停键探测 |
| `tvgate-quiz/` | Android TV 答题 App 工程（约 250 行 Java，无第三方库） |
| `tvgate/tvgate.db` | 自动生成的 SQLite 数据库 |

## 第一步：验证 Fire Stick 能被控制

Fire TV：设置 → My Fire TV → 关于 → 连点设备名 7 次 → 开发者选项 →
**ADB 调试打开**。第一次连接时电视会弹授权框，用 Fire 遥控器点「允许」。

```bash
python3 tvgate/firetv_probe.py --ip <FireStick的IP>
python3 tvgate/firetv_probe.py --ip <FireStick的IP> --pause-test --resume
```

`--pause-test` 会读取 `dumpsys media_session` 的播放状态，发一次
`keyevent 85`，确认 `state=3`（播放）是否变成 `state=2`（暂停）。
**这一步不通过，后面的方案都不成立**，先解决它。

## 第二步：构建并安装答题 App

```bash
# 一次性环境
brew install openjdk@17 gradle
brew install --cask android-commandlinetools
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools

# 一键构建 + 安装
cd tvgate-quiz
./install.sh <FireStick的IP>
```

手动构建时用 `./gradlew assembleDebug`，产物在
`tvgate-quiz/app/build/outputs/apk/debug/app-debug.apk`。
依赖仓库已配置阿里云镜像，`repo.maven.apache.org` 的 TLS 握手在部分网络下会失败。

如果在树莓派上构建，装 `openjdk-17-jdk` 和 `gradle` 即可，步骤相同。

## 第三步：启动控制器

本机临时运行：

```bash
python3 tvgate/tvgate.py --firetv <FireStick的IP> --interval 600
```

长期运行推荐部署到 NAS，见 [NAS-DEPLOY.md](NAS-DEPLOY.md)：

```bash
cd tvgate
cp .env.example .env   # 改 FIRE_TV_IP
sudo docker compose up -d --build
```

- 家长端：`http://<控制器IP>:8765/`，默认 PIN `1234`。
- `--interval 600` 是 10 分钟；调试时可以改成 20 秒。
- 控制器每 2 秒判断一次：优先看 MediaSession；云视听等不注册会话的 App
  退化为「前台 App + 音频焦点」判断。

## 孩子看到的流程

1. 看视频到第 10 分钟，控制器发 `keyevent 85`；对云视听这类不响应媒体键的 App，
   答题 App 启动时抢音频焦点，播放器自己暂停。
2. 控制器用 ADB 拉起 `com.tvgate.quiz`，电视切到全屏答题界面
   （原视频 App 退到后台，停在原位置）。答题 App 已隐藏桌面入口，
   孩子不会在 Fire TV 桌面上看到它。
3. 遥控器上下选答案，OK 提交。
4. 答对 → 如果设置了「每次需答对多题」，原地继续出下一题；全部答对后恢复播放。
5. 答错 → 优先换错题本里同难度的题；按设置决定是否清零连续答对进度。
6. 返回键被 App 屏蔽；按 Home 键，控制器 2 秒内发现并重新拉起答题界面。

## 家长退出

答题界面右下角有一个「家长退出」按钮：

1. 遥控器按向下键走到该按钮，OK。
2. 输入家长端 PIN（设置页里那个，也用于后台登录），确认。
3. App 退出、视频恢复，控制器进入「家长模式」：在设定的
   `parent_suspend_minutes`（默认 30 分钟）内不再弹题，也不计入孩子的观看统计。
4. 到期自动恢复；家长也可以在后台「设置」页点「立即恢复管控」提前结束。

暂停状态存在数据库的 `suspend_until` 里，控制器重启也不会丢。

## 答题 API（排查用）

控制器提供三个给 App 用的接口：

```bash
# 当前题目
curl 'http://<树莓派IP>:8765/api/quiz/current?session=test'

# 提交答案（choice=-1 表示超时）
curl -X POST -H 'Content-Type: application/json' \
  -d '{"question_id":"e-d1-1","choice":1,"timeout":false,"elapsed_ms":3000}' \
  'http://<树莓派IP>:8765/api/quiz/answer'

# 家长退出（需要 PIN）
curl -X POST -H 'Content-Type: application/json' \
  -d '{"pin":"你的PIN"}' \
  'http://<树莓派IP>:8765/api/quiz/exit'
```

本地不连 Fire TV 也能测：

```bash
python3 tvgate/tvgate.py --quiz-test --port 8765
```

## 已知边界

- **Home 键拦不住**：普通 App 无法拦截 Home，控制器用「发现前台不是答题 App
  就重新拉起」兜底。孩子铁了心反复按也能拖时间，但看不成视频。
- **少数 App 不响应媒体键**：答题 App 会抢音频焦点，云视听已验证可暂停；
  其他 App 用 `firetv_probe.py` 逐个测。
- **切回视频依赖 App 保留播放位置**：Netflix、YouTube 一般没问题；
  Prime Video 有可能回到首页，到时按实际 App 调整。
- **ADB 是局域网后门**：只在家里用，不要把 5555 端口映射到公网。
- **Fire OS 大版本更新后**可能要重新授权 ADB。
- **控制器最好放孩子够不到的地方**（电视背后或另一台常开机器），
  否则拔掉控制器就绕过了。

## 观看统计

控制器每 2 秒判断一次 Fire TV 前台是不是视频 App，把连续观看聚合成会话：

- **时长**：只累计前台是视频 App 的时间；桌面、设置、答题界面不计入。
- **次数**：连续观看中离开不超过 3 分钟算同一次；超过就结束并记一次。
- **重启恢复**：控制器重启时按最后一次心跳关闭上次未结束的会话，避免重复计时。
- **日期归属**：跨午夜的会话记在开始那天。

家长端「观看」页：今日时长/次数、近 7 天日均、累计、最近 14 天明细、常用 App。
首页卡片也会显示今日观看和今日次数；学习报告的 Markdown/JSON 里同样包含观看统计。

已知边界：云视听等不注册 MediaSession 的 App 无法区分暂停，暂停时间可能被计入；
时长是「前台是视频 App 的时间」，不是精确的播放时间。

## 学习报告

家长端「报告」页可以按最近 7/30/90 天或全部生成学习报告，支持：

- **下载 Markdown**：文件开头自带一段给大模型的提示词，直接发给 Claude / ChatGPT
  就能得到薄弱点分析和两周复习计划。
- **下载 JSON**：结构化数据，方便自己写脚本或接其他分析工具。
- **网页预览**：不想下载时直接复制页面内容。

报告内容包括：总体正确率、分科知识点掌握表、薄弱知识点排序、未掌握错题
（题干/选项/正确答案/解析）、最近答题记录、建议复习方向。

## 题库怎么扩

题库现在是 601 道四年级下册仿真题（数学 197、语文 201、英语 203），
按知识点和难度打标，覆盖人教版/部编版四年级下册主要单元。

重新生成：

```bash
cd tvgate
python3 build_bank.py
```

`bank_math.py` / `bank_chinese.py` / `bank_english.py` 里是分科题目模板和
数据，改完后重新生成 `questions.json`，再到网页「题库」页点
「从 questions.json 重新载入」。

网页也可以直接新增、编辑、删除单题，或粘贴 JSON 批量导入。
`answer` 是正确选项的下标（从 0 开始）。
注意：难度目前集中在 1–3，控制器默认最高难度设为 3；如需 4–5 档，需要补题。
