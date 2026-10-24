#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""哨兵 —— 只看，不决定。

它自己不回消息、不挑视频、不写字。只干四件事：

  1. 按周期看有没有新东西（@ / 回复 / 私信未读）
  2. 用四道闸决定"该不该叫醒 AI"
  3. 写任务包到 inbox/，调 dsh 把 AI 叫醒
  4. 记日志、记事件流水、出错弹窗

用法：
    python fish.py                 # 常驻
    python fish.py --fire          # 现在叫醒一次（读消息）
    python fish.py --fire --scan   # 现在叫醒一次（刷视频）
    python fish.py --fire --diary  # 现在叫醒一次（写日记）
    python fish.py --fire --dry    # 只写任务包，不真叫醒
    python fish.py --fire --new    # 强制开新会话
    python fish.py --once          # 只跑一轮判断，不叫醒
    python fish.py --status        # 看当前状态
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

CODE = os.path.dirname(os.path.abspath(__file__))       # code\
ROOT = os.path.dirname(CODE)                            # 大肥鱼\
MEM = os.path.join(ROOT, "memory")
EVENTS = os.path.join(MEM, "events")
INBOX = os.path.join(ROOT, "inbox")
LOGS = os.path.join(ROOT, "logs")
CONFIG_FILE = os.path.join(ROOT, "config.json")
STATE_FILE = os.path.join(MEM, "state.json")

# 票据只从工作区的 credential\ 里读 —— 不依赖任何外部目录，文件夹搬到哪都跟着走
DEFAULT_CRED = os.path.join(ROOT, "credential", "bili_credential.json")
POLL_TICK = 30          # 秒：多久看一次
WAKE_TIMEOUT = 600      # 秒：一次叫醒最多等多久

# 自己的 DSH_HOME：桌面版 .dsh 下那个 headless profile 的 cordis.yml
# 被锁着（连新建文件都拒绝访问），所以整个 home 复制一份到工作区里用
DSH_HOME = os.path.join(ROOT, "dsh-home")
PROFILE_PKG = """{
  "name": "dsh-profile-headless",
  "private": true,
  "dependencies": {},
  "dsh": {
    "profile": {
      "bundles": [
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-headless"
      ]
    }
  }
}
"""


# ------------------------------------------------------------------ 基础设施


