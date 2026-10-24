"""
Creator Radar - YouTube fetcher (by category)
博主雷达 - 按类别抓取 YouTube 博主

For each category in config.json: search YouTube by keyword x region,
check each channel's recent videos (length, views, engagement, topic),
pull public contact emails from channel/video descriptions, score them,
and write one table per category plus an explanation page.

对 config.json 里的每个类别：按 关键词 x 地区 搜索，检查频道最近的视频
（时长、播放、互动、内容是否相关），从简介和视频描述里提取公开邮箱，打分，
每个类别输出一张表，并生成说明页 data/README.md。

Needs env var YOUTUBE_API_KEY. Python standard library only.
需要环境变量 YOUTUBE_API_KEY，只用 Python 自带库。
"""

import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")
DATA_PATH = os.path.join(DATA_DIR, "creators.json")
API = "https://www.googleapis.com/youtube/v3/"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com|linktr\.ee|beacons\.ai|x\.com|twitter\.com|tiktok\.com|twitch\.tv)/[^\s)\]>\"']+",
    re.I,
)
DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


class QuotaExceeded(Exception):
    pass


# ---------- API helpers ----------

def api_get(endpoint, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            if e.code == 403 and "quota" in body.lower():
                raise QuotaExceeded(body[:300])
            if e.code == 404:
                return {"items": []}
            if attempt == 2:
                raise RuntimeError(f"{endpoint} failed: {e.code} {body[:300]}")
        except urllib.error.URLError as e:
            if attempt == 2:
                raise RuntimeError(f"{endpoint} network error: {e}")
        time.sleep(2 * (attempt + 1))


def chunks(items, size=50):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def minutes(iso):
    m = DURATION_RE.fullmatch(iso or "")
    if not m:
        return 0.0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return round(d * 1440 + h * 60 + mi + s / 60, 1)


def find_emails(*texts):
    out = []
    for t in texts:
        for e in EMAIL_RE.findall(t or ""):
            e = e.strip(".").lower()
            if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")) or e in out:
                continue
            out.append(e)
    return out[:3]


def find_socials(*texts):
    out = []
    for t in texts:
        for u in SOCIAL_RE.findall(t or ""):
            u = u.rstrip(".,;")
            if u not in out:
                out.append(u)
    return out[:3]


# ---------- Fetching ----------

def search_category(cfg, cat):
    """Return {channel_id: set(keywords)} for one category."""
    published_after = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg["days_back"])
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for kw in cat["keywords"]:
        for region in cfg["regions"]:
            print(f"[{cat['id']}] searching '{kw}' in {region} ...")
            params = dict(
                part="snippet", q=kw, type="video", regionCode=region,
                relevanceLanguage=cfg.get("language", "en"),
                publishedAfter=published_after,
                maxResults=cfg.get("max_results_per_search", 25), order="relevance",
            )
            if cat.get("search_duration"):
                params["videoDuration"] = cat["search_duration"]
            for item in api_get("search", **params).get("items", []):
                found.setdefault(item["snippet"]["channelId"], set()).add(kw)
    return found


def channel_profile(ch, n):
    """Recent-video stats, topic text and contacts for a channel (cached per run)."""
    uploads = ch["contentDetails"]["relatedPlaylists"].get("uploads")
    if not uploads:
        return None
    res = api_get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=n)
    ids = [i["contentDetails"]["videoId"] for i in res.get("items", [])]
    if not ids:
        return None
    vids = api_get("videos", part="statistics,snippet,contentDetails", id=",".join(ids)).get("items", [])
    if not vids:
        return None
    views = [int(v["statistics"].get("viewCount", 0)) for v in vids]
    inter = sum(int(v["statistics"].get("likeCount", 0)) + int(v["statistics"].get("commentCount", 0)) for v in vids)
    durs = [minutes(v["contentDetails"].get("duration")) for v in vids]
    vids_sorted = sorted(vids, key=lambda v: int(v["statistics"].get("viewCount", 0)), reverse=True)
    desc = ch["snippet"].get("description", "")
    video_descs = [v["snippet"].get("description", "") for v in vids]
    return {
        "videos_checked": len(vids),
        "avg_views": round(sum(views) / len(vids)),
        "engagement_rate": round(inter / sum(views), 4) if sum(views) else 0,
        "median_minutes": statistics.median(durs),
        "last_upload": max(v["snippet"]["publishedAt"] for v in vids),
        "top_video": {
            "title": vids_sorted[0]["snippet"]["title"],
            "url": f"https://www.youtube.com/watch?v={vids_sorted[0]['id']}",
            "views": int(vids_sorted[0]["statistics"].get("viewCount", 0)),
        },
        "emails": find_emails(desc, *video_descs),
        "socials": find_socials(desc, *video_descs),
        "_topic_text": " ".join([ch["snippet"]["title"], desc] + [v["snippet"]["title"] for v in vids]).lower(),
    }


