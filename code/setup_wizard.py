#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大肥鱼 · 第一次运行向导。

三件事：
  1. 用手机 B 站 App 扫码登录，把凭据存到 credential/bili_credential.json
  2. 填 DeepSeek API key（AI 的脑子）
  3. 探测本机的 dsh（叫醒 AI 的程序），写进 config.json

跑完这一步，双击 启动哨兵.cmd 就能用了。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys

CODE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CODE)
CRED = os.path.join(ROOT, "credential", "bili_credential.json")
CONFIG = os.path.join(ROOT, "config.json")
EXAMPLE = os.path.join(ROOT, "config.example.json")
QR = os.path.join(ROOT, "qr-login.png")


def say(text=""):
    print(text, flush=True)


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def open_file(path):
    try:
        os.startfile(path)          # Windows
    except Exception:
        say(f"（没能自动打开，你自己看一下：{path}）")


async def login_bili():
    """扫码登录，返回 (credential, uid, name)。"""
    from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents
    from bilibili_api import user

    qr = QrCodeLogin()
    await qr.generate_qrcode()
    qr.get_qrcode_picture().to_file(QR)
    say(f"二维码图片：{QR}")
    open_file(QR)
    say("用手机 B 站 App 扫码，然后在手机上点「确认登录」。")
    say("（关掉图片窗口不影响，这里会等）")

    print("等扫码", end="", flush=True)
    last = None
    while True:
        try:
            ev = await qr.check_state()
        except Exception as e:
            say(f"\n检查状态出错：{type(e).__name__}: {e}")
            return None
        if ev == QrCodeLoginEvents.DONE:
            break
        if ev == QrCodeLoginEvents.TIMEOUT:
            say("\n二维码过期，换一张。")
            await qr.generate_qrcode()
            qr.get_qrcode_picture().to_file(QR)
            open_file(QR)
            print("等扫码", end="", flush=True)
            last = None
            continue
        if ev != last:
            if ev == QrCodeLoginEvents.CONF:
                say("\n扫到了，等你在手机上确认…")
            last = ev
        print(".", end="", flush=True)
        await asyncio.sleep(2)

    cred = qr.get_credential()
    uid = int(getattr(cred, "dedeuserid", 0) or 0)
    name = ""
    try:
        info = await user.get_self_info(cred)
        uid = int(info.get("mid") or uid)
        name = info.get("uname") or ""
    except Exception:
        pass
    say(f"\n登录成功：{name or uid}（UID {uid}）")
    return cred, uid, name


def save_cred(cred):
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    data = {
        "sessdata": cred.sessdata,
        "bili_jct": cred.bili_jct,
        "buvid3": getattr(cred, "buvid3", "") or "",
        "dedeuserid": cred.dedeuserid,
        "ac_time_value": getattr(cred, "ac_time_value", "") or "",
    }
    tmp = CRED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CRED)
    say(f"凭据已保存：{CRED}")


def find_dsh():
    found = shutil.which("dsh")
    if found:
        return found
    home = os.path.expanduser("~")
    for base in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "DeepSeek"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "DeepSeek"),
        os.path.join(home, "AppData", "Local", "Programs", "DeepSeek"),
    ):
        for name in ("dsh.cmd", "dsh.exe"):
            p = os.path.join(base, "resources", "runtime", "cli", "bin", name)
            if os.path.exists(p):
                return p
    return ""


def load_example():
    try:
        with open(EXAMPLE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    say("=" * 46)
    say("  大肥鱼 · 第一次运行")
    say("=" * 46)

    try:
        import bilibili_api  # noqa: F401
    except ImportError:
        say("还没装依赖。先双击 安装依赖.cmd，装完再来。")
        return 1

    # 1. 登录
    say("\n[1/3] 登录 B 站")
    result = asyncio.run(login_bili())
    if not result:
        say("登录没成功，这次先退出。")
        return 1
    cred, uid, name = result
    save_cred(cred)

    # 2. key
    say("\n[2/3] DeepSeek API key")
    say("这是 AI 的脑子。到 https://platform.deepseek.com 申请，sk- 开头。")
    key = ask("粘贴 key（直接回车可以先跳过）：")
    if key and not key.startswith("sk-"):
        say("看着不像 sk- 开头的 key，也先收着。")

    # 3. dsh
    say("\n[3/3] 找 dsh")
    dsh = find_dsh()
    if dsh:
        say(f"找到了：{dsh}")
    else:
        say("没找到 dsh。先装 DeepSeek Harness，或在 config.json 里手动填 dsh_bin。")
        dsh = ""

    # 写 config
    cfg = load_example()
    share = cfg.setdefault("share", {})
    share["master_uid"] = uid
    share["master_name"] = name or "主人"
    if key:
        cfg["llm_key"] = key
    if dsh:
        cfg["dsh_bin"] = dsh
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)
    say(f"\n配置写好了：{CONFIG}")
    say("以后要改（额度、频率之类）直接改这个文件，哨兵 30 秒内生效。")
    say("\n下一步：双击 启动哨兵.cmd")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\n取消了。")
        sys.exit(1)
