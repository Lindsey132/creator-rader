"""
Creator Radar - YouTube fetcher
博主雷达 - YouTube 数据抓取脚本

Searches YouTube by keyword x region, collects channels, computes
engagement metrics from their recent uploads, scores them, and merges
the results into data/creators.json.

按 关键词 x 地区 搜索 YouTube，收集频道，用最近的视频计算互动数据并打分，
结果合并保存到 data/creators.json。

Needs env var YOUTUBE_API_KEY. Uses only the Python standard library.
需要环境变量 YOUTUBE_API_KEY，只用 Python 自带库，不用安装依赖。
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_PATH = os.path.join(ROOT, "data", "creators.json")
API = "https://www.googleapis.com/youtube/v3/"


class QuotaExceeded(Exception):
    pass


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


def search_channels(cfg):
    """Return {channel_id: {"keywords": set, "regions": set}}"""
    published_after = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg["days_back"])
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for kw in cfg["keywords"]:
        for region in cfg["regions"]:
            print(f"Searching '{kw}' in {region} ...")
            res = api_get(
                "search",
                part="snippet",
                q=kw,
                type="video",
                regionCode=region,
                relevanceLanguage=cfg.get("language", "en"),
                publishedAfter=published_after,
                maxResults=cfg.get("max_results_per_search", 25),
                order="relevance",
            )
            for item in res.get("items", []):
                cid = item["snippet"]["channelId"]
                hit = found.setdefault(cid, {"keywords": set(), "regions": set()})
                hit["keywords"].add(kw)
                hit["regions"].add(region)
    return found


def recent_video_stats(uploads_playlist, n):
    res = api_get("playlistItems", part="contentDetails",
                  playlistId=uploads_playlist, maxResults=n)
    ids = [i["contentDetails"]["videoId"] for i in res.get("items", [])]
    if not ids:
        return None
    vids = api_get("videos", part="statistics,snippet", id=",".join(ids)).get("items", [])
    if not vids:
        return None
    views = [int(v["statistics"].get("viewCount", 0)) for v in vids]
    likes = [int(v["statistics"].get("likeCount", 0)) for v in vids]
    comments = [int(v["statistics"].get("commentCount", 0)) for v in vids]
    dates = sorted(v["snippet"]["publishedAt"] for v in vids)
    total_views = sum(views)
    return {
        "videos_checked": len(vids),
        "avg_views": round(total_views / len(vids)),
        "avg_likes": round(sum(likes) / len(vids)),
        "avg_comments": round(sum(comments) / len(vids)),
        "engagement_rate": round((sum(likes) + sum(comments)) / total_views, 4) if total_views else 0,
        "last_upload": dates[-1],
        "recent_videos": [
            {"title": v["snippet"]["title"],
             "url": f"https://www.youtube.com/watch?v={v['id']}",
             "views": int(v["statistics"].get("viewCount", 0)),
             "published": v["snippet"]["publishedAt"]}
            for v in sorted(vids, key=lambda x: x["snippet"]["publishedAt"], reverse=True)[:3]
        ],
    }


def score(c):
    """0-100. Engagement 50 pts, views/subscriber ratio 30 pts, recency 20 pts.
    满分100：互动率50分，播放/粉丝比30分，最近更新20分。"""
    eng = min(c["engagement_rate"] / 0.05, 1) * 50          # 5%+ engagement = full marks
    ratio = c["avg_views"] / c["subscribers"] if c["subscribers"] else 0
    reach = min(ratio / 0.3, 1) * 30                          # avg views >= 30% of subs = full
    days = (dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(c["last_upload"].replace("Z", "+00:00"))).days
    recency = 20 if days <= 14 else 10 if days <= 30 else 0
    return round(eng + reach + recency, 1)


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("Missing YOUTUBE_API_KEY / 缺少 YOUTUBE_API_KEY")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    existing = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            for c in json.load(f).get("creators", []):
                existing[c["channel_id"]] = c

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        hits = search_channels(cfg)
        print(f"Found {len(hits)} channels; fetching details ...")
        for batch in chunks(list(hits)):
            res = api_get("channels", part="snippet,statistics,contentDetails", id=",".join(batch))
            for ch in res.get("items", []):
                st = ch["statistics"]
                if st.get("hiddenSubscriberCount"):
                    continue
                subs = int(st.get("subscriberCount", 0))
                if not (cfg["min_subscribers"] <= subs <= cfg["max_subscribers"]):
                    continue
                uploads = ch["contentDetails"]["relatedPlaylists"].get("uploads")
                stats = recent_video_stats(uploads, cfg.get("recent_videos_to_check", 10)) if uploads else None
                if not stats:
                    continue
                cid = ch["id"]
                old = existing.get(cid, {})
                hit = hits[cid]
                creator = {
                    "channel_id": cid,
                    "name": ch["snippet"]["title"],
                    "url": f"https://www.youtube.com/channel/{cid}",
                    "custom_url": ch["snippet"].get("customUrl", ""),
                    "country": ch["snippet"].get("country", ""),
                    "description": ch["snippet"].get("description", "")[:300],
                    "thumbnail": ch["snippet"]["thumbnails"]["default"]["url"],
                    "subscribers": subs,
                    "total_videos": int(st.get("videoCount", 0)),
                    **stats,
                    "matched_keywords": sorted(set(old.get("matched_keywords", [])) | hit["keywords"]),
                    "matched_regions": sorted(set(old.get("matched_regions", [])) | hit["regions"]),
                    "first_seen": old.get("first_seen", now),
                    "last_updated": now,
                    # Fields you edit by hand are kept / 你手动填写的字段会保留
                    "status": old.get("status", "new"),
                    "notes": old.get("notes", ""),
                }
                creator["score"] = score(creator)
                existing[cid] = creator
                print(f"  + {creator['name']}  subs={subs}  score={creator['score']}")
    except QuotaExceeded as e:
        print(f"Daily API quota used up, saving what we have. / 今日配额用完，先保存已有数据。\n{e}")

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    creators = sorted(existing.values(), key=lambda c: c["score"], reverse=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now, "count": len(creators), "creators": creators},
                  f, ensure_ascii=False, indent=2)
    write_csv(creators)
    print(f"Saved {len(creators)} creators to data/creators.json and data/creators.csv")


def write_csv(creators):
    """Human-readable table; GitHub shows .csv files as a searchable table.
    方便阅读的表格，GitHub 会把 .csv 显示成可搜索的表格。"""
    import csv
    cols = [("score", "得分 Score"), ("name", "博主 Name"), ("country", "国家 Country"),
            ("subscribers", "粉丝 Subs"), ("avg_views", "平均播放 Avg views"),
            ("engagement_rate", "互动率 Engagement"), ("last_upload", "最近更新 Last upload"),
            ("matched_keywords", "关键词 Keywords"), ("status", "状态 Status"),
            ("notes", "备注 Notes"), ("url", "链接 Link")]
    path = os.path.join(os.path.dirname(DATA_PATH), "creators.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig so Excel shows Chinese correctly
        w = csv.writer(f)
        w.writerow([label for _, label in cols])
        for c in creators:
            row = []
            for key, _ in cols:
                v = c.get(key, "")
                if key == "engagement_rate":
                    v = f"{v * 100:.1f}%"
                elif key == "last_upload":
                    v = str(v)[:10]
                elif isinstance(v, list):
                    v = ", ".join(v)
                row.append(v)
            w.writerow(row)


if __name__ == "__main__":
    main()
