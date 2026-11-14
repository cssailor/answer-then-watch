#!/usr/bin/env python3
"""firetv_probe.py — 动手改造前，验证 Fire TV Stick 能否被局域网 ADB 控制。

用法：
    python3 firetv_probe.py --ip 192.168.1.50
    python3 firetv_probe.py --ip 192.168.1.50 --pause-test
    python3 firetv_probe.py --ip 192.168.1.50 --pause-test --resume

前提：
    1. Fire TV：设置 → My Fire TV → 关于 → 连点设备名 7 次
       → 开发者选项 → ADB 调试：开
    2. 第一次连接时电视上会弹授权框，用 Fire 遥控器点“允许”
    3. 电脑上装了 adb（macOS: brew install android-platform-tools）
"""

import argparse
import re
import shutil
import subprocess
import sys
import time

STATE_NAMES = {
    0: "NONE", 1: "STOPPED", 2: "PAUSED", 3: "PLAYING", 4: "FAST_FORWARDING",
    5: "REWINDING", 6: "BUFFERING", 7: "ERROR", 8: "CONNECTING", 9: "SKIPPING",
}


def run(cmd, timeout=20):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "命令不存在"
    except subprocess.TimeoutExpired:
        return 124, "", "超时"


def adb(serial, *args, timeout=20):
    return run(["adb", "-s", serial] + list(args), timeout=timeout)


def check_adb():
    if not shutil.which("adb"):
        print("找不到 adb。macOS 安装：brew install android-platform-tools")
        print("树莓派安装：sudo apt install android-tools-adb")
        return False
    return True


def connect(ip):
    serial = "%s:5555" % ip
    rc, out, err = run(["adb", "connect", serial])
    print("adb connect → %s" % (out or err))
    rc, out, err = run(["adb", "devices", "-l"])
    print(out)
    if "unauthorized" in out:
        print("\n[!] 电视上弹了授权框：用 Fire 遥控器点“允许”，然后重跑。")
        return None
    if serial not in out:
        print("\n[!] 没连上。检查：同一 Wi-Fi、IP 正确、ADB 调试已开、防火墙。")
        return None
    return serial


def props(serial):
    print("== 设备信息 ==")
    for prop in ("ro.product.model", "ro.product.manufacturer",
                 "ro.build.version.release", "ro.build.version.sdk"):
        rc, out, _ = adb(serial, "shell", "getprop", prop)
        print("  %-28s %s" % (prop, out or "?"))


def media_sessions(serial, raw=False):
    rc, out, err = adb(serial, "shell", "dumpsys", "media_session", timeout=30)
    if rc != 0:
        return []
    sessions = []
    for block in out.split("Media session:")[1:]:
        pkg_match = re.search(r"package=([\w.]+)", block)
        state_match = re.search(r"PlaybackState \{state=(\d+)", block)
        if not state_match:
            continue
        sessions.append({
            "package": pkg_match.group(1) if pkg_match else "?",
            "state": int(state_match.group(1)),
        })
    if raw:
        for line in out.splitlines():
            if "package=" in line or "PlaybackState" in line:
                print("  " + line.strip())
    return sessions


def print_sessions(sessions, title):
    print("== %s ==" % title)
    if not sessions:
        print("  没有活动的媒体会话（先播放一个视频再测）")
        return
    for s in sessions:
        print("  %-38s state=%d (%s)"
              % (s["package"], s["state"], STATE_NAMES.get(s["state"], "?")))


def focus(serial):
    rc, out, _ = adb(serial, "shell", "dumpsys", "window")
    print("== 当前前台 ==")
    for line in out.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            print("  " + line.strip())


def pause_test(serial, resume):
    before = media_sessions(serial)
    print_sessions(before, "暂停前")
    playing = [s for s in before if s["state"] == 3]
    if not playing:
        print("\n先让 Fire TV 播放一个视频，再跑 --pause-test。")
        return False

    print("\n发送 KEYCODE_MEDIA_PLAY_PAUSE（keyevent 85）...")
    rc, out, err = adb(serial, "shell", "input", "keyevent", "85")
    if rc != 0:
        print("发送失败：%s" % (err or out))
        return False

    time.sleep(2.0)
    after = media_sessions(serial)
    print_sessions(after, "暂停后")

    still_playing = [s for s in after if s["state"] == 3]
    verdict = not still_playing
    print("\n结果：%s" % ("暂停有效 ✔" if verdict else "没有变化 ✘"))

    if not verdict:
        print("可以再试：keyevent 127（PAUSE）、keyevent 23（确定键，模拟按屏）。")
        print("有些 App 不响应媒体键，需要针对该 App 换方案。")

    if resume:
        print("\n恢复播放（再发一次 85）...")
        adb(serial, "shell", "input", "keyevent", "85")
    return verdict


def main():
    parser = argparse.ArgumentParser(description="Fire TV Stick ADB 控制探测")
    parser.add_argument("--ip", required=True, help="Fire TV 的局域网 IP")
    parser.add_argument("--pause-test", action="store_true", help="真的发一次暂停键")
    parser.add_argument("--resume", action="store_true", help="测完恢复播放")
    parser.add_argument("--raw", action="store_true", help="打印 media_session 原始行")
    args = parser.parse_args()

    if not check_adb():
        return 2

    serial = connect(args.ip)
    if not serial:
        return 1

    props(serial)
    focus(serial)
    print_sessions(media_sessions(serial, raw=args.raw), "当前媒体会话")

    if args.pause_test:
        ok = pause_test(serial, args.resume)
        print("\n下一步：如果暂停有效，就可以把 tvgate 接到 Fire TV 上；"
              "无效则告诉我孩子常用 App，我再定替代方案。")
        return 0 if ok else 3

    print("\n连接正常。下一步：播放一个视频，再跑一次加 --pause-test 的命令。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
