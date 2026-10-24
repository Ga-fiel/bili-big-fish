#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大肥鱼的工具箱 —— 54 个工具，AI 的手

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


async def _thread_json(oid: int, rpid: int, ps: int = 20, pn: int = 1, type_: int = 1) -> dict:
    """拉一楼的原始数据：楼层根评论 + 这楼的回复（root 传楼层根或楼内任意一条都行，B 站会解析）。"""
    if not oid or not rpid:
        return {}
    import aiohttp

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.bilibili.com/x/v2/reply/reply",
                params={"type": int(type_), "oid": int(oid), "root": int(rpid), "ps": int(ps), "pn": int(pn)},
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
                    "business_id": m["business_id"],
                    "at": m["at"],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


async def tool_read_video(bvid: str = "", oid: int = 0) -> str:
    """读一个视频的基本信息：标题、UP、简介、热门评论。要字幕用 read_subtitle / read_subtitle_all。"""
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


async def tool_send_dynamic(text: str = "", topic_id: int = 0, at_uids: list = None) -> str:
    """发一条动态。正文自己写；要带话题给 topic_id，要 @ 人给 at_uids（uid 列表）。"""
    body = _check_text(text, 2000, "动态")
    from bilibili_api import dynamic as bdynamic, user as buser

    cred = _cred()
    if isinstance(at_uids, str):
        at_uids = [x.strip() for x in at_uids.replace("，", ",").split(",") if x.strip()]
    ats = []
    for u in (at_uids or []):
        try:
            info = await buser.User(uid=int(u), credential=cred).get_user_info()
            if info.get("name"):
                ats.append("@" + str(info.get("name")))
        except Exception:
            pass
    if ats:
        body = " ".join(ats) + " " + body
    kw = {"text": body}
    if int(topic_id):
        kw["topic_id"] = int(topic_id)
    res = await bdynamic.send_dynamic(bdynamic.BuildDynamic.create_by_args(**kw), cred)
    res = res or {}
    dyn_id_str = str(res.get("dyn_id_str") or res.get("dyn_id") or "")
    return json.dumps(
        {
            "sent": True,
            "dyn_id": dyn_id_str or None,
            "dyn_id_str": dyn_id_str,
            "url": res.get("share_url") or (f"https://t.bilibili.com/{dyn_id_str}" if dyn_id_str else ""),
            "at": ats,
            "topic_id": int(topic_id or 0) or None,
            "raw": res,
        },
        ensure_ascii=False,
    )


