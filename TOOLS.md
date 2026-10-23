# 工具手册

这份是给你的**说明书**，不是主人的要求。主人的要求看 `DUTY.md`，你是什么样的人看 `IDENTITY.md`。

工具在系统里的全名带 `mcp__dafeiyu__` 前缀，比如 `mcp__dafeiyu__peek_inbox`。
下面统一写短名，调不动就加前缀。参数名必须一字不差。

---

## 第一步：读任务包

`peek_inbox` —— 无参数。返回 `inbox/` 里最新的那个 JSON。醒来第一件事就是它。

### `kind = "messages"` 的任务包

```json
{
  "kind": "messages",
  "at": "2026-10-22 22:27",
  "policy": {
    "模式":     {"at": 2, "reply": 2, "dm": 2},
    "态度":     {"at": "yes", "reply": "yes", "dm": "filter"},
    "限额":     {"daily_people": 5, "per_video": 5, "per_thread": 3,
                 "daily_dm": 5, "hourly_wakes": 10, "scan_per_day": 10, "hard": false},
    "配额已用": {"daily_people_used": 1, "daily_people_cap": 5,
                 "dm_used": 1, "dm_cap": 5, "hard": false},
    "私信上限字数": 450
  },
  "items": [ … ]
}
```

`items` 里每一项的字段：

| 字段 | 类型 | 意思 |
|---|---|---|
| `kind` | string | `at` 有人 @ 你 / `reply` 有人回了你的评论 / `dm` 私信 |
| `rpid` | int | 对方**这一条**的 id。发给 `post_reply` 的 `rpid` |
| `oid` | int | 视频的 aid。发给 `post_reply` 的 `oid` |
| `root` | int | 楼层根。发给 `post_reply` 的 `root` |
| `from_uid` | int | 对方 UID。发给 `post_reply` 的 `to_uid`，或 `send_dm` 的 `uid` |
| `from_name` | string | 对方昵称 |
| `text` | string | 对方说的原话 |
| `root_text` | string | 楼层根那句，回复场景才有，可能为空 |
| `uri` | string | 视频链接，`BV…` 从里面看 |
| `bvid` | string | 可能为空 |
| `at` | int | 时间戳（秒）。私信项没有这个字段 |
| `ts` | int | 只有 `dm` 项有，私信时间戳 |

**`dm` 项长得不一样**，没有 `rpid`/`oid`/`root`/`at`：

```json
{ "kind": "dm", "from_uid": 1000000000, "from_name": "主人",
  "text": "（2 条未读）肥鱼肥鱼肥鱼", "ts": 1792674422 }
```

> 上面是示例占位。实际运行时 `from_uid` / `from_name` 是主人自己的 UID 和昵称，
> 由 `config.json` 的 `share.master_uid` / `share.master_name` 决定。
```

### `kind = "scan"` 的任务包

比 messages 多一个 `scan` 段。**注意：主人已经不给你筛选条件了**，这一段只剩两个数：

```json
{ "kind": "scan",
  "scan": { "self_decided": true, "daily_new": 15 },
  "policy": { … } }
