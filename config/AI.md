# AI feed settings

Edit this file to tune what the AI feed collects. The scheduled task reads it at the start of every run, so changes apply on the next run without touching the task prompt.

## Scope

Broad: anything newsworthy about artificial intelligence, including:
- model and product releases and updates
- company news, funding, acquisitions, leadership changes
- policy, regulation, legal cases, and safety
- research results and notable papers
- chips, data centers, and compute
- notable uses and incidents involving AI

Ignore: sponsored posts, listicles, opinion pieces with no new facts, and rewrites of older stories with no new development.

## Preferred sources

Prefer these when choosing the primary link for a story. Add one per line.

- (none yet)

## Excluded sources

Never use these as a primary link, and do not add a story whose only coverage is from them. Add one per line.

- (none yet)

## Significance and caps

- Window: stories published in the last 24 hours.
- Soft target: about 2 stories per run. Add fewer if little happened.
- Hard cap: 8 stories per run, reserved for days with big news. The script enforces this.
- Runs happen every 2 hours from 6 AM to 10 PM Eastern, so the daily ceiling is 72 stories. There is no daily cap beyond that.
- Rank by importance: a major release, a large deal, a ruling, or a safety incident beats a minor update.

## Duplicates

- Several outlets reporting the same event become one entry, with the most authoritative outlet as the main link and the others listed as additional sources.
- A story already in the feed is skipped.
- A major new development in an old story (for example a court ruling after an earlier announcement) counts as a new entry. A follow-up with no new facts does not.
