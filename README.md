# news-feeds

Topic news feeds in RSS 2.0, updated by a Claude scheduled task.

| Feed | URL |
| --- | --- |
| AI | https://n3yne.github.io/news-feeds/feeds/AI.rss |

## Layout

- `feeds/<name>.rss`: the published feed, regenerated on every run
- `state/<name>.json`: every item seen in the last 90 days. This is the source of truth and the duplicate memory.
- `config/<name>.md`: scope, preferred sources, excluded sources, and caps for a feed
- `config/feeds.json`: feed title, description, and URLs
- `scripts/update_feed.py`: adds items, skips duplicates, trims old items, writes valid XML

## Retention

- Items stay in the feed for 30 days.
- Duplicate memory lasts 90 days, so a story that has left the feed is not re-added while outlets still cover it.

## Adding a feed

1. Add an entry to `config/feeds.json`.
2. Create `config/<name>.md` from `config/AI.md`.
3. Create a scheduled task that uses `--feed <name>`.