async def tool_delete_dynamic(dyn_id: int = 0) -> str:
    """删掉自己的一条动态。dyn_id 就是发动态时返回的那个；19 位数字，传的时候用字符串，别转成数字。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id。")
    from bilibili_api import dynamic as bdynamic

    cred = _cred()
    res = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).delete()
    return json.dumps({"deleted": True, "dyn_id": str(dyn_id), "raw": res}, ensure_ascii=False)


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


async def tool_comment_dynamic(text: str = "", dyn_id: int = 0, rpid: int = 0, root: int = 0) -> str:
    """回复动态里的评论。dyn_id 是动态 id（19 位，传字符串），rpid 是要回复的那条评论 id。"""
    cfg = load_cfg()
    if not cfg.get("auto_reply", True):
        raise RuntimeError("号主关掉了「自动回复」，现在只能看不能发。")
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id，就是动态链接 /opus/ 后面那串数字。")
    text = _check_text(text)

    cred = _cred()
    from bilibili_api import comment as bcomment
    from bilibili_api import dynamic as bdynamic

    try:
        detail = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).get_info()
    except Exception as e:
        raise RuntimeError(f"这条动态现在看不到，可能已经删了或还没审核完：{e}")
    basic = ((detail or {}).get("item") or {}).get("basic") or {}
    ctype = int(basic.get("comment_type") or 0)
    oid = int(basic.get("comment_id_str") or 0) or int(dyn_id)
    if ctype == 11:
        type_ = bcomment.CommentResourceType.DYNAMIC_DRAW
    elif ctype == 17:
        type_ = bcomment.CommentResourceType.DYNAMIC
    else:
        raise RuntimeError(f"这条动态的评论类型是 {ctype}，暂时评论不了。")

    parent = int(rpid or 0)
    rt = int(root or 0) or parent
    res = await bcomment.send_comment(
        text=text,
        oid=oid,
        type_=type_,
        root=rt if rt else None,
        parent=parent if parent else None,
        credential=cred,
    )
    new_rpid = ((res or {}).get("rpid") or (res or {}).get("data", {}).get("rpid") or 0)
    return json.dumps(
        {
            "sent": True,
            "rpid": new_rpid,
            "dyn_id": str(dyn_id),
            "oid": oid,
            "comment_type": ctype,
            "toast": (res or {}).get("success_toast") or "已发送",
        },
        ensure_ascii=False,
    )


async def tool_read_dynamic_comment(dyn_id: int = 0, rpid: int = 0, root: int = 0, pn: int = 1, ps: int = 20) -> str:
    """读动态的评论。dyn_id 是动态 id（19 位，传字符串）；给 rpid 读一条，给 root 读整楼，都不给就读评论区第一页。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id，就是动态链接 /opus/ 后面那串数字。")
    cred = _cred()
    from bilibili_api import dynamic as bdynamic

    try:
        detail = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).get_info()
    except Exception as e:
        raise RuntimeError(f"这条动态现在看不到，可能已经删了或还没审核完：{e}")
    basic = ((detail or {}).get("item") or {}).get("basic") or {}
    ctype = int(basic.get("comment_type") or 0)
    oid = int(basic.get("comment_id_str") or 0) or int(dyn_id)
    if ctype not in (11, 17):
        raise RuntimeError(f"这条动态的评论类型是 {ctype}，读不了。")

    rp = int(rpid or 0)
    rt = int(root or 0) or rp
    if rt:
        data = await _thread_json(
            oid, rt, ps=max(1, min(50, int(ps or 20))), pn=max(1, int(pn or 1)), type_=ctype
        )
        root_c = data.get("root") or {}
        replies = data.get("replies") or []
        target = None
        if rp:
            if int(root_c.get("rpid") or 0) == rp:
                target = root_c
            else:
                for c in replies:
                    if int(c.get("rpid") or 0) == rp:
                        target = c
                        break
        out = {
            "dyn_id": str(dyn_id),
            "oid": oid,
            "comment_type": ctype,
            "root": _reply_row(root_c, oid) if root_c else None,
            "replies": [_reply_row(c, oid) for c in replies],
            "page": data.get("page") or {},
        }
        if rp:
            out["found"] = bool(target)
            out["target"] = _reply_row(target, oid) if target else None
            out["floor_is_target"] = bool(target and root_c and int(root_c.get("rpid") or 0) == rp)
            if not target:
                out["hint"] = "这条查不到（可能已删/被折叠）。"
        return json.dumps(out, ensure_ascii=False)

    import aiohttp

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.bilibili.com/x/v2/reply",
                params={
                    "type": ctype,
                    "oid": oid,
                    "ps": max(1, min(50, int(ps or 20))),
                    "pn": max(1, int(pn or 1)),
                    "sort": 2,
                },
                headers=_cookie_headers(cred),
            ) as r:
                body = await r.json(content_type=None)
    except Exception as e:
        raise RuntimeError(f"评论拉不到：{e}")
    if body.get("code") != 0:
        raise RuntimeError(f"评论拉不到：{body.get('code')} {body.get('message')}")
    data = body.get("data") or {}
    return json.dumps(
        {
            "dyn_id": str(dyn_id),
            "oid": oid,
            "comment_type": ctype,
            "page": data.get("page") or {},
            "replies": [_reply_row(c, oid) for c in (data.get("replies") or [])],
        },
        ensure_ascii=False,
    )


STICKER_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _sticker_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "表情库")


def _sticker_files() -> list:
    d = _sticker_dir()
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if os.path.splitext(f)[1].lower() in STICKER_EXT)


def _sticker_path(name: str) -> str:
    """按名字找表情：带不带后缀都行，先同名再包含。"""
    d = _sticker_dir()
    raw = str(name or "").strip()
    files = _sticker_files()
    if not raw:
        raise RuntimeError("要给表情名字，比如「偷笑」。")
    if raw in files:
        return os.path.join(d, raw)
    for f in files:
        if os.path.splitext(f)[0] == raw:
            return os.path.join(d, f)
    hits = [f for f in files if raw in f]
    if len(hits) == 1:
        return os.path.join(d, hits[0])
    if hits:
        raise RuntimeError(f"有不止一个像「{raw}」的：{'、'.join(hits)}，说全一点。")
    names = "、".join(os.path.splitext(f)[0] for f in files) or "（空）"
    raise RuntimeError(f"表情库里没有「{raw}」。现在有：{names}")


def tool_list_stickers(keyword: str = "") -> str:
    """列出本地表情库里的表情。文件名就是它的意思。"""
    names = [os.path.splitext(f)[0] for f in _sticker_files()]
    kw = str(keyword or "").strip()
    if kw:
        names = [n for n in names if kw in n]
    if not names:
        return "没有匹配的表情。"
    return "\n".join(names)


