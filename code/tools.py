#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大肥鱼的工具箱 —— 27 个工具，AI 的手

AI 只有通过这里的工具才能碰到 B站。
硬闸全部在这里：严禁、限额、草稿拒发、字数上限。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

CODE = os.path.dirname(os.path.abspath(__file__))       # code\
ROOT = os.path.dirname(CODE)                            # 大肥鱼\
MEM = os.path.join(ROOT, "memory")
INBOX = os.path.join(ROOT, "inbox")
CONFIG_FILE = os.path.join(ROOT, "config.json")

# 票据只从工作区的 credential\ 里读 —— 不依赖任何外部目录，文件夹搬到哪都跟着走
DEFAULT_CRED = os.path.join(ROOT, "credential", "bili_credential.json")

# ---------------------------------------------------------------- 基础设施


def load_cfg() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _p(*parts) -> str:
    return os.path.join(MEM, *parts)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _cred():
    from bilibili_api import Credential

    cfg = load_cfg()
    path = cfg.get("credential_file") or DEFAULT_CRED
    d = _read_json(path, None)
    if not d:
        raise RuntimeError(f"读不到凭证文件：{path}")
    return Credential(
        sessdata=d.get("sessdata"),
        bili_jct=d.get("bili_jct"),
        buvid3=d.get("buvid3"),
        dedeuserid=d.get("dedeuserid"),
    )


def _self_uid() -> int:
    cfg = load_cfg()
    path = cfg.get("credential_file") or DEFAULT_CRED
    d = _read_json(path, {})
    return int(d.get("dedeuserid") or 0)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _cookie_headers(cred) -> dict:
    return {
        "User-Agent": _UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Cookie": f"SESSDATA={cred.sessdata}; buvid3={cred.buvid3}",
    }


def _check_text(text: str, limit: int = 1000, label: str = "评论") -> str:
    """发布前的统一检查：不能空、不能是草稿、不能超长。"""
    body = (text or "").strip()
    if not body:
        raise RuntimeError("空内容不发。")
    if body.startswith("[草稿]"):
        raise RuntimeError("这是草稿，不能发出去。")
    if len(body) > limit:
        raise RuntimeError(f"太长了，{label}上限 {limit} 字。")
    return body


# ---------------------------------------------------------------- 配额（号主定义，程序记账）


def _quota_path():
    return _p("quota.json")


def _quota():
    q = _read_json(_quota_path(), {})
    if q.get("day") != _today():
        q = {"day": _today(), "people": {}, "videos": {}, "threads": {}, "dm": 0}
        _write_json(_quota_path(), q)
    return q


def quota_state() -> dict:
    q = _quota()
    cfg = load_cfg()
    caps = cfg.get("caps") or {}
    return {
        "daily_people_used": len(q.get("people") or {}),
        "daily_people_cap": caps.get("daily_people", 5),
        "per_video_cap": caps.get("per_video", 5),
        "per_thread_cap": caps.get("per_thread", 3),
        "dm_used": q.get("dm", 0),
        "dm_cap": caps.get("daily_dm", 5),
        "hard": bool(caps.get("hard", False)),
    }


def _cap_check(kind: str, key: str) -> str:
    """返回警告文本；hard 模式下抛异常。"""
    cfg = load_cfg()
    caps = cfg.get("caps") or {}
    q = _quota()
    hard = bool(caps.get("hard", False))
    msg = ""

    if kind == "people":
        used = len(q.get("people") or {})
        cap = caps.get("daily_people", 5)
        if used >= cap:
            msg = f"今天已经回过 {used} 个人，上限 {cap}（{'硬' if hard else '软'}上限）"
            if hard:
                raise RuntimeError("达到每日回人数上限：" + msg)
    elif kind == "video":
        n = len((q.get("videos") or {}).get(str(key), []))
        cap = caps.get("per_video", 5)
        if n >= cap:
            msg = f"这个视频已经回过 {n} 条，上限 {cap}"
            if hard:
                raise RuntimeError(msg)
    elif kind == "thread":
        n = len((q.get("threads") or {}).get(str(key), []))
        cap = caps.get("per_thread", 3)
        if n >= cap:
            msg = f"这个楼层已经回过 {n} 条，上限 {cap}"
            if hard:
                raise RuntimeError(msg)
    return ("\n\n【提醒】" + msg + "。你可以自己决定还要不要继续，但号主设定的额度已经用满了。") if msg else ""


def _cap_bump(kind: str, uid: int, key: str):
    q = _quota()
    if kind == "people":
        q.setdefault("people", {})[str(uid)] = int(q.setdefault("people", {}).get(str(uid), 0)) + 1
    elif kind == "video":
        q.setdefault("videos", {}).setdefault(str(key), []).append(int(time.time()))
    elif kind == "thread":
        q.setdefault("threads", {}).setdefault(str(key), []).append(int(time.time()))
    elif kind == "dm":
        q["dm"] = int(q.get("dm", 0)) + 1
    _write_json(_quota_path(), q)


# ---------------------------------------------------------------- 态度闸