def now_ts() -> float:
    return time.time()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def load_cfg() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ensure_dsh_home() -> str:
    """准备一份干净的 DSH_HOME，让 headless 会话不跟桌面版抢目录。

    桌面版 `~/.dsh/profiles/headless/cordis.yml` 实测写不进去（连在该目录
    新建文件都 Permission denied），而 dsh 每次启动都无条件重写它，于是
    唤醒必然失败。这里把 profile 抄到工作区，用 DSH_HOME 指过去。
    """
    dst = os.path.join(DSH_HOME, "profiles", "headless")
    os.makedirs(dst, exist_ok=True)
    for d in ("cache", "logs", "sessions", "storages"):
        os.makedirs(os.path.join(DSH_HOME, d), exist_ok=True)
    if os.path.exists(os.path.join(dst, "package.json")):
        return DSH_HOME

    src = os.path.join(os.path.expanduser("~"), ".dsh", "profiles", "headless")
    ok = False
    if os.path.isdir(src):
        try:
            for name in os.listdir(src):
                p = os.path.join(src, name)
                if os.path.isfile(p):
                    shutil.copyfile(p, os.path.join(dst, name))
            ok = os.path.exists(os.path.join(dst, "package.json"))
        except Exception as e:
            log(f"[home] 抄 profile 失败（用内置模板）：{e}")

    if not ok:
        with open(os.path.join(dst, "package.json"), "w", encoding="utf-8") as f:
            f.write(PROFILE_PKG)
        with open(os.path.join(dst, "cordis.patch.yml"), "w", encoding="utf-8") as f:
            f.write("[]\n")
        with open(os.path.join(dst, "cordis.yml"), "w", encoding="utf-8") as f:
            f.write("[]\n")
        with open(os.path.join(dst, "pnpm-workspace.yaml"), "w", encoding="utf-8") as f:
            f.write("packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n")

    log(f"[home] 用独立 DSH_HOME：{DSH_HOME}")
    return DSH_HOME


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(os.path.join(LOGS, f"sentinel-{today().replace('-', '')}.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def event(kind: str, what: str, extra: dict | None = None):
    """写进 memory/events/<日期>.jsonl —— AI 写日记时读的就是这里。"""
    try:
        os.makedirs(EVENTS, exist_ok=True)
        row = {"ts": now_ts(), "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "kind": kind, "what": what}
        if extra:
            row.update(extra)
        with open(os.path.join(EVENTS, f"{today()}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"[warn] 事件流水写不进：{e}")


def alert(msg: str) -> bool:
    """弹窗。返回 True=继续，False=暂停。"""
    log(f"[alert] {msg}")
    try:
        import ctypes

        MB_OKCANCEL, MB_ICONWARNING = 0x1, 0x30
        r = ctypes.windll.user32.MessageBoxW(0, msg, "大肥鱼 · 哨兵", MB_OKCANCEL | MB_ICONWARNING)
        return r == 1
    except Exception:
        return True


# ------------------------------------------------------------------ 单实例


def load_state() -> dict:
    st = read_json(STATE_FILE, {}) or {}
    st.setdefault("wakes", [])
    return st


def set_state(**kw) -> dict:
    """只改给定的键 —— 别覆盖另一个进程刚写进去的东西。"""
    st = read_json(STATE_FILE, {}) or {}
    st.update(kw)
    write_json(STATE_FILE, st)
    return st


# 这些键由 set_state 独占（会话、进程、归档）。主循环整份写盘时必须跳过它们，
# 否则内存里那份旧 state 会把 wake() 刚存好的 session 又盖成空串。
STATE_OWNED = ("session", "session_created", "session_archive", "pid", "started")


def save_state(mem: dict) -> dict:
    """主循环落盘：先读盘再合并 —— 绝不用内存里的旧会话盖掉盘上的新会话。"""
    disk = read_json(STATE_FILE, {}) or {}
    for k, v in (mem or {}).items():
        if k in STATE_OWNED:
            continue
        disk[k] = v
    write_json(STATE_FILE, disk)
    return disk


def _kill_pid(pid: int) -> bool:
    """结束一个旧哨兵（连带它的 dsh 子进程）。"""
    try:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def acquire_lock() -> bool:
    """单实例：发现旧的还在跑，就结束它，由本进程接管值班。

    主人要的是「双击哪个都一样，永远只有一个在干活」，所以这里不做
    "有就算了"的退出，而是主动收编 —— 旧进程留着只会抢写 state / quota。
    """
    try:
        st = read_json(STATE_FILE, {}) or {}
        pid = st.get("pid")
        if pid and int(pid) != os.getpid() and _pid_alive(int(pid)):
            log(f"[lock] 发现旧的哨兵还在跑（pid={pid}），先结束它再接管")
            ok = _kill_pid(int(pid))
            log(f"[lock] 旧哨兵 {'已结束' if ok else '没能结束（可能已经自己退了）'}")
            time.sleep(1.0)
        set_state(pid=os.getpid(), started=now_ts(), heartbeat=now_ts())
        log(f"[lock] 单实例拿到手（pid={os.getpid()}）")
        return True
    except Exception as e:
        log(f"[lock] 单实例锁不可用（{e}），继续跑")
        return True


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


# ------------------------------------------------------------------ 读消息


def _cred():
    from bilibili_api import Credential

    cfg = load_cfg()
    path = cfg.get("credential_file") or DEFAULT_CRED
    d = read_json(path, None) or {}
    return Credential(
        sessdata=d.get("sessdata"),
        bili_jct=d.get("bili_jct"),
        buvid3=d.get("buvid3"),
        dedeuserid=d.get("dedeuserid"),
    )


def _self_uid() -> int:
    cfg = load_cfg()
    if cfg.get("self_uid"):
        return int(cfg["self_uid"])
    d = read_json(cfg.get("credential_file") or DEFAULT_CRED, {}) or {}
    try:
        return int(d.get("dedeuserid") or 0)
    except Exception:
        return 0


def _bvid_of(uri: str) -> str:
    m = re.search(r"/video/(BV[0-9A-Za-z]+)", uri or "")
    return m.group(1) if m else ""


def _parse(it: dict, kind: str) -> dict | None:
    inner = it.get("item") or {}
    user = it.get("user") or {}
    src = inner.get("source_id") or it.get("id") or 0
    try:
        src = int(src)
    except Exception:
        src = 0
    if not src:
        return None
    root = 0
    try:
        root = int(inner.get("root_id") or 0)
    except Exception:
        root = 0
    text = (inner.get("source_content") or it.get("content") or "").strip()
    if not text:
        text = (it.get("title") or "").strip()
    uri = inner.get("uri") or it.get("uri") or ""
    return {
        "kind": kind,
        "rpid": src,
        "oid": int(inner.get("subject_id") or 0),
        "root": root or src,
        "from_uid": int(user.get("mid") or 0),
        "from_name": user.get("nickname") or "",
        "text": text[:800],
        "root_text": (inner.get("root_reply_content") or "")[:300],
        "uri": uri,
        "business_id": int(inner.get("business_id") or it.get("business_id") or 0),
        "bvid": _bvid_of(uri),
        "ts": int(it.get("at_time") or it.get("reply_time") or 0),
    }


async def _root_text(oid: int, root_id: int, cred) -> str:
    """楼中楼：按 root_id 读出楼层根（楼主）那句。@ 消息只给 target_id，reply 有时只给 root_id。"""
    if not oid or not root_id:
        return ""
    import aiohttp

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={cred.sessdata}; buvid3={cred.buvid3}",
    }
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.bilibili.com/x/v2/reply/reply",
                params={"type": 1, "oid": int(oid), "root": int(root_id), "ps": 1, "pn": 1},
                headers=headers,
            ) as r:
                body = await r.json(content_type=None)
    except Exception:
        return ""
    root = (body.get("data") or {}).get("root") or {}
    return str((root.get("content") or {}).get("message") or "").strip()[:300]


def _too_old(m: dict, now: float, cfg: dict) -> bool:
    """超过 max_age_hours 的旧消息就别再叫醒了（默认 24 小时）。"""
    try:
        hours = float(cfg.get("max_age_hours", 24) or 24)
    except Exception:
        hours = 24.0
    ts = m.get("ts") or 0
    return bool(ts) and (now - ts) > hours * 3600


async def gather(cfg: dict) -> list[dict]:
    from bilibili_api import session

    cred = _cred()
    att = cfg.get("attitude") or {}
    mode = cfg.get("mode") or {}
    me = _self_uid()
    now = now_ts()
    out: list[dict] = []

    if att.get("at") != "forbid" and int(mode.get("at", 0)) != 0:
        try:
            r = await session.get_at(credential=cred)
            for it in r.get("items") or []:
                p = _parse(it, "at")
                if not p or p["from_uid"] == me or _too_old(p, now, cfg):
                    continue
                inner = it.get("item") or {}
                try:
                    target = int(inner.get("target_id") or 0) or int(inner.get("root_id") or 0)
                except Exception:
                    target = 0
                if target and not p["root_text"]:
                    p["root_text"] = await _root_text(int(inner.get("subject_id") or 0), target, cred)
                out.append(p)
        except Exception as e:
            log(f"[warn] 读 @ 失败：{e}")

    if att.get("reply") != "forbid" and int(mode.get("reply", 0)) != 0:
        try:
            r = await session.get_replies(credential=cred)
            for it in r.get("items") or []:
                p = _parse(it, "reply")
                if not p or p["from_uid"] == me or _too_old(p, now, cfg):
                    continue
                inner = it.get("item") or {}
                try:
                    root_id = int(inner.get("root_id") or 0)
                except Exception:
                    root_id = 0
                if root_id and not p["root_text"]:
                    p["root_text"] = await _root_text(int(inner.get("subject_id") or 0), root_id, cred)
                out.append(p)
        except Exception as e:
            log(f"[warn] 读回复失败：{e}")

    if att.get("dm") != "forbid" and int(mode.get("dm", 0)) != 0:
        # 两处都会话：1=最近会话；2=未关注人（陌生人第一次私信都在这里，原来只看 1 会漏）
        dm_seen_uid = set()
        for st in (1, 2):
            try:
                r = await session.get_sessions(credential=cred, session_type=st)
            except Exception as e:
                log(f"[warn] 读私信列表(type={st})失败：{e}")
                continue
            for s in r.get("session_list") or []:
                if not s.get("unread_count"):
                    continue
                uid = int(s.get("talker_id") or 0)
                if not uid or uid == me or uid in dm_seen_uid:
                    continue
                dm_seen_uid.add(uid)
                lm = s.get("last_msg") or {}
                raw = lm.get("content") or ""
                try:
                    raw = json.loads(raw).get("content") or raw
                except Exception:
                    pass
                try:
                    ts = int(lm.get("timestamp") or 0)
                except Exception:
                    ts = 0
                if not ts:
                    try:
                        ts = int(s.get("session_ts") or 0) // 1000
                    except Exception:
                        ts = 0
                out.append({
                    "kind": "dm", "rpid": 0, "oid": 0, "root": 0,
                    "from_uid": uid, "from_name": s.get("name") or "",
                    "text": f"（{s.get('unread_count')} 条未读）{str(raw)[:300]}",
                    "root_text": "", "uri": "", "bvid": "",
                    "ts": ts,
                })

    return out


# ------------------------------------------------------------------ 四道闸


def scan_today_count() -> int:
    """今天读过的视频数 —— AI 侧记在 seen_videos.json，这里只数不写。"""
    d = read_json(os.path.join(MEM, "seen_videos.json"), {}) or {}
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    n = 0
    for v in d.values():
        try:
            if float((v or {}).get("ts") or 0) >= start:
                n += 1
        except Exception:
            continue
    return n


def _key(m: dict) -> str:
    return f"{m['kind']}:{m['rpid'] or m['from_uid']}:{m['ts']}"


def gate(state: dict, cfg: dict, items: list[dict], now: float) -> tuple[bool, str, list[dict]]:
    """返回 (放行?, 理由, 真正的新消息)。"""
    if not cfg.get("sentinel_enabled", True):
        return False, "总开关关着", []

    if cfg.get("night_quiet"):
        rng = cfg.get("night_quiet_range") or ["00:00", "07:00"]
        if _in_night(hhmm(), rng):
            return False, f"夜间静默中（{rng[0]}~{rng[1]}）", []

    seen = state.get("seen") or {}
    fresh = [m for m in items if _key(m) not in seen]
    if not fresh:
        return False, "没有新东西", []

    att = cfg.get("attitude") or {}
    min_count = int(cfg.get("min_count", 1) or 1)
    if len(fresh) < min_count:
        return False, f"新东西 {len(fresh)} 条 < 门槛 {min_count}", fresh

    interval = int(cfg.get("wake_interval_seconds", 600) or 600)
    last = float(state.get("last_wake") or 0)
    if now - last < interval:
        return False, f"距上次叫醒才 {int(now - last)} 秒 < {interval}", fresh

    hourly = int((cfg.get("caps") or {}).get("hourly_wakes", 6) or 6)
    wakes = [t for t in (state.get("wakes") or []) if now - t < 3600]
    if len(wakes) >= hourly:
        return False, f"这一小时已经叫醒 {len(wakes)} 次，到顶了", fresh

    n_filter = sum(1 for m in fresh if att.get(m["kind"]) == "filter")
    tail = f"，其中 {n_filter} 条醒来后要先过筛" if n_filter else ""
    return True, f"{len(fresh)} 条新的{tail}", fresh


def _plus_minutes(hhmm_str: str, minutes: int) -> str:
    try:
        h, m = hhmm_str.split(":")
        total = int(h) * 60 + int(m) + minutes
        total %= 24 * 60
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return "23:59"


def _in_window(hm: str, t: str, window_min: int = 120) -> bool:
    """到点了，且没拖太久（错过超过 2 小时就不补跑）。"""
    return t <= hm <= _plus_minutes(t, window_min)


def _in_night(hm: str, rng) -> bool:
    """夜间静默窗口。支持跨零点（23:00~07:00）。"""
    try:
        start, end = str(rng[0]), str(rng[1])
    except Exception:
        start, end = "00:00", "07:00"
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end


def due_scheduled(state: dict, cfg: dict, now: float) -> tuple[str, str] | tuple[None, None]:
    """到点该干的定时活：刷视频 / 写日记。"""
    day = today()
    hm = hhmm()

    done_scan = (state.get("scan_done") or {}).get(day) or []
    for t in cfg.get("scan_at") or []:
        if _in_window(hm, t) and t not in done_scan:
            if int((state.get("scan_count") or {}).get(day, 0)) >= int((cfg.get("caps") or {}).get("scan_per_day", 10) or 10):
                return None, None
            return "scan", t

    diary_at = cfg.get("diary_at") or "21:30"
    if _in_window(hm, diary_at) and (state.get("diary_done") or "") != day:
        return "diary", diary_at

    return None, None


# ------------------------------------------------------------------ 任务包


def write_pack(kind: str, payload: dict) -> str:
    os.makedirs(INBOX, exist_ok=True)
    name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{kind}.json"
    path = os.path.join(INBOX, name)
    write_json(path, payload)

    # 只留最近 10 个包
    try:
        files = sorted(f for f in os.listdir(INBOX) if f.endswith(".json"))
        for old in files[:-10]:
            os.remove(os.path.join(INBOX, old))
    except Exception:
        pass
    return path


def policy_snapshot(cfg: dict) -> dict:
    if CODE not in sys.path:
        sys.path.insert(0, CODE)
    from tools import quota_state

    return {
        "模式": cfg.get("mode"),
        "态度": cfg.get("attitude"),
        "限额": cfg.get("caps"),
        "配额已用": quota_state(),
        "私信上限字数": cfg.get("dm_max_chars", 450),
        "号主": {
            "uid": (cfg.get("share") or {}).get("master_uid", 0),
            "名字": (cfg.get("share") or {}).get("master_name", ""),
            "主动评论会带上@他": (cfg.get("share") or {}).get("at_on_every_comment", True),
            "什么时候该想起他": (cfg.get("share") or {}).get("tell_when_replying", "经常"),
        },
    }


# ------------------------------------------------------------------ 叫醒


def _dsh_bin(cfg: dict) -> str:
    """找 dsh 在哪：配置 > 环境变量 > PATH > 常见安装位置。"""
    if cfg.get("dsh_bin"):
        return cfg["dsh_bin"]
    env = os.environ.get("DSH_BIN")
    if env and os.path.exists(env):
        return env
    found = shutil.which("dsh")
    if found:
        return found
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "DeepSeek",
                     "resources", "runtime", "cli", "bin", "dsh.cmd"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "DeepSeek",
                     "resources", "runtime", "cli", "bin", "dsh.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "DeepSeek",
                     "resources", "runtime", "cli", "bin", "dsh.cmd"),
        os.path.join(home, "AppData", "Local", "Programs", "DeepSeek",
                     "resources", "runtime", "cli", "bin", "dsh.cmd"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "dsh"


OVERLAY_TEMPLATE = """- id: credentials
  disabled: false

- id: authorization
  disabled: false

- id: deepseek-account
  disabled: false

- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-flash
    reasoningEffort: low

- insert:
    - id: mcp-dafeiyu
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: dafeiyu
        transport: stdio
        command: '{python}'
        args:
          - '{tools}'
        env:
          PYTHONUTF8: '1'
          PYTHONIOENCODING: 'utf-8'
"""


def ensure_overlay() -> str:
    """生成给 dsh 的 patch 文件，放在 dsh-home 里（不占工作区根目录）。"""
    py = sys.executable or "python"
    tools = os.path.join(CODE, "tools.py")
    text = OVERLAY_TEMPLATE.format(
        python=py.replace("\\", "/"),
        tools=tools.replace("\\", "/"),
    )

    os.makedirs(DSH_HOME, exist_ok=True)
    path = os.path.join(DSH_HOME, "overlay.yml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def ensure_session(cfg: dict) -> str:
    """拿到要续的那个会话 id；没有就返回空串（表示新建）。"""
    return (read_json(STATE_FILE, {}) or {}).get("session") or ""


def wake(cfg: dict, prompt: str, why: str) -> bool:
    """叫醒 AI 一次。成功返回 True。"""
    dsh = _dsh_bin(cfg)
    overlay = ensure_overlay()
    sid = ensure_session(cfg)

    cmd = [dsh]
    if os.path.exists(overlay):
        # --patch 是 launcher 层选项，必须排在 --profile 前面
        cmd += ["--patch", overlay]
    cmd += ["--profile", cfg.get("dsh_profile") or "headless", "--json"]
    if sid:
        cmd += ["--session-id", sid]
    cmd += [prompt]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["DSH_HOME"] = ensure_dsh_home()
    if cfg.get("llm_key"):
        env["DEEPSEEK_API_KEY"] = cfg["llm_key"]

    t0 = now_ts()
    log(f"[wake] {why} → 叫醒（会话 {sid or '新建'}）")
    try:
        r = subprocess.run(
            cmd, cwd=ROOT, env=env, timeout=WAKE_TIMEOUT,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        alert("叫醒超时了（10 分钟没回来）。\n\n点“确定”继续重试，点“取消”暂停哨兵。")
        return False
    except Exception as e:
        alert(f"叫醒失败：{e}\n\n点“确定”继续重试，点“取消”暂停哨兵。")
        return False

    out = (r.stdout or "") + (r.stderr or "")
    dt = now_ts() - t0

    # 抓 sessionId / 用量
    m = re.search(r'"sessionId"\s*:\s*"(session-[^"]+)"', out)
    got_sid = m.group(1) if m else ""
    if got_sid and got_sid != sid:
        set_state(session=got_sid, session_created=now_ts())
        log(f"[wake] 会话定为 {got_sid}")

    u = (re.search(r'"totalTokens"\s*:\s*(\d+)', out)
         or re.search(r'"total"\s*:\s*(\d+)', out))
    tokens = int(u.group(1)) if u else 0

    ok = r.returncode == 0
    log(f"[wake] {'完成' if ok else '失败'} 用时 {dt:.0f}s 代号 {r.returncode} token≈{tokens}")

    # 上下文太长 → 下次开新会话
    if tokens and tokens > int(cfg.get("session_max_tokens", 60000) or 60000):
        st = read_json(STATE_FILE, {}) or {}
        arch = st.get("session_archive") or []
        arch.append({"id": got_sid or sid, "retired": now_ts(),
                     "reason": "context_too_long", "tokens": tokens})
        set_state(session_archive=arch[-20:], session="")
        log("[wake] 上下文超了，下次开新会话")

    # 记一笔本轮用量，--status / 日志能看到会话是不是真在续（续上时这个数会明显小于首轮）
    set_state(last_tokens=tokens, last_wake_at=now_ts())

    if not ok:
        low = out.lower()
        hint = ""
        if "insufficient balance" in low or '"quota"' in low:
            hint = "DeepSeek 账户余额不足了。\n去 platform.deepseek.com 充值，\n或者改 config.json 里的 llm_key 换一个有余额的。"
        elif "missing_credential" in low:
            hint = "config.json 里的 llm_key 是空的，或者这个 key 无效。"
        elif "eperm" in low:
            hint = "profile 目录写不进去，DSH_HOME 隔离没生效。"
        lines = [l for l in out.strip().splitlines() if l.strip()]
        tail = lines[-3:] if lines else [out[-300:]]
        log("[wake] 失败输出：" + " | ".join(tail))
        event("wake_failed", why, {"code": r.returncode, "hint": hint})
        body = "叫醒失败。"
        if hint:
            body += "\n\n" + hint
        body += "\n\n" + "\n".join(tail[-2:])
        body += "\n\n点“确定”继续重试，点“取消”暂停哨兵。"
        alert(body)
        return False

    event("wake", why, {"tokens": tokens, "seconds": int(dt)})
    return True


def prompt_for(kind: str) -> str:
    head = "读 IDENTITY.md、DUTY.md、TOOLS/00-目录和任务包.md（工具按目录挑，别整份读），"
    if kind == "scan":
        return head + "然后看 inbox 里最新的任务包（scan）。这是你自己的时间：想清楚今天想看什么，自己搜、自己看，看完自己决定说不说话。做完用一两句话说你干了什么。"
    if kind == "diary":
        return head + "然后看 inbox 里最新的任务包（diary）。整理今日的日记，删除或者压缩精简，和主人有关的只能压缩不可删除。整理完发一条动态说说——不强制主题但是要写。做完用一两句话说你干了什么。"
    return head + "然后看 inbox 里最新的任务包（messages），按你的判断处理里面的消息。做完用一两句话说你干了什么。"


# ------------------------------------------------------------------ 主循环


def tick(state: dict, fire: bool = True, guard_first_run: bool = True) -> dict:
    cfg = load_cfg()
    now = now_ts()

    if cfg.get("night_quiet"):
        rng = cfg.get("night_quiet_range") or ["00:00", "07:00"]
        if _in_night(hhmm(), rng):
            log(f"[sleep] 夜间静默（{rng[0]}~{rng[1]}），下一轮再看")
            return state

    if guard_first_run and "seen" not in state:
        items = asyncio.run(gather(cfg))
        state["seen"] = {_key(m): now for m in items}
        log(f"[first-run] 去重表是空的，把现有 {len(items)} 条消息标记为已见，从下一条开始")
        event("first_run", f"标记 {len(items)} 条历史消息")
        return state

    kind, t = due_scheduled(state, cfg, now)
    if kind:
        payload = {"kind": kind, "created_at": now, "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "policy": policy_snapshot(cfg)}
        if kind == "scan":
            payload["scan"] = cfg.get("scan") or {}
        path = write_pack(kind, payload)
        log(f"[{kind}] 到点了（{t}），任务包 {os.path.basename(path)}")
        if fire:
            if wake(cfg, prompt_for(kind), f"定时 {kind} {t}"):
                state.setdefault("wakes", []).append(now)
                state["last_wake"] = now
                if kind == "scan":
                    d = state.setdefault("scan_done", {}).setdefault(today(), [])
                    d.append(t)
                    sc = state.setdefault("scan_count", {})
                    sc[today()] = int(sc.get(today(), 0)) + 1
                    log(f"[scan] 本轮刷完，今日已读 {scan_today_count()} 个视频")
                else:
                    state["diary_done"] = today()
        return state

    items = asyncio.run(gather(cfg))
    ok, why, fresh = gate(state, cfg, items, now)
    if not ok:
        log(f"[idle] {why}")
        return state

    payload = {
        "kind": "messages", "created_at": now, "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "items": fresh, "policy": policy_snapshot(cfg),
    }
    path = write_pack("messages", payload)
    log(f"[notify] {why}，任务包 {os.path.basename(path)}")
    if fire:
        if wake(cfg, prompt_for("messages"), why):
            state.setdefault("wakes", []).append(now)
            state["last_wake"] = now
            seen = state.setdefault("seen", {})
            for m in fresh:
                seen[_key(m)] = now
            cutoff = now - 7 * 86400
            state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    return state


def manual_fire(cfg: dict, args) -> int:
    """手动叫醒一次 —— 不管四道闸，也不管有没有新消息。"""
    kind = "scan" if args.scan else ("diary" if args.diary else "messages")

    if args.new:
        set_state(session="")
        log("[fire] 已清空会话记录，这次会新建")

    payload = {
        "kind": kind,
        "created_at": now_ts(),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "policy": policy_snapshot(cfg),
    }

    if kind == "messages":
        items = asyncio.run(gather(cfg))
        att = cfg.get("attitude") or {}
        seen = (read_json(STATE_FILE, {}) or {}).get("seen") or {}
        fresh = [m for m in items
                 if att.get(m["kind"]) != "forbid" and (args.all or _key(m) not in seen)]
        payload["items"] = fresh
        log(f"[fire] 抓到 {len(fresh)} 条要处理的（通知列表里共 {len(items)} 条）")
    elif kind == "scan":
        payload["scan"] = cfg.get("scan") or {}

    path = write_pack(kind, payload)
    log(f"[fire] 任务包 {os.path.basename(path)}")

    if args.dry:
        log("[fire] 只写任务包，不叫醒（--dry）")
        return 0

    ok = wake(cfg, prompt_for(kind), f"手动 {kind}")
    if ok and kind == "messages":
        seen = (read_json(STATE_FILE, {}) or {}).get("seen") or {}
        now = now_ts()
        for m in payload.get("items") or []:
            seen[_key(m)] = now
        cutoff = now - 7 * 86400
        set_state(seen={k: v for k, v in seen.items() if v >= cutoff})
        log(f"[fire] {len(payload.get('items') or [])} 条已标记为已交付（不会重复回）")
    log("[fire] 成功" if ok else "[fire] 失败")
    return 0 if ok else 1


def boot_scan() -> bool:
    """开机先刷一轮视频，刷完接着正常监听。"""
    cfg = load_cfg()
    now = now_ts()
    payload = {
        "kind": "scan",
        "created_at": now,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "policy": policy_snapshot(cfg),
        "scan": cfg.get("scan") or {},
    }
    path = write_pack("scan", payload)
    log(f"[boot] 开机先刷一轮视频，任务包 {os.path.basename(path)}")
    if not wake(cfg, prompt_for("scan"), "开机刷视频"):
        log("[boot] 这轮没叫醒成功，接着正常监听")
        return False
    st = load_state()
    st.setdefault("wakes", []).append(now)
    st["last_wake"] = now
    sc = st.setdefault("scan_count", {})
    sc[today()] = int(sc.get(today(), 0)) + 1
    write_json(STATE_FILE, st)
    log("[boot] 刷完了，接下来正常监听")
    log(f"[boot] 今日已读 {scan_today_count()} 个视频（目标 {int((cfg.get('caps') or {}).get('scan_per_day', 15) or 15)} 个没看过的）")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑一轮判断，不叫醒")
    ap.add_argument("--fire", action="store_true", help="现在叫醒一次")
    ap.add_argument("--scan", action="store_true", help="配合 --fire：刷视频")
    ap.add_argument("--diary", action="store_true", help="配合 --fire：写日记")
    ap.add_argument("--dry", action="store_true", help="配合 --fire：只写任务包")
    ap.add_argument("--new", action="store_true", help="配合 --fire：强制开新会话")
    ap.add_argument("--all", action="store_true", help="配合 --fire：处理过的也再来一遍")
    ap.add_argument("--status", action="store_true", help="打印状态")
    ap.add_argument("--boot-scan", action="store_true", help="开机先刷一轮视频，之后正常监听")
    args = ap.parse_args()

    if args.status:
        st = read_json(STATE_FILE, {}) or {}
        cfg = load_cfg()
        pid = st.get("pid")
        hb = st.get("heartbeat") or 0
        print(json.dumps({
            "开关": cfg.get("sentinel_enabled"),
            "周期(秒)": cfg.get("wake_interval_seconds"),
            "最少条数": cfg.get("min_count"),
            "模式": cfg.get("mode"),
            "态度": cfg.get("attitude"),
            "会话": ensure_session(cfg) or "(还没建)",
            "哨兵进程": f"{pid}（{'活着' if pid and _pid_alive(int(pid)) else '不在了'}）" if pid else "还没跑过",
            "最后心跳": datetime.fromtimestamp(hb).strftime("%Y-%m-%d %H:%M:%S") if hb else "无",
            "上次叫醒": datetime.fromtimestamp(st.get("last_wake", 0)).strftime("%Y-%m-%d %H:%M") if st.get("last_wake") else "从未",
            "上轮 token": st.get("last_tokens") or "(没记到)",
            "今日刷过": scan_today_count(),
            "已交付消息": len(st.get("seen") or {}),
        }, ensure_ascii=False, indent=2))
        return 0

    os.makedirs(MEM, exist_ok=True)
    os.makedirs(INBOX, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)

    if args.fire:
        return manual_fire(load_cfg(), args)

    if not args.once and not acquire_lock():
        return 1

    state = load_state()

    if args.once:
        state = tick(state, fire=False, guard_first_run=False)
        state["heartbeat"] = now_ts()
        save_state(state)
        return 0

    log(f"哨兵启动（周期 {load_cfg().get('wake_interval_seconds')}s，工作区 {ROOT}）")
    event("boot", "哨兵启动")

    if args.boot_scan:
        try:
            boot_scan()
            state = load_state()
        except Exception as e:
            log(f"[boot] 先刷一波失败：{type(e).__name__}: {e}")

    while True:
        try:
            state = tick(state, fire=True)
            state["heartbeat"] = now_ts()
            save_state(state)
        except KeyboardInterrupt:
            log("收到 Ctrl+C，退出")
            event("shutdown", "哨兵退出")
            break
        except Exception as e:
            log(f"[error] {type(e).__name__}: {e}")
            event("error", f"{type(e).__name__}: {e}")
        time.sleep(POLL_TICK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
