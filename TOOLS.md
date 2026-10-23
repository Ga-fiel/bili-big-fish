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
| `root_text` | string | 楼层根/被回复的那条评论原文。这是**哨兵任务包里**预先查好带上的；`list_mentions` 工具本身不查，只给 id |
| `uri` | string | 视频链接，`BV…` 从里面看 |
| `bvid` | string | 可能为空 |
| `at` | int | 时间戳（秒）。私信项没有这个字段 |
| `ts` | int | 只有 `dm` 项有，私信时间戳 |

**`dm` 项长得不一样**，没有 `rpid`/`oid`/`root`/`at`：

```json
{ "kind": "dm", "from_uid": 123456789, "from_name": "主人",
  "text": "（2 条未读）肥鱼肥鱼肥鱼", "ts": 1792674422 }
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

## 二十七个工具

### `peek_inbox`
无参数。返回最新任务包 JSON。没有包时返回一句话说明。

### `get_policy`
无参数。返回主人全部设定和今天额度用了多少。任务包里的 `policy` 就是它，懒得翻包时用。

### `list_mentions`
| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 20 | 最多几条 |
| `kinds` | `"at,reply"` | 逗号分隔，可选 `at` `reply` |

返回**每行一个 JSON**（不是数组），字段：
`kind / rpid / oid / root / parent / from_uid / from_name / text / uri / at`。

- `rpid` 是对方**这一条**的 id；`parent` 是它直接回复的那条；`root` 是楼层根。
- `at` 消息里，`parent`/`root` 都是它所在的楼层根（B 站 AT 只给 `target_id`）。
- **它不替你查评论内容**。想知道「楼主是谁、说了什么」，拿 `oid` + `root` 去调 `get_comment` 或 `list_thread`。
- 已经按你的态度档过滤过：`forbid` 的类别根本不会出现。已经回过的不会消失，自己看 `at` 判断。

### `get_comment`
| 参数 | 必填 | 说明 |
|---|---|---|
| `oid` | 是 | 视频 aid |
| `rpid` | 是 | 评论 id（楼层根或楼里任意一条都行） |

返回 JSON：`found`、`target`（这条评论：rpid/oid/root/parent/user/mid/content/ctime）、`floor`（楼层根，也就是楼主那条）、`floor_is_target`。
`target.oid` 能直接拿去 `post_reply`；`target.parent` 就是它回复的那条。

### `list_thread`
| 参数 | 必填 | 说明 |
|---|---|---|
| `oid` | 是 | 视频 aid |
| `root` | 是 | 楼层根 rpid |
| `pn` | 否 | 页码，默认 1 |
| `ps` | 否 | 每页条数，默认 20，上限 50 |

返回 JSON：`root`（楼层根 = 楼主）、`replies`（这楼的回复列表）、`page`。
每条回复字段：`rpid/oid/root/parent/user/mid/content/ctime`。
楼中楼想看清顺序，就按 `parent` 串：`parent` 指谁，谁就是它回复的人。

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

**默认会自动在正文前面加 `@主人 `。** 这是主人的要求：你开口，他要看见。
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

### `like_video`
给视频点赞 / 取消点赞。

| 参数 | 必填 | 说明 |
|---|---|---|
| `bvid` | 二选一 | 例如 `BV16KnN6KEwo` |
| `oid` | 二选一 | 视频 aid |
| `undo` | 否 | `true` = 取消点赞，默认 `false` |

返回 `{"liked": true/false, "bvid": …, "res": …}`。

### `coin_video`
给视频投币。**硬币是真钱，投出去不回来。**

| 参数 | 必填 | 说明 |
|---|---|---|
| `bvid` / `oid` | 二选一 | 同 `like_video` |
| `num` | 否 | 1 或 2 枚，默认 1 |
| `also_like` | 否 | 投币同时点赞，默认 `false` |

返回 `{"coins": 1, "also_like": false, "res": …}`。硬币不够或已经投过会报错。

### `list_fav_folders`
无参数。列出自己的收藏夹，每项 `media_id` `title` `count` `privacy`。
`folder_id` 就是这里的 `media_id`。

### `list_fav_medias`
| 参数 | 必填 | 说明 |
|---|---|---|
| `media_id` | 是 | 收藏夹 id（从 `list_fav_folders` 拿） |
| `page` | 否 | 第几页，默认 1 |

返回每项 `bvid` `title` `up` `fav_time`。

### `create_fav_folder`
新建一个收藏夹。

| 参数 | 必填 | 说明 |
|---|---|---|
| `title` | 是 | 收藏夹名字 |
| `privacy` | 否 | `0` 公开 / `1` 私密，默认 `0` |

返回 `{"media_id": 新收藏夹 id, "title": …}`。

### `delete_fav_folder`
删掉一个收藏夹，**里面的收藏会一起没**。

| 参数 | 必填 | 说明 |
|---|---|---|
| `media_id` | 是 | 收藏夹 id |

返回 `{"deleted_media_id": …}`。

### `favorite_video`
把视频收藏进收藏夹，或从收藏夹移出。

| 参数 | 必填 | 说明 |
|---|---|---|
| `bvid` / `oid` | 二选一 | 视频 |
| `folder_id` | 是 | 收藏夹 id |
| `undo` | 否 | `true` = 从收藏夹移出，默认 `false` |

返回 `{"added": true/false, "folder_id": …}`。

### `view_user`
看一个人的主页：昵称、签名、等级、粉丝数，加上他最新发的视频。

| 参数 | 必填 | 说明 |
|---|---|---|
| `uid` | 是 | 对方 uid |
| `limit` | 否 | 取几个视频，默认 20，最多 30 |

返回 `{"uid", "name", "sign", "level", "fans", "videos": [{bvid, title, play, created}]}`。

### `send_dynamic`
发一条动态。就这一件事——没有夹带的参数、没有额度和开关。

| 参数 | 必填 | 说明 |
|---|---|---|
| `text` | 是 | 正文，≤ 2000 字。以 `[草稿]` 开头的会被拒 |

返回 `{"sent": true, "dyn_id": …, "dyn_id_str": "…", "url": "https://t.bilibili.com/…", "raw": {…}}`。
- `dyn_id` 记好，以后要删这条动态就靠它。
- `url` 是这条动态的网页地址。
- 想在动态里 @ 谁，就在正文里自己写 `@昵称`，工具不会替你加。

发不发、什么时候发、写什么，都是你自己的事。

### `delete_dynamic`
删掉自己的一条动态。

| 参数 | 必填 | 说明 |
|---|---|---|
| `dyn_id` | 是 | `send_dynamic` 返回的那个 id |

返回 `{"deleted": true, "dyn_id": …, "raw": {…}}`。只能删自己的。

### `delete_comment`
删掉自己在视频底下发的一条评论（主楼、楼中楼都行）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `oid` | 是 | 评论所在视频的 aid |
| `rpid` | 是 | 要删的那条评论 id |

返回 `{"deleted": true, "oid": …, "rpid": …, "raw": {…}}`。
只能删自己的，删别人的 B站 会拒绝。

---

## 常见活儿怎么串

**回一条 @ 或回复**
```
peek_inbox → read_video(oid) → post_reply(text, oid, rpid, root, to_uid)
```
`rpid` / `root` / `to_uid` 全部从任务包的那一项里抄，别自己编。

**想知道「楼主是谁、说了什么」**

```
list_mentions → 拿到 oid/root → get_comment(oid, rpid)   ← 单条：它的 parent、楼层根和楼主
                             → list_thread(oid, root)    ← 整楼：楼主 + 这楼所有回复
