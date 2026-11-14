# 部署到 NAS

控制器（计时、题库、判题、统计、家长端）跑在 NAS 的 Docker 里，
Fire TV 上只留答题 App。两者通过局域网通信。

## 前置条件

- NAS 支持 Docker（群晖 Container Manager、威联通 Container Station、TrueNAS、unRAID 均可）
- NAS 和 Fire TV 在同一局域网，NAS 能访问 `FIRE_TV_IP:5555`
- NAS 7×24 常开，硬盘休眠策略不会把容器停掉
- Fire TV 已开启 ADB 调试（设置 → My Fire TV → 关于 → 连点设备名 7 次 → 开发者选项）

## iStoreOS 快速部署

iStoreOS 在 `192.168.1.10`，SSH 只接受密码认证，所以从 Mac 上运行脚本，
按提示输入 root 密码即可：

```bash
cd /opt/answer-then-watch
./tvgate/deploy-istoreos.sh
```

默认装到 `/overlay/tvgate`。**不要用 `/mnt`**：iStoreOS 的 `/mnt` 是 4MB 的
tmpfs，写不下题库且重启会丢数据；`/overlay` 才是持久化分区。如果 NAS 还有
单独的数据盘，也可以指过去：

```bash
REMOTE_DIR=/volume1/tvgate ./tvgate/deploy-istoreos.sh
```

脚本会自动检测 `docker compose` / `docker-compose` / 只有 `docker` 三种情况。
第一次启动时电视会弹 ADB 授权框，点「允许」。

手动部署等价命令：

```bash
# Mac 上传输（注意用 /. 把隐藏文件一起带上）
scp -r /opt/answer-then-watch/tvgate/. root@192.168.1.10:/overlay/tvgate/

# 登录 iStoreOS
ssh root@192.168.1.10
cd /overlay/tvgate
cp .env.example .env
vi .env                     # 确认 FIRE_TV_IP=192.168.1.50
docker compose up -d --build
docker compose logs -f
```

如果 iStoreOS 没有 compose：

```bash
docker build -t tvgate .
docker rm -f tvgate 2>/dev/null
docker run -d --name tvgate --restart unless-stopped \
  -p 8765:8765 \
  -v /overlay/tvgate/data:/app/data \
  -v /overlay/tvgate/adb:/root/.android \
  -v /overlay/tvgate/questions.json:/app/questions.json:ro \
  -e TZ=Asia/Shanghai \
  tvgate --firetv 192.168.1.50 \
    --server-url http://192.168.1.10:8765 \
    --interval 600 --port 8765 --db /app/data/tvgate.db
docker logs -f tvgate
```

> iStoreOS 自带的 ADB server 会占用 5037，所以这里用 bridge 网络隔离，
> 不要用 `--network host`。

## 1. 上传文件

把这几个文件放到 NAS 上的同一个目录，例如 `/volume1/docker/tvgate/`：

```
Dockerfile
docker-compose.yml
tvgate.py
questions.json
.env.example
```

群晖可以用 File Station 上传；其他 NAS 用 SMB/SSH 均可。

## 2. 配置

```bash
cd /volume1/docker/tvgate
cp .env.example .env
```

编辑 `.env`：

```
FIRE_TV_IP=192.168.1.50
INTERVAL=600
```

`INTERVAL` 是检查间隔（秒），`600` = 10 分钟。调试时可以改成 `20`。

## 3. 启动

```bash
sudo docker compose up -d --build
```

群晖 Container Manager 也可以用「项目 → 新增 → 选择 docker-compose.yml」的方式启动。

查看日志：

```bash
sudo docker compose logs -f
```

第一次连接时，**电视上会弹 ADB 授权框**，用 Fire 遥控器点「允许」。
日志里看到下面两行就成功了：

```
Fire TV 连接正常：AFTMM
Fire TV 控制已启动：192.168.1.50（答题 App 由 ADB 拉起）
```

## 4. 家长端

浏览器打开：

```
http://<NAS的IP>:8765/
```

默认 PIN `1234`，第一次进去请在设置里改掉。
同一局域网的手机、电脑都能访问。

## 5. Fire TV 上的 App

APK 已经隐藏了桌面入口，只能由控制器拉起。安装：

```bash
cd tvgate-quiz
./install.sh 192.168.1.50
```

需要手动打开时（比如调试）：

```bash
adb -s 192.168.1.50:5555 shell am start -n com.tvgate.quiz/.QuizActivity \
  --es server http://<NAS的IP>:8765 --es session manual
```

## 6. 更新题库

三种方式：

1. **网页题库页**：直接新增、编辑、删除，立即生效。
2. **改 JSON 文件**：编辑 NAS 上的 `questions.json`，然后在题库页点
   「从 questions.json 重新载入」。
3. **重新生成**：在 `tvgate/` 目录运行 `python3 build_bank.py`，
   再上传 `questions.json` 并点重新载入。

注意：容器启动时只在数据库为空时导入 `questions.json`；
重启不会覆盖网页里的增删改。网页删除的题不会写回 JSON。

## 6.1 学习报告

家长端「报告」页支持按 7/30/90 天或全部导出 Markdown / JSON。
Markdown 文件开头带一段给大模型的提示词，下载后直接发给 Claude/ChatGPT 即可
得到薄弱点分析和复习计划。

## 7. 数据与备份

| 内容 | 位置 |
|---|---|
| 作答记录 / 设置 | `tvgate/data/tvgate.db`（SQLite） |
| ADB 授权密钥 | `tvgate/adb/` |
| 题库 | `questions.json` |

用 NAS 自带的快照/备份套件把整个 `tvgate/` 目录备份即可。
`adb/` 里是 ADB 私钥，不要外传。

## 8. 开机自启

`docker-compose.yml` 里已经设置 `restart: unless-stopped`，
NAS 重启后容器会自动拉起，不需要额外配置。

## 常见问题

### `adb: device unauthorized`

电视上的授权框没点「允许」，或者密钥丢了。重新执行：

```bash
sudo docker compose exec tvgate adb kill-server
sudo docker compose restart
```

然后再点一次电视上的「允许」。

### `device not found`

Fire TV 的 IP 变了。在路由器里给它做 DHCP 固定，或者改 `.env` 里的
`FIRE_TV_IP` 后 `docker compose up -d`。

### 端口 8765 被占用

改 `.env` 里的端口不可用（compose 里是写死的 8765），直接改
`docker-compose.yml` 的 `--port`，同时改 Fire TV 控制器的 `--server-url`。

### NAS 不支持 host 网络

把 `network_mode: host` 换成端口映射，并显式告诉控制器 NAS 的地址：

```yaml
    ports:
      - "8765:8765"
    # 删掉 network_mode: host
    command:
      - "--firetv"
      - "${FIRE_TV_IP:-192.168.1.50}"
      - "--server-url"
      - "http://<NAS的IP>:8765"
      - "--interval"
      - "${INTERVAL:-600}"
      - "--port"
      - "8765"
      - "--db"
      - "/app/data/tvgate.db"
```

### 容器一直重启

看日志：

```bash
sudo docker compose logs --tail=50
```

常见原因是 `tvgate.py` 语法错误、数据库目录没权限、或 `FIRE_TV_IP` 写错。
adb 连不上不会让容器退出，只会在日志里反复提示。

## 安全边界

- 只在局域网内使用，不要把 `8765` 或 `5555` 端口映射到公网
- 家长端用 PIN 保护，默认 `1234` 请改掉
- ADB 是设备级后门，NAS 被入侵等于 Fire TV 被控制