async def tool_send_sticker(
    name: str = "",
    target: str = "comment",
    oid: int = 0,
    rpid: int = 0,
    root: int = 0,
    dyn_id: int = 0,
    uid: int = 0,
    text: str = "",
) -> str:
    """发一张本地表情库里的表情。target 是 comment / dm / dynamic。"""
    from bilibili_api.utils.picture import Picture

    cfg = load_cfg()
    if not cfg.get("auto_reply", True):
        raise RuntimeError("号主关掉了「自动回复」，现在只能看不能发。")
    path = _sticker_path(name)
    pic = Picture.from_file(path)
    cred = _cred()
    who = os.path.basename(path)
    tg = str(target or "comment").strip().lower()

    if tg == "comment":
        if not int(oid) and not int(dyn_id):
            raise RuntimeError("评论要 oid（视频）或 dyn_id（动态）。")
        from bilibili_api import comment as bcomment
        from bilibili_api import dynamic as bdynamic

        if int(dyn_id):
            detail = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).get_info()
            basic = ((detail or {}).get("item") or {}).get("basic") or {}
            ctype = int(basic.get("comment_type") or 0)
            target_oid = int(basic.get("comment_id_str") or 0) or int(dyn_id)
            if ctype == 11:
                tp = bcomment.CommentResourceType.DYNAMIC_DRAW
            elif ctype == 17:
                tp = bcomment.CommentResourceType.DYNAMIC
            else:
                raise RuntimeError(f"这条动态的评论类型是 {ctype}，发不了。")
        else:
            target_oid = int(oid)
            tp = bcomment.CommentResourceType.VIDEO
        parent = int(rpid or 0)
        rt = int(root or 0) or parent
        body = _check_text(text)
        warn = _cap_check("video", str(target_oid)) if not int(dyn_id) else ""
        res = await bcomment.send_comment(
            text=body,
            oid=target_oid,
            type_=tp,
            root=rt if rt else None,
            parent=parent if parent else None,
            pic=pic,
            credential=cred,
        )
        new_rpid = ((res or {}).get("rpid") or (res or {}).get("data", {}).get("rpid") or 0)
        if warn:
            _cap_bump("video", 0, str(target_oid))
        out = {
            "sent": True,
            "rpid": new_rpid,
            "oid": target_oid,
            "sticker": who,
            "toast": (res or {}).get("success_toast") or "已发送",
        }
        return json.dumps(out, ensure_ascii=False) + (("\n" + warn) if warn else "")

    if tg == "dm":
        _forbid_dm()
        if not int(uid):
            raise RuntimeError("私信要 uid。")
        from bilibili_api import session

        await session.send_msg(cred, int(uid), session.EventType.PICTURE, pic)
        return json.dumps({"sent": True, "uid": int(uid), "sticker": who, "toast": "已发送"}, ensure_ascii=False)

    if tg == "dynamic":
        from bilibili_api import dynamic as bdynamic

        body = _check_text(text) if str(text or "").strip() else ""
        res = await bdynamic.send_dynamic(bdynamic.BuildDynamic.create_by_args(text=body, pics=[pic]), cred)
        d = res or {}
        dyn_s = str(d.get("dyn_id_str") or d.get("dyn_id") or "")
        return json.dumps(
            {
                "sent": True,
                "dyn_id": dyn_s or None,
                "url": d.get("share_url") or (f"https://t.bilibili.com/{dyn_s}" if dyn_s else ""),
                "sticker": who,
            },
            ensure_ascii=False,
        )

    raise RuntimeError("target 只能是 comment、dm、dynamic。")


# ---------------------------------------------------------------- 视频扩展（字幕 / 弹幕 / 相关推荐）


def _video_obj(bvid: str = "", oid: int = 0, cred=None):
    from bilibili_api import video as bvideo

    if bvid:
        return bvideo.Video(bvid=bvid, credential=cred or _cred())
    if oid:
        return bvideo.Video(aid=int(oid), credential=cred or _cred())
    raise RuntimeError("要么给 bvid，要么给 oid。")


async def _video_cid(v) -> int:
    info = await v.get_info()
    return int(((info.get("pages") or [{}])[0] or {}).get("cid") or 0)