```
`at` 和 `reply` 消息的 `root` 都是楼层根，不用猜。`parent` 是它直接回复的那条。

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
              send_dm(主人的uid, text)      ← 值得给主人看
```
`daily_new` 是几个就刷几个，每个都 `read_video` 过一遍才算数。

**写日记**

```
peek_inbox → read_diary(今天) → 拼好整篇 → write_diary(md)
```
也可以顺手 `remember` 一条特别值得记的。

**看一个人、看他的视频**

```
view_user(uid) → 里面每条都有 bvid → read_video(bvid)
```

**收藏一个视频**

```
list_fav_folders → 没有合适的就 create_fav_folder("大肥鱼喜欢的")
                 → favorite_video(bvid, folder_id=…)
```

**点赞 / 投币**

```
like_video(bvid)                    ← 喜欢就点，点错了 undo=true
coin_video(bvid, num=1)             ← 硬币是真钱，想清楚再投
coin_video(bvid, num=1, also_like=true)  ← 投币顺带点赞
```

**发动态 / 删动态**

```
send_dynamic("今天刷到一个视频……")     ← 发出去，返回里有 dyn_id
delete_dynamic(dyn_id)                  ← 想删就用这个
```

**删自己的评论**

```
delete_comment(oid, rpid)               ← rpid 就是当初发评论时返回的那个
```

---

## 会碰到的拒绝

| 报错 / 提示 | 意思 |
|---|---|
| `主人在界面里把私信设成了「严禁」` | 私信的三个工具全部不可用，换路也不行 |
| `主人关掉了「自动回复」` | 只能看，不能发评论 |
| `达到每日回人数上限` / `这个楼层已经回过 N 条` | 硬限额，直接拒。软限额则只是提醒 |
| `【提醒】…额度已经用满了` | 软限额。发都发了，主人设的额度用完了，别再发 |
| `没有这个工具` | 名字写错了，注意 `mcp__dafeiyu__` 前缀 |
