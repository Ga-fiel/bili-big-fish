#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大肥鱼 · 控制台（图形界面）

双击「控制台.cmd」→ 自动打开浏览器 → 改 → 点保存。
哨兵每 30 秒重读一次 config.json，改完不用重启。

    python panel.py            起服务并打开浏览器
    python panel.py --no-open  只起服务
    python panel.py --port 8765
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

CODE = os.path.dirname(os.path.abspath(__file__))       # code\
ROOT = os.path.dirname(CODE)                            # 大肥鱼\
MEM = os.path.join(ROOT, "memory")
LOGS = os.path.join(ROOT, "logs")
CFG = os.path.join(ROOT, "config.json")
STATE = os.path.join(MEM, "state.json")
QUOTA = os.path.join(MEM, "quota.json")

PY = sys.executable or "python"


# ---------------------------------------------------------------- 读写

def read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def merge(dst, patch):
    """深合并：只动 patch 里有的键，别的一概保留（_说明、llm_key 等）。"""
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v


# ---------------------------------------------------------------- 状态

def pid_alive(pid):
    if not pid:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    except Exception:
        return False


def tail_log(lines=40):
    try:
        files = sorted(x for x in os.listdir(LOGS) if x.endswith(".log"))
    except Exception:
        return ""
    if not files:
        return ""
    try:
        with open(os.path.join(LOGS, files[-1]), "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except Exception as e:
        return f"（读不出来：{e}）"


def _hm(ts):
    """时间戳 → HH:MM。给界面显示用。"""
    try:
        ts = float(ts)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def status():
    st = read(STATE, {}) or {}
    pid = st.get("pid")
    q = read(QUOTA, {}) or {}
    seen = st.get("seen") or {}
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "running": bool(pid and pid_alive(pid)),
        "pid": pid if pid else None,
        "session_id": st.get("session") or "",
        "last_wake": _hm(st.get("last_wake") or 0),
        "seen": len(seen),
        "scan_today": int((st.get("scan_count") or {}).get(today, 0) or 0),
        "quota": q,
        "log": tail_log(),
    }


# ---------------------------------------------------------------- 动作

def fire(extra_args=None):
    python = PY if os.path.exists(PY) else sys.executable
    args = [python, os.path.join(CODE, "fish.py"), "--fire"] + list(extra_args or [])
    flags = 0x00000010 if os.name == "nt" else 0  # CREATE_NEW_CONSOLE
    try:
        subprocess_Popen(args, flags)
    except Exception as e:
        print("[!] 叫醒失败:", e)


def subprocess_Popen(args, flags):
    import subprocess
    subprocess.Popen(args, cwd=ROOT, creationflags=flags)


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "DaFeiYuPanel/1.0"

    def _out(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._out(200, HTML, "text/html; charset=utf-8")
        if p == "/api/config":
            return self._out(200, json.dumps(read(CFG, {}) or {}, ensure_ascii=False))
        if p == "/api/status":
            return self._out(200, json.dumps(status(), ensure_ascii=False))
        if p == "/favicon.ico":
            return self._out(204, b"")
        return self._out(404, "{}")

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}

        if p == "/api/save":
            cfg = read(CFG, {}) or {}
            merge(cfg, data)
            write(CFG, cfg)
            return self._out(200, json.dumps({"ok": True, "status": status()}, ensure_ascii=False))

        if p == "/api/wake":
            fire(tuple(data.get("args") or ()))
            return self._out(200, json.dumps({"ok": True}))

        if p == "/api/newsession":
            st = read(STATE, {}) or {}
            st["session"] = ""
            write(STATE, st)
            return self._out(200, json.dumps({"ok": True, "status": status()}, ensure_ascii=False))

        if p == "/api/open":
            target = data.get("path") or ""
            full = os.path.normpath(os.path.join(ROOT, target))
            if full.startswith(ROOT) and os.path.exists(full):
                os.startfile(full)  # noqa: 只在 Windows 用
                return self._out(200, json.dumps({"ok": True}))
            return self._out(400, json.dumps({"ok": False}))

        return self._out(404, "{}")

    def log_message(self, *a):
        pass