async def _subtitle_text(v) -> str:
    cid = await _video_cid(v)
    if not cid:
        return ""
    try:
        sub = await v.get_subtitle(cid=cid)
    except Exception:
        return ""
    subs = (sub or {}).get("subtitles") or []
    if not subs:
        return ""
    import urllib.request

    url = subs[0].get("subtitle_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return " ".join((x.get("content") or "") for x in (body.get("body") or [])).strip()


async def tool_read_subtitle(bvid: str = "", oid: int = 0, chars: int = 500) -> str:
    """读视频字幕的前 chars 个字（默认 500）。要全文用 read_subtitle_all。"""
    v = _video_obj(bvid, oid)
    text = await _subtitle_text(v)
    if not text:
        raise RuntimeError("这个视频没有字幕。")
    n = max(1, int(chars or 500))
    if len(text) <= n:
        return text
    return text[:n] + f"…（共 {len(text)} 字，要更多就加大 chars，或者用 read_subtitle_all）"


async def tool_read_subtitle_all(bvid: str = "", oid: int = 0) -> str:
    """读视频的全部字幕（太长时截到 10000 字）。"""
    v = _video_obj(bvid, oid)
    text = await _subtitle_text(v)
    if not text:
        raise RuntimeError("这个视频没有字幕。")
    return text[:10000]


async def tool_read_video_ai(bvid: str = "", oid: int = 0) -> str:
    """读视频的 AI 总结。"""
    v = _video_obj(bvid, oid)
    cid = await _video_cid(v)
    res = None
    for _ in range(2):
        try:
            res = await v.get_ai_conclusion(cid=cid)
            break
        except Exception:
            res = None
    model = (res or {}).get("model_result") or {}
    summary = (model.get("summary") or "").strip()
    outline = model.get("outline") or []
    if not summary and not outline:
        raise RuntimeError("这个视频没有 AI 总结。")
    parts = []
    if summary:
        parts.append(summary)
    for o in outline[:20]:
        t = (o or {}).get("title") or ""
        if t:
            parts.append(f"· {t}")
    return "\n".join(parts)


async def tool_list_danmakus(bvid: str = "", oid: int = 0, limit: int = 50) -> str:
    """读视频的弹幕：时间 + 内容。limit 是最多几条。"""
    v = _video_obj(bvid, oid)
    cid = await _video_cid(v)
    dms = await v.get_danmakus(cid=cid)
    n = max(1, int(limit or 50))
    clean = [d for d in (dms or []) if (getattr(d, "text", "") or "").strip()]
    lines = []
    for d in clean[:n]:
        t = float(getattr(d, "dm_time", 0) or 0)
        mm, ss = int(t // 60), int(t % 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {getattr(d, 'text', '')}")
    if not lines:
        raise RuntimeError("这个视频还没有弹幕。")
    return "\n".join(lines) + f"\n（共 {len(clean)} 条，这里显示 {len(lines)} 条）"


async def tool_send_danmaku(bvid: str = "", oid: int = 0, text: str = "", progress: int = 0, mode: int = 1) -> str:
    """发一条弹幕。progress 是视频里的位置（毫秒），mode 1=滚动 4=底部 5=顶部。"""
    cfg = load_cfg()
    if not cfg.get("auto_reply", True):
        raise RuntimeError("号主关掉了「自动回复」，现在只能看不能发。")
    text = _check_text(text, 100, "弹幕")
    v = _video_obj(bvid, oid)
    cid = await _video_cid(v)
    from bilibili_api.utils.danmaku import Danmaku

    dm = Danmaku(text=text, dm_time=max(0.0, float(progress or 0) / 1000.0), mode=int(mode or 1))
    res = await v.send_danmaku(page_index=0, danmaku=dm, cid=cid)
    return json.dumps(
        {"sent": True, "text": text, "progress_ms": int(progress or 0), "mode": int(mode or 1), "raw": res},
        ensure_ascii=False,
    )


async def tool_list_related(bvid: str = "", oid: int = 0, limit: int = 10) -> str:
    """列一个视频的相关推荐。"""
    v = _video_obj(bvid, oid)
    rel = await v.get_related()
    n = max(1, int(limit or 10))
    lines = []
    for x in (rel or [])[:n]:
        lines.append(
            f"{x.get('bvid')} | {x.get('title')} | UP {((x.get('owner') or {}).get('name'))} | 播放 {(x.get('stat') or {}).get('view')}"
        )
    if not lines:
        raise RuntimeError("没有相关推荐。")
    return "\n".join(lines)


async def tool_add_to_toview(bvid: str = "", oid: int = 0, undo: bool = False) -> str:
    """把视频加进稍后再看；undo=True 就移出来。"""
    v = _video_obj(bvid, oid)
    res = await (v.delete_from_toview() if undo else v.add_to_toview())
    return json.dumps({"ok": True, "toview": not undo, "raw": res}, ensure_ascii=False)


async def tool_list_toview(limit: int = 20) -> str:
    """列稍后再看。"""
    cred = _cred()
    from bilibili_api import user as buser

    res = await buser.get_toview_list(cred)
    items = (res or {}).get("list") or []
    if not items:
        return "稍后再看是空的。"
    lines = [
        f"{x.get('bvid')} | {x.get('title')} | aid {x.get('aid')}"
        for x in items[: max(1, int(limit or 20))]
    ]
    return "\n".join(lines) + f"\n（共 {(res or {}).get('count')} 个）"


# ---------------------------------------------------------------- 动态扩展


def _dyn_time(ts) -> str:
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return ""


def _dyn_row(it) -> str:
    it = it or {}
    mods = it.get("modules") or {}
    ma = mods.get("module_author") or {}
    md = mods.get("module_dynamic") or {}
    major = md.get("major") or {}
    txt = ((major.get("opus") or {}).get("summary") or {}).get("text") or (md.get("desc") or {}).get("text") or ""
    st = mods.get("module_stat") or {}
    likes = ((st.get("like") or {}).get("count")) or 0
    return f"{it.get('id_str')} | {ma.get('name')} | {_dyn_time(ma.get('pub_ts'))} | 赞 {likes} | {_clean(txt)[:100]}"


async def tool_list_user_dynamics(uid: int = 0, limit: int = 10) -> str:
    """看某个人最近发的动态。"""
    if not int(uid):
        raise RuntimeError("要给我 uid。")
    cred = _cred()
    from bilibili_api import user as buser

    res = await buser.User(uid=int(uid), credential=cred).get_dynamics_new()
    items = (res or {}).get("items") or []
    if not items:
        return "这个人最近没发动态。"
    return "\n".join(_dyn_row(x) for x in items[: max(1, int(limit or 10))])


async def tool_list_following_dynamics(limit: int = 10) -> str:
    """看关注的人最新的动态。"""
    cred = _cred()
    from bilibili_api import dynamic as bdynamic

    res = await bdynamic.get_dynamic_page_info(cred, _type=None)
    items = (res or {}).get("items") or []
    if not items:
        return "关注的人最近没发动态。"
    return "\n".join(_dyn_row(x) for x in items[: max(1, int(limit or 10))])


async def tool_repost_dynamic(dyn_id: int = 0, text: str = "") -> str:
    """转发一条动态。dyn_id 是 19 位数字，传的时候用字符串。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id。")
    cred = _cred()
    from bilibili_api import dynamic as bdynamic

    res = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).repost(text=(text or "转发动态")[:1000])
    rid = str(((res or {}).get("dyn_id_str") or (res or {}).get("dyn_id") or "") or "")
    return json.dumps({"reposted": True, "dyn_id": str(dyn_id), "new_dyn_id": rid or None, "raw": res}, ensure_ascii=False)


async def tool_like_dynamic(dyn_id: int = 0, undo: bool = False) -> str:
    """给一条动态点赞；undo=True 取消点赞。dyn_id 是 19 位数字，传的时候用字符串。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id。")
    cred = _cred()
    from bilibili_api import dynamic as bdynamic

    res = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).set_like(not undo)
    return json.dumps({"ok": True, "dyn_id": str(dyn_id), "liked": not undo, "raw": res}, ensure_ascii=False)


async def tool_favorite_dynamic(dyn_id: int = 0, undo: bool = False) -> str:
    """收藏一条动态；undo=True 取消收藏。dyn_id 是 19 位数字，传的时候用字符串。"""
    if not int(dyn_id):
        raise RuntimeError("要给我 dyn_id。")
    cred = _cred()
    from bilibili_api import dynamic as bdynamic

    res = await bdynamic.Dynamic(dynamic_id=int(dyn_id), credential=cred).set_favorite(not undo)
    return json.dumps({"ok": True, "dyn_id": str(dyn_id), "favorited": not undo, "raw": res}, ensure_ascii=False)


# ---------------------------------------------------------------- 账号 / 搜索 / 榜单


async def tool_name_to_uid(name: str = "") -> str:
    """把 B站 用户名转成 uid。"""
    name = (name or "").strip()
    if not name:
        raise RuntimeError("要给我名字。")
    cred = _cred()
    from bilibili_api import user as buser

    res = await buser.name2uid(name, credential=cred)
    lst = (res or {}).get("uid_list") or []
    if not lst:
        raise RuntimeError(f"没找到叫「{name}」的人。")
    return "\n".join(f"{x.get('uid')} | {x.get('name')}" for x in lst)


async def tool_self_info() -> str:
    """看自己账号的数据：昵称、等级、硬币、粉丝、关注。"""
    cred = _cred()
    from bilibili_api import user as buser

    uid = _self_uid()
    info = await buser.get_self_info(cred)
    coins = await buser.get_self_coins(cred)
    rel = await buser.User(uid=uid, credential=cred).get_relation_info()
    return json.dumps(
        {
            "uid": uid,
            "name": info.get("name"),
            "level": info.get("level"),
            "coins": coins,
            "fans": (rel or {}).get("follower"),
            "following": (rel or {}).get("following"),
            "sign": info.get("sign") or "",
        },
        ensure_ascii=False,
    )


async def tool_up_stat(uid: int = 0) -> str:
    """看一个 UP 主的数据：播放、点赞、粉丝。"""
    if not int(uid):
        raise RuntimeError("要给我 uid。")
    cred = _cred()
    from bilibili_api import user as buser

    u = buser.User(uid=int(uid), credential=cred)
    up = await u.get_up_stat()
    ov = await u.get_overview_stat()
    rel = await u.get_relation_info()
    return json.dumps(
        {
            "uid": int(uid),
            "fans": (rel or {}).get("follower"),
            "play": ((up or {}).get("archive") or {}).get("view"),
            "likes": (up or {}).get("likes"),
            "videos": (ov or {}).get("video"),
            "articles": (ov or {}).get("article"),
        },
        ensure_ascii=False,
    )


async def tool_search_other(keyword: str = "", type: str = "user") -> str:
    """搜视频以外的东西：type 用 user / article / bangumi / live / topic。"""
    keyword = (keyword or "").strip()
    if not keyword:
        raise RuntimeError("要给我关键词。")
    from bilibili_api import search as bsearch

    tmap = {
        "user": bsearch.SearchObjectType.USER,
        "article": bsearch.SearchObjectType.ARTICLE,
        "bangumi": bsearch.SearchObjectType.BANGUMI,
        "live": bsearch.SearchObjectType.LIVE,
        "topic": bsearch.SearchObjectType.TOPIC,
    }
    t = str(type or "user").lower()
    if t not in tmap:
        raise RuntimeError("type 只能是 user、article、bangumi、live、topic。")
    try:
        res = await bsearch.search_by_type(keyword, tmap[t])
    except Exception as e:
        raise RuntimeError(f"这次搜不了：{e}")
    raw = (res or {}).get("result")
    items = list(raw) if isinstance(raw, list) else []
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list):
                items.extend(v)
    if not items:
        return "没搜到。"
    lines = []
    for x in items[:20]:
        if t == "user":
            lines.append(f"用户 {x.get('mid')} | {x.get('uname')} | 粉丝 {x.get('fans')}")
        elif t == "article":
            lines.append(f"专栏 {x.get('id')} | {_clean(str(x.get('title') or ''))} | UP {x.get('author')}")
        elif t == "bangumi":
            lines.append(f"番剧 {x.get('season_id') or x.get('media_id')} | {_clean(str(x.get('title') or ''))}")
        elif t == "live":
            lines.append(f"直播 {x.get('roomid')} | {_clean(str(x.get('title') or ''))} | {x.get('uname')}")
        else:
            lines.append(f"{x.get('id')} | {_clean(str(x.get('title') or x.get('name') or ''))}")
    return "\n".join(lines)


