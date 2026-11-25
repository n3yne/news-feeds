#!/usr/bin/env python3
"""Maintain RSS 2.0 news feeds from batches of new items. Standard library only.

The state file (state/<feed>.json) is the source of truth. The feed XML is
regenerated from it on every run, so the feed can never drift out of sync.

Commands
  add     --feed AI --input items.json   add new items, skipping duplicates
  recent  --feed AI [--days 7]           list recent titles and links (for duplicate checks)
  stats   --feed AI                      counts used by the empty-day alert
  rebuild --feed AI                      regenerate the feed from state (also trims)

Input for `add` is a JSON array of objects, ranked most significant first:
  title        headline (required)
  description  1 to 3 plain-text sentences (required)
  link         URL of the most authoritative source (required)
  source_name  outlet name for the primary link (optional)
  sources      other outlets covering the same story: [{"name": "...", "url": "..."}]
  published    ISO 8601 time of the original report (optional, defaults to now)
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ZONE = ZoneInfo("America/New_York")
FEED_RETENTION_DAYS = 30    # items older than this leave the feed
STATE_RETENTION_DAYS = 90   # duplicate memory outlives the feed on purpose
HARD_CAP_PER_RUN = 8
TITLE_SIMILARITY = 0.8      # token overlap that counts as the same headline

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "cmp", "ocid", "taid", "igshid"}
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by", "with", "from",
    "is", "are", "was", "were", "be", "as", "it", "its", "this", "that", "new", "says", "say",
    "after", "over", "about", "into", "than", "will", "has", "have", "its",
}


def canon_url(url):
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


def tokens(title):
    return {t for t in re.findall(r"[a-z0-9]+", title.lower()) if t not in STOPWORDS and len(t) > 1}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_time(value, default):
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return default
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Feed:
    def __init__(self, root, name):
        self.root = Path(root)
        self.name = name
        cfg = json.loads((self.root / "config" / "feeds.json").read_text())
        if name not in cfg:
            sys.exit(f"Unknown feed {name!r}; add it to config/feeds.json")
        self.cfg = cfg[name]
        self.state_path = self.root / "state" / f"{name}.json"
        self.feed_path = self.root / "feeds" / f"{name}.rss"
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        else:
            self.state = {"items": []}

    # ---- duplicate index -------------------------------------------------
    def url_index(self):
        index = {}
        for item in self.state["items"]:
            for u in [item["link"]] + [s["url"] for s in item.get("sources", [])]:
                index[canon_url(u)] = item["id"]
        return index

    # ---- add -------------------------------------------------------------
    def add(self, incoming, now):
        urls = self.url_index()
        token_sets = [(it["id"], set(it["tokens"])) for it in self.state["items"]]
        added, skipped, merged = [], [], []
        by_id = {}

        for raw in incoming:
            missing = [k for k in ("title", "description", "link") if not str(raw.get(k, "")).strip()]
            if missing:
                skipped.append({"title": raw.get("title", "?"), "reason": f"missing {', '.join(missing)}"})
                continue
            title = raw["title"].strip()
            link = raw["link"].strip()
            extra = [s for s in raw.get("sources", []) if s.get("url")]
            all_urls = [canon_url(link)] + [canon_url(s["url"]) for s in extra]
            tset = tokens(title)

            hit = next((urls[u] for u in all_urls if u in urls), None)
            if hit is None:
                hit = next((i for i, ts in token_sets if jaccard(tset, ts) >= TITLE_SIMILARITY), None)
                reason = "similar headline already in feed"
            else:
                reason = "url already in feed"

            if hit is not None:
                if hit in by_id:
                    # Same story as one accepted earlier in this batch: fold sources in.
                    target = by_id[hit]
                    known = {canon_url(target["link"])} | {canon_url(s["url"]) for s in target["sources"]}
                    pool = [{"name": raw.get("source_name") or urlsplit(link).netloc, "url": link}] + extra
                    new_sources = [s for s in pool if canon_url(s["url"]) not in known]
                    target["sources"].extend(new_sources)
                    for s in new_sources:
                        urls[canon_url(s["url"])] = target["id"]
                    merged.append({"title": title, "into": target["title"]})
                else:
                    skipped.append({"title": title, "reason": reason})
                continue

            if len(added) >= HARD_CAP_PER_RUN:
                skipped.append({"title": title, "reason": f"hard cap of {HARD_CAP_PER_RUN} per run"})
                continue

            item_id = hashlib.sha1(canon_url(link).encode()).hexdigest()[:16]
            entry = {
                "id": item_id,
                "title": title,
                "description": raw["description"].strip(),
                "link": link,
                "source_name": (raw.get("source_name") or urlsplit(link).netloc.removeprefix("www.")).strip(),
                "sources": extra,
                "published": parse_time(raw.get("published"), now).astimezone(timezone.utc).isoformat(),
                "added": now.isoformat(),
                "tokens": sorted(tset),
            }
            added.append(entry)
            by_id[item_id] = entry
            token_sets.append((item_id, tset))
            for u in all_urls:
                urls[u] = item_id

        self.state["items"].extend(added)
        return added, skipped, merged

    # ---- trim and write --------------------------------------------------
    def trim(self, now):
        cutoff = now - timedelta(days=STATE_RETENTION_DAYS)
        before = len(self.state["items"])
        self.state["items"] = [i for i in self.state["items"] if parse_time(i["added"], now) >= cutoff]
        return before - len(self.state["items"])

    def feed_items(self, now):
        cutoff = now - timedelta(days=FEED_RETENTION_DAYS)
        items = [i for i in self.state["items"] if parse_time(i["added"], now) >= cutoff]
        return sorted(items, key=lambda i: i["published"], reverse=True)

    def render(self, now):
        def cdata(text):
            return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"

        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
            "<channel>",
            f"<title>{escape(self.cfg['title'])}</title>",
            f"<link>{escape(self.cfg['link'])}</link>",
            f"<description>{escape(self.cfg['description'])}</description>",
            "<language>en-us</language>",
            f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
            f'<atom:link href="{escape(self.cfg["feed_url"])}" rel="self" type="application/rss+xml"/>',
        ]
        for item in self.feed_items(now):
            links = [f'<a href="{escape(item["link"])}">{escape(item["source_name"])}</a> (primary)']
            links += [f'<a href="{escape(s["url"])}">{escape(s.get("name") or urlsplit(s["url"]).netloc)}</a>'
                      for s in item.get("sources", [])]
            body = f"<p>{escape(item['description'])}</p><p>Sources: {', '.join(links)}</p>"
            out += [
                "<item>",
                f"<title>{escape(item['title'])}</title>",
                f"<link>{escape(item['link'])}</link>",
                f'<guid isPermaLink="false">{item["id"]}</guid>',
                f"<pubDate>{format_datetime(parse_time(item['published'], now))}</pubDate>",
                f"<description>{cdata(body)}</description>",
                "</item>",
            ]
        out += ["</channel>", "</rss>", ""]
        return "\n".join(out)

    def save(self, now):
        xml = self.render(now)
        ET.fromstring(xml.encode("utf-8"))  # refuse to write malformed XML
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1, ensure_ascii=False) + "\n")
        self.feed_path.write_text(xml)


def main():
    default_root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["add", "recent", "stats", "rebuild"])
    ap.add_argument("--feed", required=True)
    ap.add_argument("--input")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--root", default=str(default_root))
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    feed = Feed(args.root, args.feed)

    if args.command == "add":
        if not args.input:
            sys.exit("--input is required for add")
        incoming = json.loads(Path(args.input).read_text())
        added, skipped, merged = feed.add(incoming, now)
        trimmed = feed.trim(now)
        feed.save(now)
        print(json.dumps({
            "added": [{"title": a["title"], "link": a["link"]} for a in added],
            "skipped": skipped,
            "merged": merged,
            "state_items_pruned": trimmed,
            "items_in_feed": len(feed.feed_items(now)),
        }, indent=1))
    elif args.command == "recent":
        cutoff = now - timedelta(days=args.days)
        rows = [i for i in feed.state["items"] if parse_time(i["added"], now) >= cutoff]
        for i in sorted(rows, key=lambda i: i["added"], reverse=True):
            print(f"{i['added'][:16]}Z | {i['title']} | {i['link']}")
    elif args.command == "stats":
        today = now.astimezone(ZONE).date()
        added_today = sum(1 for i in feed.state["items"]
                          if parse_time(i["added"], now).astimezone(ZONE).date() == today)
        last_24h = sum(1 for i in feed.state["items"]
                       if parse_time(i["added"], now) >= now - timedelta(hours=24))
        print(json.dumps({
            "added_today_eastern": added_today,
            "added_last_24h": last_24h,
            "items_in_feed": len(feed.feed_items(now)),
            "items_in_state": len(feed.state["items"]),
        }))
    elif args.command == "rebuild":
        trimmed = feed.trim(now)
        feed.save(now)
        print(json.dumps({"state_items_pruned": trimmed, "items_in_feed": len(feed.feed_items(now))}))


if __name__ == "__main__":
    main()