# ---------------------------------------------------------------- 页面

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>大肥鱼 · 控制台</title>
<style>
:root{
  --bg:#eef7fe; --bg2:#e0f0fb; --card:#ffffff; --line:#d5e7f5;
  --ink:#26415a; --ink2:#6c8aa6; --ink3:#9db4c8;
  --blue:#5aa9e0; --blue-d:#3d84b8; --blue-l:#eaf5fd;
  --ok:#5cb894; --warn:#eda35c; --bad:#e07b7b;
  --shadow:0 2px 14px rgba(61,132,184,.07);
  --radius:16px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:-apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
  background:linear-gradient(170deg,var(--bg) 0%,var(--bg2) 100%);
  color:var(--ink); min-height:100vh; padding-bottom:96px;
  -webkit-font-smoothing:antialiased;
}
header{
  position:sticky; top:0; z-index:20;
  background:linear-gradient(135deg,#ffffff 0%,#f3faff 100%);
  border-bottom:1px solid var(--line);
  padding:18px 28px; display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  backdrop-filter:saturate(180%) blur(8px);
}
header .fish{
  width:40px;height:40px;border-radius:12px;flex:0 0 auto;
  background:linear-gradient(135deg,#7fc4ee,#4d96cc);
  display:flex;align-items:center;justify-content:center;font-size:22px;
  box-shadow:0 3px 10px rgba(77,150,204,.35);
}
header h1{font-size:19px;margin:0;font-weight:650;letter-spacing:.3px}
header .sub{font-size:12px;color:var(--ink2);margin-top:2px}
.pills{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap;align-items:center}
.pill{
  font-size:12px;padding:6px 12px;border-radius:999px;border:1px solid var(--line);
  background:#fff;color:var(--ink2);display:flex;align-items:center;gap:6px;white-space:nowrap;
}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ink3)}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(92,184,148,.18)}
.dot.off{background:var(--bad);box-shadow:0 0 0 3px rgba(224,123,123,.15)}

main{max-width:1180px;margin:0 auto;padding:22px 28px;
  display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:18px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:20px 22px}
.card h2{font-size:14px;margin:0 0 4px;font-weight:650;display:flex;align-items:center;gap:8px}
.card h2 .ic{font-size:15px}
.card .hint{font-size:11.5px;color:var(--ink3);margin:0 0 16px;line-height:1.6}

.row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:9px 0;
  border-bottom:1px dashed #ecf4fa}
.row:last-child{border-bottom:0}
.row .lab{font-size:13.5px;color:var(--ink)}
.row .lab small{display:block;font-size:11px;color:var(--ink3);margin-top:3px;font-weight:400}

/* 开关 */
.sw{position:relative;width:46px;height:26px;flex:0 0 auto}
.sw input{opacity:0;width:0;height:0;position:absolute}
.sw span{position:absolute;inset:0;background:#d9e6f0;border-radius:999px;transition:.22s;cursor:pointer}
.sw span::before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;
  border-radius:50%;transition:.22s;box-shadow:0 1px 4px rgba(0,0,0,.18)}