async def tool_hot_search() -> str:
    """B站 热搜词。"""
    from bilibili_api import search as bsearch

    res = await bsearch.get_hot_search_keywords()
    items = (res or {}).get("list") or []
    if not items:
        return "现在没有热搜。"
    return "\n".join(f"{x.get('keyword')}（{x.get('show_name')}）" for x in items[:20])


async def tool_homepage_videos(limit: int = 10) -> str:
    """首页推荐视频。"""
    cred = _cred()
    from bilibili_api import homepage as bhome

    res = await bhome.get_videos(cred)
    items = [x for x in ((res or {}).get("item") or []) if x.get("goto") == "av"]
    if not items:
        return "首页没有推荐。"
    lines = [
        f"{x.get('bvid')} | {x.get('title')} | UP {((x.get('owner') or {}).get('name'))}"
        for x in items[: max(1, int(limit or 10))]
    ]
    return "\n".join(lines)


async def tool_hot_videos(kind: str = "hot", limit: int = 10) -> str:
    """热门视频。kind=hot 是热门，weekly 是每周必看。"""
    from bilibili_api import hot as bhot

    n = max(1, int(limit or 10))
    k = str(kind or "hot").lower()
    if k == "weekly":
        from bilibili_api.utils.network import Api

        series = {
            "url": "https://api.bilibili.com/x/web-interface/popular/series/list",
            "method": "GET",
            "verify": False,
            "wbi": True,
        }
        one = {
            "url": "https://api.bilibili.com/x/web-interface/popular/series/one",
            "method": "GET",
            "verify": False,
            "wbi": True,
        }
        cred = _cred()
        lst = (
            await Api(**series, credential=cred)
            .update_params(web_location="333.934")
            .result
        )
        arr = (lst or {}).get("list") or []
        if not arr:
            raise RuntimeError("拿不到每周必看。")
        week = int(arr[0].get("number") or 1)
        res = (
            await Api(**one, credential=cred)
            .update_params(number=week, web_location="333.934")
            .result
        )
        items = (res or {}).get("list") or []
    elif k == "hot":
        res = await bhot.get_hot_videos(pn=1, ps=n)
        items = (res or {}).get("list") or []
    else:
        raise RuntimeError("kind 只能是 hot 或 weekly。")
    if not items:
        return "没有。"
    return "\n".join(
        f"{x.get('bvid') or x.get('aid')} | {x.get('title')} | UP {((x.get('owner') or {}).get('name'))}"
        for x in items[:n]
    )