def score(c):
    """0-100. Engagement 50, views/subscriber ratio 30, recency 20.
    满分100：互动率50分，播放/粉丝比30分，近期活跃20分。"""
    eng = min(c["engagement_rate"] / 0.05, 1) * 50
    ratio = c["avg_views"] / c["subscribers"] if c["subscribers"] else 0
    reach = min(ratio / 0.3, 1) * 30
    days = (dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(c["last_upload"].replace("Z", "+00:00"))).days
    recency = 20 if days <= 14 else 10 if days <= 30 else 0
    return round(eng + reach + recency, 1)


def country_ok(cfg, country):
    allowed = cfg.get("only_countries") or []
    if not allowed:
        return True
    if not country:
        return cfg.get("keep_unknown_country", True)
    return country in allowed


# ---------- Output ----------

COLUMNS = [
    ("score", "得分 Score"),
    ("name", "博主 Name"),
    ("country", "国家 Country"),
    ("subscribers", "粉丝 Subs"),
    ("avg_views", "平均播放 Avg views"),
    ("engagement_rate", "互动率 Engagement"),
    ("median_minutes", "视频时长(分钟) Typical length (min)"),
    ("emails", "邮箱 Email"),
    ("socials", "其他联系方式 Other contacts"),
    ("bio", "备注：博主简介 Notes: bio"),
    ("top_video", "近期最热视频 Top recent video"),
    ("status", "状态 Status"),
    ("url", "频道链接 Channel"),
]


def cell(c, key):
    v = c.get(key, "")
    if key == "engagement_rate":
        return f"{v * 100:.1f}%"
    if key == "bio":
        v = " ".join(str(v).split())
        return v[:400] + ("…" if len(v) > 400 else "")
    if key == "top_video":
        return f"{v['title']} ({v['views']:,} views) {v['url']}" if v else ""
    if key == "emails":
        return ", ".join(v) if v else "未公开 Not public"
    if isinstance(v, list):
        return ", ".join(v)
    return v


