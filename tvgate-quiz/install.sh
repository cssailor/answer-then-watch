#!/bin/bash
# 构建并安装答题 App 到 Fire TV Stick
# 用法: ./install.sh <FireTV-IP>
set -e

IP="${1:?用法: ./install.sh <FireTV-IP>}"
cd "$(dirname "$0")"

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

echo "==> 构建 APK"
./gradlew assembleDebug

echo "==> 连接 Fire TV: $IP"
adb connect "$IP:5555"
adb devices

echo "==> 安装"
adb -s "$IP:5555" install -r app/build/outputs/apk/debug/app-debug.apk

echo "==> 完成。启动控制器："
echo "    python3 ../tvgate/tvgate.py --firetv $IP --interval 600"
