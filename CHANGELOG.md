# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-19

### Added

- `Opponent.live_score`: running series score of unfinished matches (only real values
  >= 0; `score` stays `None` until the match is finished).

- `LiquipediaClient` for the LPDB v3 API (`match`, `standingstable`, `standingsentry`)
  with a 60 requests/hour sliding-window budget (can only be lowered), a lockout after
  HTTP 429, no automatic retries, a size-bounded TTL cache with negative caching,
  mandatory identifying User-Agent and redacted API key handling.
- Match queries: results, upcoming matches, time ranges across several wikis, and match
  details with per-game scores, overtime, length, kills, maps, MVPs and League of
  Legends champion picks.
- Standings by team (finds the current phase and the next one) or by exact tournament
  name, handling per-round rows, not-started tables and Bo1 Swiss records.
- Input validation against LPDB condition injection.
- English text formatter and MCP server (`liquipedia-mcp`, stdio or local streamable
  HTTP) with five read-only tools.
- Liquipedia attribution (CC-BY-SA 3.0) on every result.
- `include_minor_types` option for results, upcoming matches and time ranges.

### Fixed

- Tier filters no longer let unranked events (`liquipediatier` `-1`) through as
  "S-Tier": the condition lists tiers explicitly
  (`([[liquipediatier::1]] OR [[liquipediatier::2]])`) and parsed matches outside
  `1..max_tier` are dropped. Qualifiers, showmatches, weeklies and other minor tier types
  are left out of tier-filtered queries by default.
- Matches without an announced time (`dateexact=0`) no longer flood time ranges: they
  count as whole UTC days (included only if the day lies fully inside the range, or the
  range inside the day), are limited separately from exact matches, and large groups are
  summarised in one line per tournament stage and day. Cut-off lists set `truncated`
  and say "… and N more". Time ranges now request up to 500 rows (still one request).

[0.1.0]: https://github.com/LionScherer/liquipedia-mcp/releases/tag/v0.1.0