def write_outputs(cfg, creators, now):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now, "count": len(creators), "creators": creators},
                  f, ensure_ascii=False, indent=2)

    # remove the old single table if it exists / 删除旧的总表
    old = os.path.join(DATA_DIR, "creators.csv")
    if os.path.exists(old):
        os.remove(old)

    lines = [
        "# 博主数据说明 Creator data guide",
        "",
        f"最近更新 Last updated: {now[:10]}",
        "",
        "每个类别一张表，点链接打开（GitHub 会显示成表格，也可以下载后用 Excel 打开）。",
        "One table per category. Click to open; GitHub shows it as a table, or download it for Excel.",
        "",
    ]
    for cat in cfg["categories"]:
        rows = sorted((c for c in creators if cat["id"] in c["categories"]),
                      key=lambda c: c["score"], reverse=True)
        fname = f"{cat['id']}.csv"
        with open(os.path.join(DATA_DIR, fname), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([label for _, label in COLUMNS])
            for c in rows:
                w.writerow([cell(c, k) for k, _ in COLUMNS])
        with_email = sum(1 for c in rows if c["emails"])
        rule = f"粉丝 Subs {cat['min_subscribers']:,}–{cat['max_subscribers']:,}"
        if cat.get("min_median_minutes"):
            rule += f"；视频通常 ≥{cat['min_median_minutes']} 分钟 typical video ≥{cat['min_median_minutes']} min"
        lines += [
            f"## [{cat['name']}]({fname})",
            "",
            cat.get("description", ""),
            "",
            f"- 搜索词 Keywords: {', '.join(cat['keywords'])}",
            f"- 条件 Criteria: {rule}",
            f"- 共 {len(rows)} 位博主，其中 {with_email} 位有公开邮箱 / {len(rows)} creators, {with_email} with a public email",
            "",
        ]
    lines += [
        "## 各列说明 Columns",
        "",
        "| 列 Column | 说明 Meaning |",
        "|---|---|",
        "| 得分 Score | 0–100：互动率 50 分 + 平均播放/粉丝 30 分 + 近期活跃 20 分。 Engagement 50 + views÷subs 30 + recent activity 20. |",
        "| 互动率 Engagement | 最近 10 条视频的（点赞+评论）÷ 播放。 (likes+comments) ÷ views over the last 10 videos. |",
        "| 视频时长 Typical length | 最近 10 条视频时长的中位数。 Median length of the last 10 videos. |",
        "| 邮箱 Email | 从频道简介和视频描述里找到的公开邮箱。“未公开”说明需要去频道“关于”页手动点“查看邮箱”。 Public emails found in the channel bio or video descriptions. “Not public” means check the channel's About page manually. |",
        "| 其他联系方式 Other contacts | Instagram、Linktree、X、TikTok 等链接。 Social and link-in-bio links. |",
        "| 备注 Notes | 博主的频道简介。 The channel's own bio. |",
        "| 状态 Status | 默认 new，以后可标记已联系、已合作、不合适。 Default `new`; later: contacted / partnered / not a fit. |",
        "",
    ]
    with open(os.path.join(DATA_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------- Main ----------

def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("Missing YOUTUBE_API_KEY / 缺少 YOUTUBE_API_KEY")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    existing = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            for c in json.load(f).get("creators", []):
                if "categories" in c:  # skip records from the old format / 跳过旧格式数据
                    existing[c["channel_id"]] = c

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    channel_cache, profile_cache = {}, {}
    try:
        for cat in cfg["categories"]:
            hits = search_category(cfg, cat)
            todo = [cid for cid in hits if cid not in channel_cache]
            for batch in chunks(todo):
                for ch in api_get("channels", part="snippet,statistics,contentDetails",
                                  id=",".join(batch)).get("items", []):
                    channel_cache[ch["id"]] = ch
            kept = 0
            for cid, kws in hits.items():
                ch = channel_cache.get(cid)
                if not ch or ch["statistics"].get("hiddenSubscriberCount"):
                    continue
                subs = int(ch["statistics"].get("subscriberCount", 0))
                country = ch["snippet"].get("country", "")
                if not (cat["min_subscribers"] <= subs <= cat["max_subscribers"]) or not country_ok(cfg, country):
                    continue
                if cid not in profile_cache:
                    profile_cache[cid] = channel_profile(ch, cfg.get("recent_videos_to_check", 10))
                prof = profile_cache[cid]
                if not prof or prof["median_minutes"] < cat.get("min_median_minutes", 0):
                    continue
                terms = cat.get("must_match_any") or []
                if terms and not any(t.lower() in prof["_topic_text"] for t in terms):
                    continue

                old = existing.get(cid, {})
                c = {
                    "channel_id": cid,
                    "name": ch["snippet"]["title"],
                    "url": f"https://www.youtube.com/channel/{cid}",
                    "country": country,
                    "bio": ch["snippet"].get("description", ""),
                    "subscribers": subs,
                    **{k: v for k, v in prof.items() if not k.startswith("_")},
                    "categories": sorted(set(old.get("categories", [])) | {cat["id"]}),
                    "matched_keywords": sorted(set(old.get("matched_keywords", [])) | kws),
                    "first_seen": old.get("first_seen", now),
                    "last_updated": now,
                    "status": old.get("status", "new"),
                    "notes": old.get("notes", ""),
                }
                c["score"] = score(c)
                existing[cid] = c
                kept += 1
            print(f"[{cat['id']}] kept {kept} of {len(hits)} channels")
    except QuotaExceeded as e:
        print(f"Daily API quota used up, saving what we have. / 今日配额用完，先保存已有数据。\n{e}")

    creators = sorted(existing.values(), key=lambda c: c["score"], reverse=True)
    write_outputs(cfg, creators, now)
    print(f"Saved {len(creators)} creators across {len(cfg['categories'])} categories")


if __name__ == "__main__":
    main()