async def tool_zone_videos(tid: int = 0, kind: str = "top10") -> str:
    """分区排行。tid 是分区 id；kind 目前只能 top10（分区最新接口 B站 已关）。"""
    if not int(tid):
        raise RuntimeError("要给我 tid（分区 id）。")
    k = str(kind or "top10").lower()
    if k == "new":
        raise RuntimeError("分区最新投稿接口 B站 已经关了（-404），现在只能看 top10。")
    from bilibili_api import video_zone as bzone

    res = await bzone.get_zone_top10(int(tid), day=7)
    items = res or []
    if not items:
        return "这个分区没有排行。"
    return "\n".join(
        f"{x.get('bvid')} | {x.get('title')} | UP {x.get('author')} | 播放 {x.get('play')}"
        for x in items[:20]
    )


async def tool_rank_videos(limit: int = 10) -> str:
    """全站排行榜。"""
    from bilibili_api import rank as brank

    res = await brank.get_rank()
    items = (res or {}).get("list") or []
    if not items:
        return "现在没有排行榜。"
    return "\n".join(
        f"{x.get('bvid') or x.get('aid')} | {x.get('title')} | UP {((x.get('owner') or {}).get('name'))}"
        for x in items[: max(1, int(limit or 10))]
    )


async def tool_list_emoji(package_id: int = 0) -> str:
    """列 B站 官方表情包。不给 package_id 就列包；给 package_id 就列这个包里的表情。"""
    cred = _cred()
    from bilibili_api import emoji as bemoji

    if int(package_id):
        res = await bemoji.get_emoji_detail(int(package_id), "reply")
        pkgs = (res or {}).get("packages") or []
        lines = []
        for p in pkgs:
            for e in (p.get("emote") or [])[:80]:
                lines.append(f"{e.get('text')}")
        return "\n".join(lines) if lines else "这个包里没有表情。"
    res = await bemoji.get_emoji_list("reply", cred)
    pkgs = (res or {}).get("packages") or []
    if not pkgs:
        return "拿不到表情包列表。"
    return "\n".join(f"{p.get('id')} | {p.get('text')}" for p in pkgs[:60])


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
        "发一条动态（正文自己写；可以带话题和 @）",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "topic_id": {"type": "integer"},
                "at_uids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["text"],
        },
        lambda a: tool_send_dynamic(a.get("text") or "", int(a.get("topic_id") or 0), a.get("at_uids") or []),
    ),
    (
        "delete_dynamic",
        "删掉自己的一条动态（给 dyn_id）",
        {"type": "object", "properties": {"dyn_id": {"type": ["integer", "string"]}}, "required": ["dyn_id"]},
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
    (
        "comment_dynamic",
        "回复动态里的评论（dyn_id 是动态 id，rpid 是要回复的评论 id）",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "dyn_id": {"type": ["integer", "string"]},
                "rpid": {"type": "integer"},
                "root": {"type": "integer"},
            },
            "required": ["text", "dyn_id"],
        },
        lambda a: tool_comment_dynamic(
            a.get("text") or "", int(a.get("dyn_id") or 0), int(a.get("rpid") or 0), int(a.get("root") or 0)
        ),
    ),
    (
        "read_dynamic_comment",
        "读动态的评论（dyn_id 是动态 id，rpid/root 是要读的评论或楼层）",
        {
            "type": "object",
            "properties": {
                "dyn_id": {"type": ["integer", "string"]},
                "rpid": {"type": "integer"},
                "root": {"type": "integer"},
                "pn": {"type": "integer"},
                "ps": {"type": "integer"},
            },
            "required": ["dyn_id"],
        },
        lambda a: tool_read_dynamic_comment(
            int(a.get("dyn_id") or 0),
            int(a.get("rpid") or 0),
            int(a.get("root") or 0),
            int(a.get("pn") or 1),
            int(a.get("ps") or 20),
        ),
    ),
    (
        "list_stickers",
        "列出本地表情库里的表情（文件名就是意思）",
        {"type": "object", "properties": {"keyword": {"type": "string"}}},
        lambda a: tool_list_stickers(a.get("keyword") or ""),
    ),
    (
        "send_sticker",
        "发一张本地表情（target: comment / dm / dynamic）",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "target": {"type": "string"},
                "oid": {"type": "integer"},
                "rpid": {"type": "integer"},
                "root": {"type": "integer"},
                "dyn_id": {"type": ["integer", "string"]},
                "uid": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["name"],
        },
        lambda a: tool_send_sticker(
            a.get("name") or "",
            a.get("target") or "comment",
            int(a.get("oid") or 0),
            int(a.get("rpid") or 0),
            int(a.get("root") or 0),
            int(a.get("dyn_id") or 0),
            int(a.get("uid") or 0),
            a.get("text") or "",
        ),
    ),
    (
        "read_subtitle",
        "读视频字幕的前 N 个字（默认 500 字）",
        {
            "type": "object",
            "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}, "chars": {"type": "integer"}},
        },
        lambda a: tool_read_subtitle(a.get("bvid") or "", int(a.get("oid") or 0), int(a.get("chars") or 500)),
    ),
    (
        "read_subtitle_all",
        "读视频的全部字幕",
        {"type": "object", "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}}},
        lambda a: tool_read_subtitle_all(a.get("bvid") or "", int(a.get("oid") or 0)),
    ),
    (
        "read_video_ai",
        "读视频的 AI 总结",
        {"type": "object", "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}}},
        lambda a: tool_read_video_ai(a.get("bvid") or "", int(a.get("oid") or 0)),
    ),
    (
        "list_danmakus",
        "读视频的弹幕（时间 + 内容）",
        {
            "type": "object",
            "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}, "limit": {"type": "integer"}},
        },
        lambda a: tool_list_danmakus(a.get("bvid") or "", int(a.get("oid") or 0), int(a.get("limit") or 50)),
    ),
    (
        "send_danmaku",
        "发一条弹幕（progress 是毫秒位置，mode 1=滚动 4=底部 5=顶部）",
        {
            "type": "object",
            "properties": {
                "bvid": {"type": "string"},
                "oid": {"type": "integer"},
                "text": {"type": "string"},
                "progress": {"type": "integer"},
                "mode": {"type": "integer"},
            },
            "required": ["text"],
        },
        lambda a: tool_send_danmaku(
            a.get("bvid") or "",
            int(a.get("oid") or 0),
            a.get("text") or "",
            int(a.get("progress") or 0),
            int(a.get("mode") or 1),
        ),
    ),
    (
        "list_related",
        "列一个视频的相关推荐",
        {
            "type": "object",
            "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}, "limit": {"type": "integer"}},
        },
        lambda a: tool_list_related(a.get("bvid") or "", int(a.get("oid") or 0), int(a.get("limit") or 10)),
    ),
    (
        "add_to_toview",
        "把视频加进稍后再看；undo=True 就移出来",
        {
            "type": "object",
            "properties": {"bvid": {"type": "string"}, "oid": {"type": "integer"}, "undo": {"type": "boolean"}},
        },
        lambda a: tool_add_to_toview(a.get("bvid") or "", int(a.get("oid") or 0), bool(a.get("undo"))),
    ),
    (
        "list_toview",
        "列稍后再看",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
        lambda a: tool_list_toview(int(a.get("limit") or 20)),
    ),
    (
        "list_user_dynamics",
        "看某个人最近发的动态",
        {
            "type": "object",
            "properties": {"uid": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": ["uid"],
        },
        lambda a: tool_list_user_dynamics(int(a.get("uid") or 0), int(a.get("limit") or 10)),
    ),
    (
        "list_following_dynamics",
        "看关注的人最新动态",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
        lambda a: tool_list_following_dynamics(int(a.get("limit") or 10)),
    ),
    (
        "repost_dynamic",
        "转发一条动态",
        {
            "type": "object",
            "properties": {"dyn_id": {"type": ["integer", "string"]}, "text": {"type": "string"}},
            "required": ["dyn_id"],
        },
        lambda a: tool_repost_dynamic(int(a.get("dyn_id") or 0), a.get("text") or ""),
    ),
    (
        "like_dynamic",
        "给动态点赞；undo=True 取消",
        {
            "type": "object",
            "properties": {"dyn_id": {"type": ["integer", "string"]}, "undo": {"type": "boolean"}},
            "required": ["dyn_id"],
        },
        lambda a: tool_like_dynamic(int(a.get("dyn_id") or 0), bool(a.get("undo"))),
    ),
    (
        "favorite_dynamic",
        "收藏动态；undo=True 取消",
        {
            "type": "object",
            "properties": {"dyn_id": {"type": ["integer", "string"]}, "undo": {"type": "boolean"}},
            "required": ["dyn_id"],
        },
        lambda a: tool_favorite_dynamic(int(a.get("dyn_id") or 0), bool(a.get("undo"))),
    ),
    (
        "name_to_uid",
        "B站用户名转 uid",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        lambda a: tool_name_to_uid(a.get("name") or ""),
    ),
    (
        "self_info",
        "看自己账号的数据",
        {"type": "object", "properties": {}},
        lambda a: tool_self_info(),
    ),
    (
        "up_stat",
        "看一个 UP 主的数据",
        {"type": "object", "properties": {"uid": {"type": "integer"}}, "required": ["uid"]},
        lambda a: tool_up_stat(int(a.get("uid") or 0)),
    ),
    (
        "search_other",
        "搜视频以外的东西：type 用 user / article / bangumi / live / topic",
        {
            "type": "object",
            "properties": {"keyword": {"type": "string"}, "type": {"type": "string"}},
            "required": ["keyword"],
        },
        lambda a: tool_search_other(a.get("keyword") or "", a.get("type") or "user"),
    ),
    (
        "hot_search",
        "B站热搜词",
        {"type": "object", "properties": {}},
        lambda a: tool_hot_search(),
    ),
    (
        "homepage_videos",
        "首页推荐视频",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
        lambda a: tool_homepage_videos(int(a.get("limit") or 10)),
    ),
    (
        "hot_videos",
        "热门视频（kind=hot 热门 / weekly 每周必看）",
        {
            "type": "object",
            "properties": {"kind": {"type": "string"}, "limit": {"type": "integer"}},
        },
        lambda a: tool_hot_videos(a.get("kind") or "hot", int(a.get("limit") or 10)),
    ),
    (
        "zone_videos",
        "分区排行（给 tid）",
        {
            "type": "object",
            "properties": {"tid": {"type": "integer"}, "kind": {"type": "string"}},
            "required": ["tid"],
        },
        lambda a: tool_zone_videos(int(a.get("tid") or 0), a.get("kind") or "top10"),
    ),
    (
        "rank_videos",
        "全站排行榜",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
        lambda a: tool_rank_videos(int(a.get("limit") or 10)),
    ),
    (
        "list_emoji",
        "列官方表情包；给 package_id 列包里的表情",
        {"type": "object", "properties": {"package_id": {"type": "integer"}}},
        lambda a: tool_list_emoji(int(a.get("package_id") or 0)),
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