def _attitude(kind: str) -> str:
    cfg = load_cfg()
    a = (cfg.get("attitude") or {}).get(kind, "yes")
    return a if a in ("yes", "filter", "forbid") else "yes"


def _forbid_dm():
    if _attitude("dm") == "forbid":
        raise RuntimeError("号主在界面里把私信设成了「严禁」。你不能读、不能发，也不要绕路。")


# ---------------------------------------------------------------- 消息解析


def _mention_text(it: dict) -> str:
    inner = it.get("item") or {}
    for k in ("source_content", "content", "target_reply_content", "root_reply_content", "title"):
        v = it.get(k) or inner.get(k)
        if v:
            return _clean(str(v))
    return ""


def _parse_notice(it: dict, kind: str) -> dict:
    inner = it.get("item") or {}
    src = int(inner.get("source_id") or 0) or int(it.get("id") or 0)
    if kind == "at":
        # @ 我 的那条评论本身是 source_id；target_id 是被回复的楼层根
        parent = int(inner.get("target_id") or 0) or src
        root = parent
    else:
        # 回复我 的那条是 source_id；root_id 是楼层根
        parent = src
        root = int(inner.get("root_id") or 0) or src
    user = it.get("user") or {}
    return {
        "kind": kind,
        "rpid": src,
        "notify_id": int(it.get("id") or 0),
        "oid": int(inner.get("subject_id") or 0),
        "root": root,
        "parent": parent,
        "from_uid": int(user.get("mid") or 0),
        "from_name": user.get("nickname") or "",
        "text": _mention_text(it),
        "uri": it.get("uri") or inner.get("uri") or "",
        "at": int(it.get("at_time") or it.get("reply_time") or it.get("at") or 0),
        "business_id": inner.get("business_id") or it.get("business_id") or 1,
    }


async def _fetch_at(cred):
    from bilibili_api import session

    try:
        r = await session.get_at(credential=cred)
    except Exception:
        return []
    return [_parse_notice(it, "at") for it in (r.get("items") or [])]


async def _fetch_replies(cred):
    from bilibili_api import session

    try:
        r = await session.get_replies(credential=cred)
    except Exception:
        return []
    return [_parse_notice(it, "reply") for it in (r.get("items") or [])]


async def _thread_json(oid: int, rpid: int, ps: int = 20, pn: int = 1) -> dict:
    """拉一楼的原始数据：楼层根评论 + 这楼的回复（root 传楼层根或楼内任意一条都行，B 站会解析）。"""
    if not oid or not rpid:
        return {}
    import aiohttp

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.bilibili.com/x/v2/reply/reply",
                params={"type": 1, "oid": int(oid), "root": int(rpid), "ps": int(ps), "pn": int(pn)},
                headers=_cookie_headers(_cred()),
            ) as r:
                body = await r.json(content_type=None)
    except Exception:
        return {}
    return (body.get("data") or {}) if body.get("code") == 0 else {}


def _reply_row(c: dict, oid: int) -> dict:
    member = c.get("member") or {}
    return {
        "rpid": int(c.get("rpid") or 0),
        "oid": int(oid),
        "root": int(c.get("root") or 0),
        "parent": int(c.get("parent") or 0),
        "user": member.get("uname") or "",
        "mid": int(member.get("mid") or 0),
        "content": _clean((c.get("content") or {}).get("message") or ""),
        "ctime": c.get("ctime") or 0,
    }


async def tool_get_comment(oid: int, rpid: int) -> str:
    """查一条评论：它自己的内容，以及它所在楼层的根（楼主）是谁。"""
    if not int(oid) or not int(rpid):
        raise RuntimeError("要 oid 和 rpid。")
    data = await _thread_json(int(oid), int(rpid), ps=20)
    root = data.get("root") or {}
    target = None
    if int(root.get("rpid") or 0) == int(rpid):
        target = root
    else:
        for c in data.get("replies") or []:
            if int(c.get("rpid") or 0) == int(rpid):
                target = c
                break
    out = {
        "found": bool(target),
        "target": _reply_row(target, int(oid)) if target else None,
        "floor": _reply_row(root, int(oid)) if root else None,
        "floor_is_target": bool(target and root and int(root.get("rpid") or 0) == int(rpid)),
    }
    if not target:
        out["hint"] = "这条查不到（可能已删/被折叠），或它不是评论区评论。"
    return json.dumps(out, ensure_ascii=False)


async def tool_list_thread(oid: int, root: int, pn: int = 1, ps: int = 20) -> str:
    """看一整楼：楼层根评论 + 这楼的回复，可翻页。"""
    if not int(oid) or not int(root):
        raise RuntimeError("要 oid 和 root（楼层根 rpid）。")
    data = await _thread_json(int(oid), int(root), ps=max(1, min(50, int(ps or 20))), pn=max(1, int(pn or 1)))
    r = data.get("root") or {}
    replies = data.get("replies") or []
    out = {
        "oid": int(oid),
        "root": _reply_row(r, int(oid)) if r else None,
        "replies": [_reply_row(c, int(oid)) for c in replies],
        "page": data.get("page") or {},
    }
    return json.dumps(out, ensure_ascii=False)


