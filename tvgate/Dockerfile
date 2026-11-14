# tvgate 控制器 —— NAS 部署
# 构建：docker compose build
#
# Docker Hub 在部分网络下不可达，默认走 1ms 镜像源。
# 如果你的网络能直连 Docker Hub，可以覆盖：
#   docker compose build --build-arg BASE_IMAGE=python:3.11-slim
ARG BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    ADB_SERVER_PORT=5038

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && (apt-get install -y --no-install-recommends adb \
        || apt-get install -y --no-install-recommends android-tools-adb) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tvgate.py questions.json ./
RUN mkdir -p /app/data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3)"

ENTRYPOINT ["python3", "-u", "tvgate.py"]
CMD ["--firetv", "192.168.1.50", "--interval", "600", "--port", "8765", "--db", "/app/data/tvgate.db"]
