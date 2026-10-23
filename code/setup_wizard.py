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
from urllib.parse import parse_qs, urlparse

try:
    import aiohttp
except ImportError:
    aiohttp = None

CODE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CODE)
CRED = os.path.join(ROOT, "credential", "bili_credential.json")
CONFIG = os.path.join(ROOT, "config.json")
EXAMPLE = os.path.join(ROOT, "config.example.json")
QR = os.path.join(ROOT, "qr-login.png")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
GEN_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_API = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


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


def _cookie(url: str, *names: str) -> str:
    """从登录回调 URL 里取某个 cookie 的值。"""
    try:
        q = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    for name in names:
        if name in q and q[name]:
            return q[name][0]
    return ""


def _parse_set_cookie(headers) -> dict:
    """把响应头里的 Set-Cookie 拆成 {名字: 值}。"""
    out = {}
    for raw in headers or []:
        first = raw.split(";", 1)[0]
        if "=" in first:
            k, v = first.split("=", 1)
            out[k.strip()] = v.strip()
    return out


async def _exchange_ticket(ticket_url: str) -> dict:
    """B 站新扫码流程：回调地址里只有 ticket，没有 cookie。

    访问一次 crossDomain 地址，从响应头里读 B 站下发的 cookie。
    这里直接读响应头，不依赖 cookie jar（跨域 cookie 会被 jar 拒收）。
    """
    if aiohttp is None or not ticket_url:
        return {}
    out = {}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                ticket_url,
                allow_redirects=True,
                headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            ) as r:
                for k, v in _parse_set_cookie(r.headers.getall("Set-Cookie", [])).items():
                    out[k] = v
                for k, m in r.cookies.items():
                    out[k] = m.value
    except Exception as e:
        say(f"（用 ticket 换 cookie 失败：{type(e).__name__}: {e}）")
        return {}
    if not (out.get("SESSDATA") or out.get("sessdata")):
        say(f"（票据没换出 SESSDATA，响应里只有：{sorted(out.keys())}）")
    return out


async def login_bili():
    """扫码登录，返回 (credential, uid, name)。

    不依赖 bilibili_api 的二维码封装，直接走 passport 的两个接口：
    生成二维码 → 轮询 → 成功后从回调 URL 里取 SESSDATA / bili_jct / DedeUserID。
    """
    from bilibili_api import Credential
    from bilibili_api import user as buser

    if aiohttp is None:
        say("缺少 aiohttp，先双击 安装依赖.cmd。")
        return None

    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    async with aiohttp.ClientSession(headers=headers) as http:
        try:
            async with http.get(GEN_API) as r:
                data = await r.json()
        except Exception as e:
            say(f"连不上 B 站：{type(e).__name__}: {e}")
            return None
        if not isinstance(data, dict) or data.get("code") != 0:
            say(f"生成二维码失败：{data}")
            return None
        qr_key = data["data"]["qrcode_key"]
        qr_link = data["data"]["url"]

        try:
            import qrcode
            qrcode.make(qr_link).save(QR)
            say(f"二维码图片：{QR}")
            open_file(QR)
        except Exception as e:
            say(f"（二维码图片生成失败：{e}）")
            say("（先双击 安装依赖.cmd 装好依赖再试）")
            return None

        say("用手机 B 站 App 扫码，然后在手机上点「确认登录」。")
        say("（关掉图片窗口不影响，这里会等）")
        print("等扫码", end="", flush=True)

        last = None
        payload = {}
        got = {}
        while True:
            try:
                async with http.get(POLL_API, params={"qrcode_key": qr_key}) as r:
                    d = await r.json()
                    for k, v in _parse_set_cookie(r.headers.getall("Set-Cookie", [])).items():
                        got[k] = v
                    for k, m in r.cookies.items():
                        got[k] = m.value
            except Exception as e:
                say(f"\n查询扫码状态出错：{type(e).__name__}: {e}")
                return None
            payload = d.get("data") or {}
            code = payload.get("code", d.get("code"))
            if code == 0:
                break
            if code == 86038:
                say("\n二维码过期了，重跑一次 首次运行.cmd。")
                return None
            if code == 86090 and last != 86090:
                say("\n扫到了，等你在手机上确认…")
                last = 86090
            print(".", end="", flush=True)
            await asyncio.sleep(2)
        say("")

        url = payload.get("url") or ""
        ac_time = payload.get("refresh_token") or ""
        sessdata = (_cookie(url, "SESSDATA", "sessdata")
                    or got.get("SESSDATA", "") or got.get("sessdata", ""))
        bili_jct = _cookie(url, "bili_jct") or got.get("bili_jct", "")
        uid_s = (_cookie(url, "DedeUserID", "dedeuserid")
                 or got.get("DedeUserID", "") or got.get("dedeuserid", ""))
        if not sessdata and url:
            say("B 站现在用 ticket 换 cookie，正在换…")
            extra = await _exchange_ticket(url)
            sessdata = extra.get("SESSDATA", "") or extra.get("sessdata", "")
            bili_jct = bili_jct or extra.get("bili_jct", "")
            uid_s = uid_s or extra.get("DedeUserID", "") or extra.get("dedeuserid", "")
        if not sessdata:
            say("登录回调里没有 SESSDATA，这次没拿到凭据。")
            say(f"（回调地址：{url[:240]}）")
            return None

        cred = Credential(sessdata=sessdata, bili_jct=bili_jct,
                          dedeuserid=uid_s, ac_time_value=ac_time)
        uid = int(uid_s or 0)
        name = ""
        try:
            info = await buser.get_self_info(cred)
            uid = int(info.get("mid") or uid)
            name = info.get("uname") or ""
        except Exception:
            pass
        say(f"登录成功：{name or uid}（UID {uid}）")
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
    if not data["sessdata"]:
        say("警告：凭据里 sessdata 是空的，哨兵会读不了消息。")
        return False
    return True


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
    if not save_cred(cred):
        say("凭据是空的，先不写配置。检查网络后再跑一次。")
        return 1

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