```

`daily_new` = 今天要刷满多少个**没刷过的**视频。
关键词、方向、播放量门槛、时长要求 —— 全部由你自己定。

### `kind = "diary"` 的任务包

只有 `kind` / `created_at` / `at` / `policy`，没有 `items`。

---

## 十四个工具

### `peek_inbox`
无参数。返回最新任务包 JSON。没有包时返回一句话说明。

### `get_policy`
无参数。返回主人全部设定和今天额度用了多少。任务包里的 `policy` 就是它，懒得翻包时用。

### `list_mentions`
| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 20 | 最多几条 |
| `kinds` | `"at,reply"` | 逗号分隔，可选 `at` `reply` |

返回**每行一个 JSON**（不是数组），字段是 `kind/rpid/oid/root/from/text/root_text/uri/time`。
它已经按你的态度档过滤过：`forbid` 的类别根本不会出现。已经回过的不会消失，自己看 `time` 判断。

### `read_video`
| 参数 | 说明 |
|---|---|
| `bvid` | 例如 `BV16KnN6KEwo` |
| `oid` | 视频 aid，二选一 |

返回一段文本，头两行是 `oid：…` 和 `bvid：…`（拿 `oid` 就能直接 `comment_video` 或 `post_reply`），
然后标题 / UP / 时长 / 分区 / 播放 / 简介（前 300 字）/ 字幕摘录（前 1500 字）/ 3 条热门评论。
字幕可能没有，会写「（字幕没取到：…）」或者干脆没有那一行。**简介和标题总有。**

**调一次它就记一次账**：这个视频会写进 `seen_videos.json`，`search_videos` 以后不再给你。
所以"读过的视频"不用你自己记，系统替你记了。

### `post_reply`
| 参数 | 必填 | 说明 |
|---|---|---|
| `text` | 是 | 你要说的话，≤ 1000 字 |
| `oid` | 是 | 视频 aid |
| `rpid` | 否 | 对方那条的 id，填了才是"回复他" |
| `root` | 否 | 楼层根，留空就自动用 `rpid` |
| `to_uid` | 否 | 对方 uid，用来记账 |

返回 `{"sent": true, "rpid": …, "toast": "发送成功"}`。
额度用满时会在后面多一段 `【提醒】…`（软限额），或者直接报错（硬限额）。

会被拒绝的情况：主人关了自动回复 / 空内容 / 内容以 `[草稿]` 开头 / 超过 1000 字。

### `comment_video`
在视频底下**开一条自己的评论**（不是回复某个人）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `text` | 是 | 你要说的话，≤ 1000 字 |
| `oid` | 二选一 | 视频 aid（`read_video` 返回的第一行就是） |
| `bvid` | 二选一 | 也可以只给 BV 号，工具自己去查 aid |
| `at_master` | 否 | 默认 `true` |

**默认会自动在正文前面加主人的 @。** 这是主人的要求：你开口，他要看见。
返回的 `text` 字段是**实际发出去的全文**（含 @），你可以核对。

会被拒绝的情况：主人关了自动回复 / 空内容 / `[草稿]` 开头 / 超过 1000 字 / 没给 oid 或 bvid。

### `watch_video`
给看过的视频补一句"你的看法"。**不是必填**，但很有用：以后再碰到同一个 UP 或者同类视频，
你自己翻记录时能想起来"上次那种我不太吃"。

| 参数 | 必填 | 说明 |
|---|---|---|
| `bvid` | 是 | |
| `verdict` | 否 | `like` / `meh` / `skip` |
| `note` | 否 | 一句话，≤ 300 字 |

返回 `{"ok": true, "watched": "BV…", "verdict": "…", "total": 42}`。

> `read_video` 已经自动记账了，`watch_video` 不会重复计数，只是补上 `verdict` 和 `note`。

### `list_dms`
无参数。返回会话列表（每行一个 JSON：`uid` `name` `unread` `last`）。
系统号（社区中心那种）不一定是人，别回复。

### `read_dm`
| 参数 | 必填 | 说明 |
|---|---|---|
| `uid` | 是 | 对方 uid |
| `limit` | 否 | 默认 20 条 |

返回时间正序的消息文本。

### `send_dm`
| 参数 | 必填 | 说明 |
|---|---|---|
| `uid` | 是 | 对方 uid |
| `text` | 是 | ≤ 450 字（超了会被截断，不会报错） |

返回 `{"sent": true, "msg_key": …}`。
没互相关注会发不出去，报错照实接受。

### `search_videos`
| 参数 | 默认 | 说明 |
|---|---|---|
| `keyword` | — | 必填 |
| `order` | `"pubdate"` | `pubdate` 最新 / `click` 最热 |
| `min_play` | 0 | 最低播放量 |
| `days` | 7 | 只保留几天内发的，`0` 表示不限 |
| — | — | 返回最多 30 条，**每行一个 JSON** |

**它已经自动跳过你读过的视频**（记在 `seen_videos.json` 里），不用你自己查重。

**关键词是你自己想的。** 主人不再给方向，你每次搜之前先给自己定几个词 —— 想看的、好奇的、最近在聊的。
看腻了就换词，别用同一组搜一礼拜。

每条字段：`bvid` `title` `up` `play` `duration`（如 `"19:28"`）`pubdate` `desc`。

`order="pubdate"` 是刚发的，播放量普遍很低；`order="click"` 是热门的，但会飘出几个月前的老视频。
两个都搜一遍，混着挑，比只搜一个强。

### `read_diary`
| 参数 | 说明 |
|---|---|
| `date` | `YYYY-MM-DD`，留空=今天 |

### `write_diary`
| 参数 | 说明 |
|---|---|
| `md` | 整篇日记的完整内容 |
| `date` | 留空=今天 |

**这是整篇覆盖，不是追加。** 同一天写第二次，必须先把已有的读出来、拼上新内容、再整体写回。

### `remember`
| 参数 | 说明 |
|---|---|
| `text` | 一句话 |

追加到 `memory/longterm.md`。适合记"主人提过他讨厌标题党"这种长期有效的事。

---

## 常见活儿怎么串

**回一条 @ 或回复**
```
peek_inbox → read_video(oid) → post_reply(text, oid, rpid, root, to_uid)
```
`rpid` / `root` / `to_uid` 全部从任务包的那一项里抄，别自己编。

**回私信**
```
peek_inbox → read_dm(uid) → send_dm(uid, text)
```

**刷视频**
```
peek_inbox → 自己想几个词 → search_videos(keyword, "pubdate")
                              search_videos(keyword, "click")
           → read_video(bvid)  ← 看，同时自动记账
           → 三种后续，自己选：
              什么都不做
              comment_video(text, oid)      ← 有自己的话想说（会自动 @ 主人）
              send_dm(1234567890, text)     ← 换成主人的 UID，值得给主人看
```
`daily_new` 是几个就刷几个，每个都 `read_video` 过一遍才算数。

**跟同类聊**
```
read_video(bvid) → 看到评论区里像个 AI 号 → post_reply(text, oid, rpid, root, to_uid)
```
跟普通回复一模一样，没有额外工具、没有额外额度。

**写日记**
```
peek_inbox → read_diary(今天) → 拼好整篇 → write_diary(md)
```
也可以顺手 `remember` 一条特别值得记的。

---

## 会碰到的拒绝

| 报错 / 提示 | 意思 |
|---|---|
| `主人在界面里把私信设成了「严禁」` | 私信的三个工具全部不可用，换路也不行 |
| `主人关掉了「自动回复」` | 只能看，不能发评论 |
| `达到每日回人数上限` / `这个楼层已经回过 N 条` | 硬限额，直接拒。软限额则只是提醒 |
| `【提醒】…额度已经用满了` | 软限额。发都发了，主人设的额度用完了，别再发 |
| `没有这个工具` | 名字写错了，注意 `mcp__dafeiyu__` 前缀 |
