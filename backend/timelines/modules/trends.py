"""Trend Research Engine (YouTube Data API v3, API key in YOUTUBE_API_KEY).

Metrics use only public data: views/subscriber, views/day, age, upload frequency, channel median,
topic frequency. Growth rates are computed ONLY from >= 2 stored snapshots of the same video;
CTR / retention of other channels are never estimated.
"""
from __future__ import annotations

import os
import re
import statistics
from collections import Counter
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from .. import db

API = "https://www.googleapis.com/youtube/v3"
SEED_CHANNELS = ["@AlternateHistoryHub", "@PossibleHistory", "@HistoryMatters", "@FallofCivilizations",
                 "@toldinstone", "@Historyin3D", "@RomeUnscrolled", "@AlterHistory"]
STOP = set("the a an of in and to what if was is how why did for on with from his her their by at".split())


def status() -> dict:
    if os.environ.get("YOUTUBE_API_KEY"):
        return {"configured": True, "reason": "YOUTUBE_API_KEY set"}
    return {"configured": False, "reason": "YOUTUBE_API_KEY is not set (.env). No data is shown until real data is collected."}


def _get(path: str, **params) -> dict:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError(status()["reason"])
    r = httpx.get(f"{API}/{path}", params={**params, "key": key}, timeout=30)
    r.raise_for_status()
    return r.json()


def _iso_duration(s: str) -> float:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0.0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def add_channel(handle_or_id: str) -> dict:
    q = {"id": handle_or_id} if handle_or_id.startswith("UC") else {"forHandle": handle_or_id.lstrip("@")}
    items = _get("channels", part="snippet,statistics,contentDetails", **q).get("items", [])
    if not items:
        raise ValueError(f"channel not found: {handle_or_id}")
    it = items[0]
    with db.session() as s:
        row = s.get(db.Channel, it["id"]) or db.Channel(channel_id=it["id"])
        row.title, row.handle = it["snippet"]["title"], handle_or_id
        row.subscribers = int(it["statistics"].get("subscriberCount", 0)) if not it["statistics"].get("hiddenSubscriberCount") else None
        row.video_count = int(it["statistics"].get("videoCount", 0))
        row.collected_at = db.now()
        s.merge(row)
        s.commit()
    return {"channel_id": it["id"], "uploads": it["contentDetails"]["relatedPlaylists"]["uploads"]}


def collect(progress=None, max_videos_per_channel: int = 50, min_duration_s: float = 240) -> dict:
    """Snapshot the latest long-form uploads of every registered channel (each run adds snapshots)."""
    with db.session() as s:
        channels = list(s.scalars(select(db.Channel)))
    if not channels:
        for h in SEED_CHANNELS:
            try:
                add_channel(h)
            except Exception:  # noqa: BLE001 - a missing handle should not stop the batch
                continue
        with db.session() as s:
            channels = list(s.scalars(select(db.Channel)))
    total = 0
    for i, ch in enumerate(channels):
        info = add_channel(ch.channel_id)
        ids, token = [], None
        while len(ids) < max_videos_per_channel:
            page = _get("playlistItems", part="contentDetails", playlistId=info["uploads"], maxResults=50,
                        **({"pageToken": token} if token else {}))
            ids += [x["contentDetails"]["videoId"] for x in page.get("items", [])]
            token = page.get("nextPageToken")
            if not token:
                break
        for k in range(0, len(ids), 50):
            vids = _get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[k:k + 50]))
            with db.session() as s:
                subs = s.get(db.Channel, ch.channel_id).subscribers
                for v in vids.get("items", []):
                    dur = _iso_duration(v["contentDetails"]["duration"])
                    if dur < min_duration_s:
                        continue
                    st = v["statistics"]
                    s.add(db.VideoSnapshot(video_id=v["id"], channel_id=ch.channel_id, title=v["snippet"]["title"],
                                           published_at=datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00")),
                                           duration_s=dur, views=int(st.get("viewCount", 0)),
                                           likes=int(st["likeCount"]) if "likeCount" in st else None,
                                           comments=int(st["commentCount"]) if "commentCount" in st else None,
                                           subscribers_at_capture=subs))
                    total += 1
                s.commit()
        if progress:
            progress((i + 1) / len(channels), f"{ch.title}: {len(ids)} uploads scanned")
    return {"channels": len(channels), "snapshots_added": total}


def videos() -> list[dict]:
    with db.session() as s:
        snaps = list(s.scalars(select(db.VideoSnapshot).order_by(db.VideoSnapshot.captured_at)))
        chans = {c.channel_id: c for c in s.scalars(select(db.Channel))}
    by_vid: dict[str, list] = {}
    for sn in snaps:
        by_vid.setdefault(sn.video_id, []).append(sn)
    now = datetime.now(timezone.utc)
    out = []
    for vid, rows in by_vid.items():
        last = rows[-1]
        pub = last.published_at if last.published_at.tzinfo else last.published_at.replace(tzinfo=timezone.utc)
        age = max((now - pub).total_seconds() / 86400, 1e-3)
        growth = None
        if len(rows) >= 2:
            first = rows[0]
            span = (last.captured_at - first.captured_at).total_seconds() / 86400
            if span > 0.5:
                growth = round((last.views - first.views) / span, 1)
        subs = last.subscribers_at_capture
        out.append({"video_id": vid, "channel_title": chans.get(last.channel_id).title if last.channel_id in chans else "",
                    "title": last.title, "published_at": pub.isoformat(), "duration_s": last.duration_s,
                    "views": last.views, "age_days": round(age, 1), "views_per_day": round(last.views / age, 1),
                    "views_per_subscriber": round(last.views / subs, 3) if subs else None, "growth_per_day": growth})
    return sorted(out, key=lambda r: -r["views_per_day"])


def summary() -> dict:
    vids = videos()
    by_ch: dict[str, list] = {}
    for v in vids:
        by_ch.setdefault(v["channel_title"], []).append(v)
    channels = {}
    for name, rows in by_ch.items():
        dates = sorted(datetime.fromisoformat(r["published_at"]) for r in rows)
        span_w = max((dates[-1] - dates[0]).days / 7, 1) if len(dates) > 1 else None
        channels[name] = {"median_views": statistics.median(r["views"] for r in rows),
                          "uploads_per_week": round(len(rows) / span_w, 2) if span_w else None, "videos": len(rows)}
    words = Counter(w for v in vids for w in re.findall(r"[a-z]+", v["title"].lower()) if w not in STOP and len(w) > 2)
    return {"channels": channels, "topic_terms": words.most_common(40), "videos": len(vids)}