.sw input:checked + span{background:linear-gradient(135deg,#6fb8e6,#4b93c9)}
.sw input:checked + span::before{transform:translateX(20px)}

/* 分段 */
.seg{display:inline-flex;background:#eef6fc;border-radius:10px;padding:3px;gap:2px;flex:0 0 auto}
.seg button{
  border:0;background:transparent;font:inherit;font-size:12px;padding:6px 11px;border-radius:8px;
  color:var(--ink2);cursor:pointer;transition:.15s;white-space:nowrap;
}
.seg button:hover{color:var(--blue-d)}
.seg button.sel{background:#fff;color:var(--blue-d);font-weight:650;
  box-shadow:0 1px 5px rgba(61,132,184,.16)}
.seg.ok button.sel{color:var(--ok)}
.seg.warn button.sel{color:#c47c2e}
.seg.bad button.sel{color:var(--bad)}

input[type=number],input[type=text],select{
  font:inherit;font-size:13px;color:var(--ink);background:#f7fbfe;
  border:1px solid var(--line);border-radius:10px;padding:7px 11px;outline:none;
  transition:.15s;max-width:100%;
}
input[type=number]{width:88px;text-align:right}
input[type=text]{width:100%}
input[type=number]:focus,input[type=text]:focus,select:focus{
  border-color:var(--blue);background:#fff;box-shadow:0 0 0 3px rgba(90,169,224,.14)}
select{width:auto;padding-right:26px}

/* 类型行 */
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;margin:0 0 6px;font-size:12px;color:var(--ink3);line-height:1.7}
.legend b{color:var(--ink2);font-weight:600;white-space:nowrap}
.type-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;padding:10px 0;
  border-bottom:1px dashed #ecf4fa}
.type-row:last-child{border-bottom:0}
.type-row .tag{flex:0 0 52px;margin-right:auto;font-size:13px;font-weight:600;color:var(--ink)}
.type-row .sub{font-size:11px;color:var(--ink3);font-weight:400;display:block}

.bar{height:6px;border-radius:99px;background:#e9f3fa;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#8ecdf0,#4f9ad0);transition:.4s}
.kv{display:flex;justify-content:space-between;font-size:12px;color:var(--ink2);padding:3px 0}
.kv b{color:var(--ink);font-weight:600}

pre.log{font-size:11px;line-height:1.65;background:#f7fbfe;border:1px solid var(--line);
  border-radius:10px;padding:12px;max-height:220px;overflow:auto;white-space:pre-wrap;
  word-break:break-all;color:#4a6b86;margin:0;font-family:Consolas,"Courier New",monospace}

.acts{display:flex;gap:10px;flex-wrap:wrap}
.btn{
  font:inherit;font-size:13px;padding:9px 16px;border-radius:11px;cursor:pointer;
  border:1px solid var(--line);background:#fff;color:var(--ink);transition:.15s;
}
.btn:hover{border-color:var(--blue);color:var(--blue-d);transform:translateY(-1px)}
.btn.primary{background:linear-gradient(135deg,#6fb8e6,#4b93c9);color:#fff;border-color:transparent;
  box-shadow:0 3px 12px rgba(75,147,201,.3)}
.btn.primary:hover{box-shadow:0 5px 16px rgba(75,147,201,.4)}
.btn.ghost{background:transparent;color:var(--ink2)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}

footer{
  position:fixed;left:0;right:0;bottom:0;z-index:30;
  background:rgba(255,255,255,.92);border-top:1px solid var(--line);
  backdrop-filter:blur(10px);padding:14px 28px;
  display:flex;align-items:center;gap:14px;
}
footer .state{font-size:12.5px;color:var(--ink2)}
footer .state b{color:var(--blue-d)}
footer .spacer{margin-left:auto}

.toast{
  position:fixed;left:50%;bottom:96px;transform:translateX(-50%) translateY(14px);
  background:#2f5d80;color:#fff;font-size:13px;padding:11px 20px;border-radius:12px;
  opacity:0;pointer-events:none;transition:.25s;z-index:50;box-shadow:0 8px 24px rgba(47,93,128,.3);
}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.chip{display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;background:var(--blue-l);
  color:var(--blue-d);margin-left:6px}
@media (max-width:560px){
  header,main{padding-left:16px;padding-right:16px}
  .legend{flex-direction:column;gap:2px}
}
</style>
</head>
<body>

<header>
  <div class="fish">🐟</div>
  <div>
    <h1>大肥鱼 · 控制台</h1>
    <div class="sub">改完点保存，哨兵 30 秒内读到</div>
  </div>
  <div class="pills">
    <div class="pill"><span class="dot" id="dot-run"></span><span id="txt-run">哨兵未启动</span></div>
    <div class="pill">上次叫醒 <b id="txt-wake">—</b></div>
    <div class="pill">给过 <b id="txt-seen">0</b> 条</div>
  </div>
</header>

<main>

  <section class="card">
    <h2><span class="ic">🎛️</span>开关</h2>
    <p class="hint">关掉哨兵就等于让它下班；下面几个是单项开关。</p>
    <div class="row">
      <div class="lab">哨兵总开关<small>关掉后它不再盯着消息</small></div>
      <label class="sw"><input type="checkbox" data-k="sentinel_enabled"><span></span></label>
    </div>
    <div class="row">
      <div class="lab">自动回复<small>关掉后只看不回</small></div>
      <label class="sw"><input type="checkbox" data-k="auto_reply"><span></span></label>
    </div>
    <div class="row">
      <div class="lab">刷视频<small>到点自己去挑片子</small></div>
      <label class="sw"><input type="checkbox" data-k="scan_enabled"><span></span></label>
    </div>
    <div class="row">
      <div class="lab">私信<small>收发私信</small></div>
      <label class="sw"><input type="checkbox" data-k="dm_enabled"><span></span></label>
    </div>
    <div class="row">
      <div class="lab">夜间静默<small>默认关（你会关电脑）</small></div>
      <label class="sw"><input type="checkbox" data-k="night_quiet"><span></span></label>
    </div>
  </section>

  <section class="card">
    <h2><span class="ic">⏱️</span>节奏</h2>
    <p class="hint">多久看一次、攒够几条才叫、多老的消息不理。</p>
    <div class="row">
      <div class="lab">唤醒周期<small>秒。最低 60，默认 600</small></div>
      <input type="number" min="60" step="30" data-k="wake_interval_seconds">
    </div>
    <div class="row">
      <div class="lab">最少条数门槛<small>没攒够就不叫醒</small></div>
      <input type="number" min="1" max="99" data-k="min_count">
    </div>
    <div class="row">
      <div class="lab">旧消息过期<small>小时。更老的不叫醒（只挡叫醒，不删数据）</small></div>
      <input type="number" min="1" max="720" data-k="max_age_hours">
    </div>
    <div class="row">
      <div class="lab">每小时最多叫醒<small>防止刷屏</small></div>
      <input type="number" min="1" max="60" data-k="caps.hourly_wakes">
    </div>
    <div class="row">
      <div class="lab">夜间静默时段<small>要打开上面的「夜间静默」才生效。跨零点也行（23:00,07:00）</small></div>
      <input type="text" data-k="night_quiet_range" style="width:150px" placeholder="00:00,07:00">
    </div>
  </section>

  <section class="card">
    <h2><span class="ic">💬</span>每种消息怎么办</h2>
    <p class="hint">左边是它拿到什么，右边是它能不能回。</p>
    <div class="legend">
      <span><b>可以</b> 它按人格自己判断</span>
      <span><b>过滤无用</b> 先过一遍垃圾，没用的不动</span>
      <span><b>严禁</b> 一个字都不看</span>
    </div>

    <div class="type-row">
      <div class="tag">@ 我<span class="sub">评论里</span></div>
      <div class="seg" data-k="mode.at">
        <button data-v="0">只看</button><button data-v="1">提一句</button><button data-v="2">给全文</button>
      </div>
      <div class="seg ok" data-k="attitude.at">
        <button data-v="yes">可以</button><button data-v="filter">过滤</button><button data-v="forbid">严禁</button>
      </div>
    </div>

    <div class="type-row">
      <div class="tag">回复<span class="sub">我的评论</span></div>
      <div class="seg" data-k="mode.reply">
        <button data-v="0">只看</button><button data-v="1">提一句</button><button data-v="2">给全文</button>
      </div>
      <div class="seg ok" data-k="attitude.reply">
        <button data-v="yes">可以</button><button data-v="filter">过滤</button><button data-v="forbid">严禁</button>
      </div>
    </div>

    <div class="type-row">
      <div class="tag">私信<span class="sub">一对一</span></div>
      <div class="seg" data-k="mode.dm">
        <button data-v="0">只看</button><button data-v="1">提一句</button><button data-v="2">给全文</button>
      </div>
      <div class="seg ok" data-k="attitude.dm">
        <button data-v="yes">可以</button><button data-v="filter">过滤</button><button data-v="forbid">严禁</button>
      </div>
    </div>
  </section>

  <section class="card">
    <h2><span class="ic">📊</span>今天</h2>
    <p class="hint">它自己记的账，只读。</p>
    <div id="quota-box">
      <div class="kv"><span>回过几个人</span><b id="q-people">—</b></div>
      <div class="bar"><i id="q-people-bar" style="width:0%"></i></div>
      <div class="kv" style="margin-top:10px"><span>发过私信</span><b id="q-dm">—</b></div>
      <div class="bar"><i id="q-dm-bar" style="width:0%"></i></div>
      <div class="kv" style="margin-top:10px"><span>今天刷了</span><b id="q-scan">—</b></div>
      <div class="bar"><i id="q-scan-bar" style="width:0%"></i></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div class="lab">软 / 硬限额<small>软=只提醒你 · 硬=超了就拒绝</small></div>
      <div class="seg" data-k="caps.hard">
        <button data-v="false">软</button><button data-v="true">硬</button>
      </div>
    </div>
    <div class="row">
      <div class="lab">每天回复人数上限</div>
      <input type="number" min="0" max="100" data-k="caps.daily_people">
    </div>
    <div class="row">
      <div class="lab">每视频上限 / 每楼层上限</div>
      <div style="display:flex;gap:8px">
        <input type="number" min="0" max="100" data-k="caps.per_video">
        <input type="number" min="0" max="100" data-k="caps.per_thread">
      </div>
    </div>
    <div class="row">
      <div class="lab">每天私信条数</div>
      <input type="number" min="0" max="100" data-k="caps.daily_dm">
    </div>
  </section>

  <section class="card">
    <h2><span class="ic">🎯</span>刷视频</h2>
    <p class="hint">你不规定它看什么了 —— 它每天自己想几个词、自己去搜。刷过的视频不会再给它。</p>
    <div class="row">
      <div class="lab">一天看几个<small>没看过的</small></div>
      <input type="number" min="1" max="90" data-k="caps.scan_per_day">
    </div>
    <div class="row" style="display:block">
      <div class="lab" style="margin-bottom:8px">它自己的话</div>
      <div class="hint" style="margin:0">关键词、方向、筛选条件，全部由它自己定。你想看它的想法，去翻日记。</div>
    </div>
    <div class="row">
      <div class="lab">主动评论时 @ 你</div>
      <label class="sw"><input type="checkbox" data-k="share.at_on_every_comment"><span class="tr"></span></label>
    </div>
    <div class="row">
      <div class="lab">叫你名字<small>评论里 @ 的那个</small></div>
      <input type="text" data-k="share.master_name" style="width:150px">
    </div>
  </section>

  <section class="card">
    <h2><span class="ic">🕐</span>时间点</h2>
    <p class="hint">刷视频和写日记的时刻，24 小时制，逗号隔开。</p>
    <div class="row" style="display:block">
      <div class="lab" style="margin-bottom:8px">刷视频时间</div>
      <input type="text" data-k="scan_at" placeholder="12:30,21:00">
    </div>
    <div class="row">
      <div class="lab">写日记时间</div>
      <input type="text" data-k="diary_at" style="width:110px">
    </div>
    <div class="row">
      <div class="lab">私信字数上限</div>
      <input type="number" min="50" max="450" step="10" data-k="dm_max_chars">
    </div>
    <div class="row">
      <div class="lab">会话超多少 token 就换新<small>默认 60000</small></div>
      <input type="number" min="8000" step="1000" data-k="session_max_tokens">
    </div>
  </section>

</main>

<footer>
  <div class="state" id="save-state">一切就绪</div>
  <div class="spacer"></div>
  <button class="btn ghost" id="btn-reload">丢弃改动</button>
  <button class="btn primary" id="btn-save">保存</button>
</footer>

<div class="toast" id="toast"></div>

<script>
const $  = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
let CFG = {};
let DIRTY = false;

function toast(msg){
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('show'), 1900);
}
function dirty(on=true){
  if(on === DIRTY) return;
  DIRTY = on;
  $('#save-state').innerHTML = on
    ? '<b style="color:#c47c2e">有改动没保存</b>'
    : '一切就绪';
}
function getPath(obj, path){
  return path.split('.').reduce((o,k)=> (o==null?undefined:o[k]), obj);
}
function setPath(obj, path, v){
  const ks = path.split('.'); const last = ks.pop();
  let o = obj;
  for(const k of ks){ if(typeof o[k] !== 'object' || o[k]===null) o[k]={}; o = o[k]; }
  o[last] = v;
}

/* ---------- 填充 ---------- */
function fill(cfg){
  CFG = cfg;
  // 开关
  $$('.sw input').forEach(inp=>{ inp.checked = !!getPath(cfg, inp.dataset.k); });
  // 数字 / 文本
  $$('input[type=number],input[type=text]').forEach(inp=>{
    const k = inp.dataset.k; if(!k) return;
    const v = getPath(cfg, k);
    if(k === 'scan_at' || k === 'night_quiet_range') inp.value = (v||[]).join(',');
    else if(v === undefined || v === null) inp.value = '';
    else inp.value = v;
  });
  // 分段
  $$('.seg[data-k]').forEach(seg=>{
    const k = seg.dataset.k;
    const v = String(getPath(cfg, k));
    seg.querySelectorAll('button').forEach(b=>{
      b.classList.toggle('sel', b.dataset.v === v);
    });
    paintSeg(seg);
  });
}
function paintSeg(seg){
  if(!seg.dataset.k.startsWith('attitude')) return;
  const v = (seg.querySelector('button.sel')||{}).dataset?.v;
  seg.classList.remove('ok','warn','bad');
  seg.classList.add(v==='forbid' ? 'bad' : v==='filter' ? 'warn' : 'ok');
}

/* ---------- 收集 ---------- */
function collect(){
  const out = {};
  $$('.sw input').forEach(inp=>{ setPath(out, inp.dataset.k, inp.checked); });
  $$('input[type=number]').forEach(inp=>{
    const k = inp.dataset.k; if(!k || !inp.value) return;
    setPath(out, k, Number(inp.value));
  });
  $$('input[type=text]').forEach(inp=>{
    const k = inp.dataset.k; if(!k) return;
    const v = inp.value.trim();
    if(k === 'scan_at' || k === 'night_quiet_range')
      setPath(out, k, v ? v.split(/[,，]/).map(s=>s.trim()).filter(Boolean) : []);
    else                            setPath(out, k, v);
  });
  $$('.seg[data-k]').forEach(seg=>{
    const k = seg.dataset.k;
    const sel = seg.querySelector('button.sel');
    if(!sel) return;
    let v = sel.dataset.v;
    if(v === 'true') v = true;
    else if(v === 'false') v = false;
    else if(/^-?\d+$/.test(v) && !k.startsWith('attitude')) v = Number(v);
    setPath(out, k, v);
  });
  return out;
}

/* ---------- 状态 ---------- */
async function refresh(){
  try{
    const r = await fetch('/api/status'); const s = await r.json();
    $('#dot-run').className = 'dot ' + (s.running ? 'on' : 'off');
    $('#txt-run').textContent = s.running ? ('哨兵在跑 · ' + s.pid) : '哨兵未启动';
    $('#txt-wake').textContent = s.last_wake || '—';
    $('#txt-seen').textContent = s.seen || 0;

    const q = s.quota || {};
    const people = (q.people && Object.keys(q.people).length) || 0;
    const dmN = Number(q.dm || 0) || 0;
    const scanN = Number(s.scan_today || 0) || 0;
    $('#q-people').textContent = people + ' / ' + ((CFG.caps||{}).daily_people ?? '?');
    $('#q-dm').textContent     = dmN + ' / ' + ((CFG.caps||{}).daily_dm ?? '?');
    $('#q-scan').textContent   = scanN + ' / ' + ((CFG.caps||{}).scan_per_day ?? '?');
    const pc = Math.min(100, people * 100 / Math.max(1,(CFG.caps||{}).daily_people || 1));
    const dc = Math.min(100, dmN    * 100 / Math.max(1,(CFG.caps||{}).daily_dm    || 1));
    const sc = Math.min(100, scanN  * 100 / Math.max(1,(CFG.caps||{}).scan_per_day || 1));
    $('#q-people-bar').style.width = pc + '%';
    $('#q-dm-bar').style.width     = dc + '%';
    $('#q-scan-bar').style.width   = sc + '%';
  }catch(e){ /* 静默 */ }
}

/* ---------- 事件 ---------- */
$$('.sw input').forEach(inp=> inp.addEventListener('change', ()=>dirty()));
$$('input[type=number],input[type=text]').forEach(inp=>{
  inp.addEventListener('input', ()=>dirty());
});
$$('.seg[data-k]').forEach(seg=>{
  seg.addEventListener('click', ev=>{
    const b = ev.target.closest('button'); if(!b) return;
    seg.querySelectorAll('button').forEach(x=>x.classList.remove('sel'));
    b.classList.add('sel');
    paintSeg(seg);
    dirty();
  });
});

$('#btn-save').addEventListener('click', async ()=>{
  const body = collect();
  $('#btn-save').disabled = true;
  try{
    const r = await fetch('/api/save', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if(d.ok){
      dirty(false);
      CFG = Object.assign(CFG, body);
      toast('已保存，哨兵 30 秒内读到');
      refresh();
    } else toast('保存失败');
  }catch(e){ toast('保存失败：' + e.message); }
  $('#btn-save').disabled = false;
});

$('#btn-reload').addEventListener('click', async ()=>{
  if(DIRTY && !confirm('丢弃没保存的改动？')) return;
  const r = await fetch('/api/config');
  fill(await r.json());
  dirty(false);
  toast('已回到已保存的版本');
});

async function doWake(args, msg){
  await fetch('/api/wake', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({args: args || []})
  });
  toast(msg || '叫醒了，去弹出的窗口看');
  setTimeout(refresh, 1500);
}

document.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key === 's'){ e.preventDefault(); $('#btn-save').click(); }
});
window.addEventListener('beforeunload', e=>{
  if(DIRTY){ e.preventDefault(); e.returnValue = ''; }
});

/* ---------- 启动 ---------- */
(async ()=>{
  const r = await fetch('/api/config');
  fill(await r.json());
  refresh();
  setInterval(refresh, 8000);
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 入口

def already_running(port):
    """已经有一个控制台在跑了？避免双击两次开两个服务。"""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.2) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
            return "running" in d
    except Exception:
        return False


def serve(port=8765, open_browser=True):
    if not os.path.exists(CFG):
        print("找不到 config.json：", CFG)
        return 1

    url = f"http://127.0.0.1:{port}/"
    if already_running(port):
        print("控制台已经开着了，直接开浏览器：", url)
        if open_browser:
            webbrowser.open(url)
        return 0

    httpd = None
    for p in range(port, port + 30):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("端口都被占了，起不了。")
        return 1

    url = f"http://127.0.0.1:{port}/"
    print("=" * 50)
    print("  大肥鱼 · 控制台")
    print("  " + url)
    print("  关掉这个窗口 = 关掉控制台（不影响哨兵）")
    print("=" * 50)

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭。")
    return 0


def main():
    port, do_open = 8765, True
    args = sys.argv[1:]
    if "--no-open" in args:
        do_open = False
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except Exception:
            pass
    return serve(port, do_open)


if __name__ == "__main__":
    sys.exit(main())