def _filter_by_attitude(items, kind):
    if _attitude(kind) == "forbid":
        return []
    return items


# ---------------------------------------------------------------- 工具实现


async def tool_list_mentions(limit: int = 20, kinds: str = "at,reply") -> str:
    cred = _cred()
    want = {k.strip() for k in (kinds or "at,reply").split(",") if k.strip()}
    out = []
    if "at" in want:
        out += _filter_by_attitude(await _fetch_at(cred), "at")
    if "reply" in want:
        out += _filter_by_attitude(await _fetch_replies(cred), "reply")
    me = _self_uid()
    out = [m for m in out if m["from_uid"] != me]
    out.sort(key=lambda m: -(m.get("at") or 0))
    out = out[:limit]
    if not out:
        return "没有新消息。"
    lines = []
    for m in out:
        lines.append(
            json.dumps(
                {
                    "kind": m["kind"],
                    "rpid": m["rpid"],
                    "oid": m["oid"],
                    "root": m["root"],
                    "parent": m["parent"],
                    "from_uid": m["from_uid"],
                    "from_name": m["from_name"],
                    "text": m["text"],
                    "uri": m["uri"],
                    "at": m["at"],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


async def tool_read_video(bvid: str = "", oid: int = 0) -> str:
    cred = _cred()
    from bilibili_api import video as bvideo, comment as bcomment

    if not bvid and oid:
        # 从 aid 反查 bvid
        v = bvideo.Video(aid=int(oid), credential=cred)
    elif bvid:
        v = bvideo.Video(bvid=bvid, credential=cred)
    else:
        raise RuntimeError("要么给 bvid，要么给 oid")
    info = await v.get_info()
    sub_text = ""
    try:
        cid = (info.get("pages") or [{}])[0].get("cid")
        if cid:
            sub = await v.get_subtitle(cid=cid)
            subs = (sub or {}).get("subtitles") or []
            if subs:
                import urllib.request

                url = subs[0].get("subtitle_url") or ""
                if url.startswith("//"):
                    url = "https:" + url
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": f"https://www.bilibili.com/video/{info.get('bvid')}",
                    },
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                sub_text = " ".join(
                    (x.get("content") or "") for x in (body.get("body") or [])
                )[:1500]
    except Exception as e:
        sub_text = f"（字幕没取到：{type(e).__name__}）"

    hot = []
    try:
        cm = await bcomment.get_comments(
            int(info.get("aid")),
            bcomment.CommentResourceType.VIDEO,
            page_index=1,
            order=bcomment.OrderType.LIKE,
            credential=cred,
        )
        for c in (cm.get("replies") or [])[:3]:
            hot.append(_clean(c.get("content", {}).get("message", ""))[:80])
    except Exception:
        pass

    parts = [
        f"oid：{info.get('aid')}",
        f"bvid：{info.get('bvid')}",
        f"标题：{info.get('title')}",
        f"UP：{(info.get('owner') or {}).get('name')}",
        f"时长：{info.get('duration')} 秒",
        f"分区：{info.get('tname')}",
        f"播放：{(info.get('stat') or {}).get('view')}",
        f"简介：{_clean((info.get('desc') or ''))[:300]}",
    ]
    if sub_text:
        parts.append(f"字幕摘录：{sub_text}")
    if hot:
        parts.append("热门评论：" + " / ".join(hot))
    _mark_seen_video(info.get("bvid") or "")
    return "\n".join(parts)


def _mark_seen_video(bvid: str):
    """看过的视频自动进 seen_videos，search_videos 以后就不再给你了。"""
    if not bvid:
        return
    try:
        seen = _read_json(_p("seen_videos.json"), {})
        if bvid not in seen:
            seen[bvid] = {"ts": int(time.time()), "verdict": "", "note": ""}
            _write_json(_p("seen_videos.json"), seen)
    except Exception:
        pass


async def tool_post_reply(text: str, oid: int, rpid: int = 0, root: int = 0, to_uid: int = 0) -> str:
    cfg = load_cfg()
    if not cfg.get("auto_reply", True):
        raise RuntimeError("号主关掉了「自动回复」，现在只能看不能发。")
    text = _check_text(text)

    warn = _cap_check("people", str(to_uid or 0))
    warn += _cap_check("video", str(oid))
    warn += _cap_check("thread", str(root or rpid))

    cred = _cred()
    from bilibili_api import comment as bcomment

    parent = int(rpid or 0)
    rt = int(root or 0) or parent
    res = await bcomment.send_comment(
        text=text,
        oid=int(oid),
        type_=bcomment.CommentResourceType.VIDEO,
        root=rt if rt else None,
        parent=parent if parent else None,
        credential=cred,
    )
    new_rpid = ((res or {}).get("rpid") or (res or {}).get("data", {}).get("rpid") or 0)
    _cap_bump("people", int(to_uid or 0), "")
    _cap_bump("video", 0, str(oid))
    _cap_bump("thread", 0, str(root or rpid))
    out = {"sent": True, "rpid": new_rpid, "toast": (res or {}).get("success_toast") or "已发送"}
    return json.dumps(out, ensure_ascii=False) + (("\n" + warn) if warn else "")


async def tool_watch_video(bvid: str = "", verdict: str = "", note: str = "") -> str:
    """记下你看过这个视频、你的看法。verdict 用 like / meh / skip。"""
    if not bvid:
        raise RuntimeError("要给我 bvid。")
    seen = _read_json(_p("seen_videos.json"), {})
    old = seen.get(bvid) or {}
    seen[bvid] = {
        "ts": int(old.get("ts") or time.time()),
        "verdict": (verdict or old.get("verdict") or "")[:20],
        "note": (note or "")[:300],
    }
    _write_json(_p("seen_videos.json"), seen)
    return json.dumps(
        {"ok": True, "watched": bvid, "verdict": seen[bvid]["verdict"], "total": len(seen)},
        ensure_ascii=False,
    )


async def tool_comment_video(text: str = "", oid: int = 0, bvid: str = "", at_master: bool = True) -> str:
    """在视频下发一条主评论（不是回复某个人）。默认会在正文前面加上 @ 加昵称。"""
    cfg = load_cfg()
    if not cfg.get("auto_reply", True):
        raise RuntimeError("号主关掉了「自动回复」，现在只能看不能发。")
    body = _check_text(text)

    if not int(oid) and bvid:
        from bilibili_api import video as bvideo

        info = await bvideo.Video(bvid=bvid, credential=_cred()).get_info()
        oid = int(info.get("aid") or 0)
    if not int(oid):
        raise RuntimeError("要么给 oid，要么给 bvid。")

    sh = cfg.get("share") or {}
    if at_master and sh.get("at_on_every_comment", True):
        name = str(sh.get("master_name") or "").strip()
        if name and not body.startswith("@" + name):
            body = f"@{name} {body}"

    if len(body) > 1000:
        raise RuntimeError("太长了，评论上限 1000 字。")

    warn = _cap_check("video", str(oid))
    cred = _cred()
    from bilibili_api import comment as bcomment

    res = await bcomment.send_comment(
        text=body,
        oid=int(oid),
        type_=bcomment.CommentResourceType.VIDEO,
        credential=cred,
    )
    new_rpid = ((res or {}).get("rpid") or (res or {}).get("data", {}).get("rpid") or 0)
    _cap_bump("video", 0, str(oid))
    out = {
        "sent": True,
        "rpid": new_rpid,
        "toast": (res or {}).get("success_toast") or "已发送",
        "text": body[:80],
    }
    return json.dumps(out, ensure_ascii=False) + (("\n" + warn) if warn else "")


async def tool_list_dms() -> str:
    _forbid_dm()
    from bilibili_api import session

    cred = _cred()
    r = await session.get_sessions(credential=cred, session_type=1)
    rows = []
    for s in (r.get("session_list") or []):
        uid = s.get("talker_id")
        if not uid:
            continue
        rows.append(
            {
                "uid": uid,
                "name": s.get("name") or "",
                "unread": s.get("unread_count") or 0,
                "ts": s.get("timestamp") or 0,
                "type": s.get("last_msg", {}).get("msg_type") if isinstance(s.get("last_msg"), dict) else None,
            }
        )
    if not rows:
        return "没有私信会话。"
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in rows)


async def tool_read_dm(uid: int, limit: int = 20) -> str:
    _forbid_dm()
    if _attitude("dm") == "forbid":
        raise RuntimeError("严禁私信。")
    from bilibili_api import session

    cred = _cred()
    r = await session.fetch_session_msgs(credential=cred, talker_id=int(uid), session_type=1)
    msgs = (r.get("messages") or [])[:limit]
    if not msgs:
        return "这个会话没有消息（也可能是系统号）。"
    out = []
    for m in reversed(msgs):
        try:
            c = m.get("content") or ""
            try:
                c = json.loads(c).get("content", c)
            except Exception:
                pass
            who = "我" if int(m.get("sender_uid") or 0) == _self_uid() else str(uid)
            out.append(f'{who}: {str(c)[:300]}')
        except Exception:
            continue
    return "\n".join(out)


async def tool_send_dm(uid: int, text: str) -> str:
    _forbid_dm()
    cfg = load_cfg()
    if not cfg.get("dm_enabled", True):
        raise RuntimeError("号主关掉了「私信」开关。")
    limit = int(cfg.get("dm_max_chars") or 450)
    text = (text or "").strip()
    if not text:
        raise RuntimeError("空私信不发。")
    if len(text) > limit:
        raise RuntimeError(f"私信最多 {limit} 字，你写了 {len(text)} 字，精简一下。")
    warn = _cap_check("dm", str(uid))
    cred = _cred()
    from bilibili_api import session as bsession

    res = await bsession.send_msg(
        credential=cred,
        receiver_id=int(uid),
        msg_type=bsession.EventType.TEXT,
        content=text,
    )
    _cap_bump("dm", 0, "")
    return json.dumps({"sent": True, "msg_key": (res or {}).get("msg_key")}, ensure_ascii=False) + (
        ("\n" + warn) if warn else ""
    )


async def tool_search_videos(keyword: str, order: str = "pubdate", min_play: int = 0, days: int = 7) -> str:
    cred = _cred()
    from bilibili_api import search as bsearch

    o = {
        "pubdate": bsearch.OrderVideo.PUBDATE,
        "click": bsearch.OrderVideo.CLICK,
    }.get((order or "pubdate").lower(), bsearch.OrderVideo.PUBDATE)

    seen = _read_json(_p("seen_videos.json"), {})
    res = await bsearch.search_by_type(
        keyword=keyword,
        search_type=bsearch.SearchObjectType.VIDEO,
        order_type=o,
        page=1,
    )
    now = int(time.time())
    out = []
    for it in (res.get("result") or []):
        bv = it.get("bvid")
        if not bv:
            continue
        if bv in seen:
            continue
        play = int(it.get("play") or 0)
        if play < int(min_play or 0):
            continue
        pub = int(it.get("pubdate") or 0)
        if days and pub and now - pub > int(days) * 86400:
            continue
        out.append(
            json.dumps(
                {
                    "bvid": bv,
                    "title": _clean(it.get("title") or ""),
                    "up": it.get("author"),
                    "play": play,
                    "duration": it.get("duration"),
                    "pubdate": time.strftime("%m-%d", time.localtime(pub)) if pub else "",
                    "desc": _clean(it.get("description") or "")[:150],
                },
                ensure_ascii=False,
            )
        )
    if not out:
        return "这个关键词下没有合适的（可能都刷过了）。"
    return "\n".join(out[:30])


# ---------------------------------------------------------------- 视频互动（点赞/投币/收藏/看主页）


def _video(bvid: str, oid: int):
    from bilibili_api import video as bvideo

    cred = _cred()
    if bvid:
        return bvideo.Video(bvid=bvid, credential=cred)
    if oid:
        return bvideo.Video(aid=int(oid), credential=cred)
    raise RuntimeError("要给我 bvid 或 oid 中的一个。")


async def _fav_api(path: str, params: dict = None, form: dict = None):
    """收藏夹的增删列表 —— bilibili_api 没封装，直接调接口。"""
    import aiohttp

    cred = _cred()
    headers = _cookie_headers(cred)
    data = None
    if form is not None:
        data = dict(form)
        data["csrf"] = cred.bili_jct
    async with aiohttp.ClientSession() as http:
        async with http.request(
            "GET" if form is None else "POST",
            "https://api.bilibili.com" + path,
            params=params,
            data=data,
            headers=headers,
        ) as r:
            try:
                body = await r.json(content_type=None)
            except Exception:
                raise RuntimeError(f"接口返回不是 JSON（HTTP {r.status}）")
    if body.get("code") != 0:
        raise RuntimeError(f"B 站说：{body.get('message') or body.get('code')}")
    return body.get("data")


async def tool_like_video(bvid: str = "", oid: int = 0, undo: bool = False) -> str:
    v = _video(bvid, oid)
    res = await v.like(status=not undo)
    return json.dumps({"bvid": bvid or None, "aid": int(oid) or None, "liked": not undo, "res": res}, ensure_ascii=False)


async def tool_coin_video(bvid: str = "", oid: int = 0, num: int = 1, also_like: bool = False) -> str:
    v = _video(bvid, oid)
    num = max(1, min(2, int(num or 1)))
    res = await v.pay_coin(num=num, like=bool(also_like))
    return json.dumps(
        {"bvid": bvid or None, "aid": int(oid) or None, "coins": num, "also_like": bool(also_like), "res": res},
        ensure_ascii=False,
    )


async def tool_list_fav_folders() -> str:
    data = await _fav_api("/x/v3/fav/folder/created/list-all", {"up_mid": _self_uid()})
    lst = data.get("list") if isinstance(data, dict) else data
    rows = []
    for it in lst or []:
        rows.append(
            {
                "media_id": it.get("id"),
                "title": it.get("title"),
                "count": it.get("media_count"),
                "privacy": it.get("attr"),
            }
        )
    return json.dumps({"folders": rows}, ensure_ascii=False) if rows else "还没有收藏夹。"


async def tool_list_fav_medias(media_id: int, page: int = 1) -> str:
    from bilibili_api import favorite_list

    fl = favorite_list.FavoriteList(media_id=int(media_id), credential=_cred())
    data = await fl.get_content(page=max(1, int(page or 1)))
    rows = []
    for m in (data or {}).get("medias") or []:
        rows.append(
            {
                "bvid": m.get("bvid") or "",
                "title": _clean(m.get("title") or ""),
                "up": (m.get("upper") or {}).get("name"),
                "fav_time": m.get("fav_time"),
            }
        )
    return json.dumps(
        {"media_id": int(media_id), "has_more": (data or {}).get("has_more"), "medias": rows},
        ensure_ascii=False,
    )


async def tool_create_fav_folder(title: str, privacy: int = 0) -> str:
    info = await _fav_api("/x/v3/fav/folder/add", form={"title": title, "privacy": int(privacy), "intro": ""})
    return json.dumps({"media_id": (info or {}).get("id"), "title": title}, ensure_ascii=False)


async def tool_delete_fav_folder(media_id: int) -> str:
    await _fav_api("/x/v3/fav/folder/del", form={"media_ids": str(int(media_id))})
    return json.dumps({"deleted_media_id": int(media_id)}, ensure_ascii=False)


async def tool_favorite_video(bvid: str = "", oid: int = 0, folder_id: int = 0, undo: bool = False) -> str:
    if not folder_id:
        raise RuntimeError("要给我 folder_id（收藏夹编号，先用 list_fav_folders 查）。")
    v = _video(bvid, oid)
    res = await v.set_favorite(
        add_media_ids=[] if undo else [int(folder_id)],
        del_media_ids=[int(folder_id)] if undo else [],
    )
    return json.dumps(
        {"bvid": bvid or None, "aid": int(oid) or None, "folder_id": int(folder_id), "added": not undo, "res": res},
        ensure_ascii=False,
    )


async def _user_stat(uid: int) -> dict:
    """粉丝数这类统计 —— bilibili_api 没封装，直接调。"""
    import aiohttp

    async with aiohttp.ClientSession() as http:
        async with http.get(
            "https://api.bilibili.com/x/relation/stat",
            params={"vmid": int(uid)},
            headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"},
        ) as r:
            body = await r.json(content_type=None)
    return (body.get("data") or {}) if body.get("code") == 0 else {}


async def tool_view_user(uid: int, limit: int = 20) -> str:
    from bilibili_api import user as buser

    u = buser.User(int(uid), credential=_cred())
    info = await u.get_user_info()
    try:
        stat = await _user_stat(int(uid))
    except Exception:
        stat = {}
    try:
        vids = await u.get_videos(pn=1, ps=max(1, min(30, int(limit or 20))))
        vlist = ((vids or {}).get("list") or {}).get("vlist") or []
    except Exception:
        vlist = []
    rows = []
    for it in vlist:
        rows.append(
            {
                "bvid": it.get("bvid"),
                "title": _clean(it.get("title") or ""),
                "play": it.get("play"),
                "created": it.get("created"),
            }
        )
    return json.dumps(
        {
            "uid": int(uid),
            "name": info.get("name"),
            "sign": info.get("sign"),
            "level": info.get("level"),
            "videos": rows,
            "fans": int(stat.get("follower") or 0) or None,
        },
        ensure_ascii=False,
    )


def tool_read_diary(date: str = "") -> str:
    date = date or _today()
    p = _p("diary", f"{date}.md")
    if not os.path.exists(p):
        return f"{date} 还没有日记。"
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def tool_write_diary(md: str, date: str = "") -> str:
    date = date or _today()
    d = _p("diary")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{date}.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(md or "")
    return f"日记已写入 {p}"


def tool_remember(text: str) -> str:
    p = _p("longterm.md")
    os.makedirs(MEM, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"\n- [{stamp}] {text.strip()}\n")
    return "记住了。"


def tool_peek_inbox() -> str:
    if not os.path.isdir(INBOX):
        return "没有任务包。"
    files = sorted(
        [x for x in os.listdir(INBOX) if x.endswith(".json")],
        key=lambda x: -os.path.getmtime(os.path.join(INBOX, x)),
    )
    if not files:
        return "没有任务包。"
    with open(os.path.join(INBOX, files[0]), "r", encoding="utf-8") as f:
        return f.read()


def tool_get_policy() -> str:
    cfg = load_cfg()
    view = {
        "唤醒周期(秒)": cfg.get("wake_interval_seconds"),
        "最少条数": cfg.get("min_count"),
        "模式": cfg.get("mode"),
        "态度": cfg.get("attitude"),
        "限额": cfg.get("caps"),
        "配额已用": quota_state(),
        "刷视频": cfg.get("scan"),
        "私信上限字数": cfg.get("dm_max_chars"),
    }
    return json.dumps(view, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 动态


async def tool_send_dynamic(text: str = "") -> str:
    """发一条动态。正文自己写，想什么时候发就什么时候发。"""
    body = _check_text(text, 2000, "动态")
    from bilibili_api import dynamic as bdynamic

    cred = _cred()
    res = await bdynamic.send_dynamic(bdynamic.BuildDynamic.create_by_args(text=body), cred)
    res = res or {}
    dyn_id_str = str(res.get("dyn_id_str") or res.get("dyn_id") or "")
    return json.dumps(
        {
            "sent": True,
            "dyn_id": int(res.get("dyn_id") or 0) or None,
            "dyn_id_str": dyn_id_str,
            "url": res.get("share_url") or (f"https://t.bilibili.com/{dyn_id_str}" if dyn_id_str else ""),
            "raw": res,
        },
        ensure_ascii=False,
    )


async def tool_delete_dynamic(dyn_id: int = 0) -> str:
    """删掉自己的一条动态。dyn_id 就是发动态时返回的那个。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id。")
    from bilibili_api import dynamic as bdynamic

    cred = _cred()
    res = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).delete()
    return json.dumps({"deleted": True, "dyn_id": int(dyn_id), "raw": res}, ensure_ascii=False)


async def tool_delete_comment(oid: int = 0, rpid: int = 0) -> str:
    """删掉自己在视频下发的一条评论。只能删自己的，删别人的会被 B 站拒绝。"""
    if not int(oid) or not int(rpid):
        raise RuntimeError("要给我 oid 和 rpid。")
    from bilibili_api import comment as bcomment

    cred = _cred()
    res = await bcomment.Comment(
        oid=int(oid), type_=bcomment.CommentResourceType.VIDEO, rpid=int(rpid), credential=cred
    ).delete()
    return json.dumps({"deleted": True, "oid": int(oid), "rpid": int(rpid), "raw": res}, ensure_ascii=False)


# ---------------------------------------------------------------- 工具表

TOOLS = [
    ("peek_inbox", "读哨兵留给你的任务包（醒来第一件事）", {"type": "object", "properties": {}}, lambda a: tool_peek_inbox()),
    (
        "get_policy",
        "看号主现在的全部设定和额度用掉多少",
        {"type": "object", "properties": {}},
        lambda a: tool_get_policy(),
    ),
    (
        "list_mentions",
        "列 @ 我 和 回复我 的消息",
        {"type": "object", "properties": {"limit": {"type": "integer"}, "kinds": {"type": "string"}}},
        lambda a: tool_list_mentions(int(a.get("limit") or 20), a.get("kinds") or "at,reply"),
    ),
    (
        "get_comment",
        "查一条评论（给 oid + rpid）：内容、parent、root，以及楼层根是谁",
        {"type": "object", "properties": {"oid": {"type": "integer"}, "rpid": {"type": "integer"}}, "required": ["oid", "rpid"]},
        lambda a: tool_get_comment(int(a.get("oid") or 0), int(a.get("rpid") or 0)),
    ),
    (
        "list_thread",
        "看一整楼（给 oid + root）：楼层根评论 + 这楼的回复，可翻页",
        {
            "type": "object",
            "properties": {"oid": {"type": "integer"}, "root": {"type": "integer"}, "pn": {"type": "integer"}, "ps": {"type": "integer"}},
            "required": ["oid", "root"],
        },
        lambda a: tool_list_thread(int(a.get("oid") or 0), int(a.get("root") or 0), int(a.get("pn") or 1), int(a.get("ps") or 20)),
    ),
    (
        "read_video",
        "读一个视频：标题/UP/简介/字幕/热门评论",
        {"type": "object", "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}}},
        lambda a: tool_read_video(a.get("bvid") or "", int(a.get("oid") or 0)),
    ),
    (
        "post_reply",
        "在视频评论区发一条回复",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "oid": {"type": "integer"},
                "rpid": {"type": "integer"},
                "root": {"type": "integer"},
                "to_uid": {"type": "integer"},
            },
            "required": ["text", "oid"],
        },
        lambda a: tool_post_reply(
            a.get("text") or "", int(a.get("oid") or 0), int(a.get("rpid") or 0), int(a.get("root") or 0), int(a.get("to_uid") or 0)
        ),
    ),
    (
        "watch_video",
        "记下你看过这个视频、你的看法（like/meh/skip），以后不再重复给你",
        {
            "type": "object",
            "properties": {
                "bvid": {"type": "string"},
                "verdict": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["bvid"],
        },
        lambda a: tool_watch_video(a.get("bvid") or "", a.get("verdict") or "", a.get("note") or ""),
    ),
    (
        "comment_video",
        "在视频下发一条自己的评论（默认会自动带上 @ 加昵称）",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "oid": {"type": "integer"},
                "bvid": {"type": "string"},
                "at_master": {"type": "boolean"},
            },
            "required": ["text"],
        },
        lambda a: tool_comment_video(
            a.get("text") or "", int(a.get("oid") or 0), a.get("bvid") or "", bool(a.get("at_master", True))
        ),
    ),
    ("list_dms", "列私信会话", {"type": "object", "properties": {}}, lambda a: tool_list_dms()),
    (
        "read_dm",
        "读某个人的私信",
        {"type": "object", "properties": {"uid": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["uid"]},
        lambda a: tool_read_dm(int(a.get("uid") or 0), int(a.get("limit") or 20)),
    ),
    (
        "send_dm",
        "给某个人发私信",
        {"type": "object", "properties": {"uid": {"type": "integer"}, "text": {"type": "string"}}, "required": ["uid", "text"]},
        lambda a: tool_send_dm(int(a.get("uid") or 0), a.get("text") or ""),
    ),
    (
        "search_videos",
        "搜视频（已经过滤掉刷过的）",
        {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "order": {"type": "string"},
                "min_play": {"type": "integer"},
                "days": {"type": "integer"},
            },
            "required": ["keyword"],
        },
        lambda a: tool_search_videos(
            a.get("keyword") or "", a.get("order") or "pubdate", int(a.get("min_play") or 0), int(a.get("days") or 7)
        ),
    ),
    ("read_diary", "读某天的日记", {"type": "object", "properties": {"date": {"type": "string"}}}, lambda a: tool_read_diary(a.get("date") or "")),
    (
        "write_diary",
        "写某天的日记",
        {"type": "object", "properties": {"md": {"type": "string"}, "date": {"type": "string"}}, "required": ["md"]},
        lambda a: tool_write_diary(a.get("md") or "", a.get("date") or ""),
    ),
    ("remember", "往长期记忆追加一条", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, lambda a: tool_remember(a.get("text") or "")),
    (
        "like_video",
        "给视频点赞，或取消点赞",
        {
            "type": "object",
            "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}, "undo": {"type": "boolean"}},
        },
        lambda a: tool_like_video(a.get("bvid") or "", int(a.get("oid") or 0), bool(a.get("undo"))),
    ),
    (
        "coin_video",
        "给视频投币（1~2 枚），可同时点赞",
        {
            "type": "object",
            "properties": {
                "bvid": {"type": "string"},
                "oid": {"type": "integer"},
                "num": {"type": "integer"},
                "also_like": {"type": "boolean"},
            },
        },
        lambda a: tool_coin_video(
            a.get("bvid") or "", int(a.get("oid") or 0), int(a.get("num") or 1), bool(a.get("also_like"))
        ),
    ),
    (
        "list_fav_folders",
        "列出自己的收藏夹（拿 folder_id）",
        {"type": "object", "properties": {}},
        lambda a: tool_list_fav_folders(),
    ),
    (
        "list_fav_medias",
        "看某个收藏夹里有哪些视频",
        {
            "type": "object",
            "properties": {"media_id": {"type": "integer"}, "page": {"type": "integer"}},
            "required": ["media_id"],
        },
        lambda a: tool_list_fav_medias(int(a.get("media_id") or 0), int(a.get("page") or 1)),
    ),
    (
        "create_fav_folder",
        "新建一个收藏夹",
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "privacy": {"type": "integer"}},
            "required": ["title"],
        },
        lambda a: tool_create_fav_folder(a.get("title") or "", int(a.get("privacy") or 0)),
    ),
    (
        "delete_fav_folder",
        "删除一个收藏夹（里面的收藏会一起删掉）",
        {"type": "object", "properties": {"media_id": {"type": "integer"}}, "required": ["media_id"]},
        lambda a: tool_delete_fav_folder(int(a.get("media_id") or 0)),
    ),
    (
        "favorite_video",
        "把视频收藏进收藏夹，或从收藏夹移出",
        {
            "type": "object",
            "properties": {
                "bvid": {"type": "string"},
                "oid": {"type": "integer"},
                "folder_id": {"type": "integer"},
                "undo": {"type": "boolean"},
            },
            "required": ["folder_id"],
        },
        lambda a: tool_favorite_video(
            a.get("bvid") or "", int(a.get("oid") or 0), int(a.get("folder_id") or 0), bool(a.get("undo"))
        ),
    ),
    (
        "view_user",
        "看一个人的主页：资料和他发的视频",
        {
            "type": "object",
            "properties": {"uid": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": ["uid"],
        },
        lambda a: tool_view_user(int(a.get("uid") or 0), int(a.get("limit") or 20)),
    ),
    (
        "send_dynamic",
        "发一条动态（正文自己写，就这一件事）",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        lambda a: tool_send_dynamic(a.get("text") or ""),
    ),
    (
        "delete_dynamic",
        "删掉自己的一条动态（给 dyn_id）",
        {"type": "object", "properties": {"dyn_id": {"type": "integer"}}, "required": ["dyn_id"]},
        lambda a: tool_delete_dynamic(int(a.get("dyn_id") or 0)),
    ),
    (
        "delete_comment",
        "删掉自己在视频下发的一条评论（给 oid + rpid）",
        {
            "type": "object",
            "properties": {"oid": {"type": "integer"}, "rpid": {"type": "integer"}},
            "required": ["oid", "rpid"],
        },
        lambda a: tool_delete_comment(int(a.get("oid") or 0), int(a.get("rpid") or 0)),
    ),
]

TOOL_MAP = {t[0]: t for t in TOOLS}


# ---------------------------------------------------------------- MCP 协议


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_call(name: str, args: dict):
    if name not in TOOL_MAP:
        return {"content": [{"type": "text", "text": f"没有这个工具：{name}"}], "isError": True}
    fn = TOOL_MAP[name][3]
    try:
        res = fn(args or {})
        if asyncio.iscoroutine(res):
            res = asyncio.run(res)
        return {"content": [{"type": "text", "text": str(res)}], "isError": False}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "dafeiyu-toolbox", "version": "1.0.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [
                            {"name": n, "description": d, "inputSchema": s} for (n, d, s, _f) in TOOLS
                        ]
                    },
                }
            )
        elif method == "tools/call":
            send({"jsonrpc": "2.0", "id": mid, "result": handle_call(params.get("name"), params.get("arguments") or {})})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"未知方法 {method}"}})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
