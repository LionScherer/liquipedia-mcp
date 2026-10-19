# liquipedia-mcp

A small, careful Python client and [MCP](https://modelcontextprotocol.io) server for the
[Liquipedia](https://liquipedia.net) **LPDB v3 API**: match results (with every single
game), upcoming matches, matches in a time range, and league/group/Swiss standings.

- **Core library** (`liquipedia_mcp.client`, `.matches`, `.standings`, `.format`) usable
  without MCP. It returns structured dataclasses, so you can format answers yourself (in
  any language).
- **MCP server** (`liquipedia-mcp`) that exposes the core as five read-only tools, returning
  English text for the model plus the structured data.
- **Built to respect Liquipedia**: a hard 60 requests/hour budget, caching, no automatic
  retries, a mandatory identifying User-Agent and attribution on every result. See
  [Respecting Liquipedia](#respecting-liquipedia).

> **Bring your own key.** This project is meant to be self-hosted by each user with their
> *own* LPDB API key. There is no public instance, and you must not run one with your key
> (see below).

Verified wikis: `rocketleague` and `leagueoflegends`. Other LPDB wikis (e.g. `dota2`,
`counterstrike`) are accepted, but the data pitfalls described below were only verified
for those two.

## Installation

Requires Python 3.11+. The package is not on PyPI; install it from this repository:

```bash
pip install "git+https://github.com/LionScherer/liquipedia-mcp"
# or run it without installing:
uvx --from "git+https://github.com/LionScherer/liquipedia-mcp" liquipedia-mcp --help
```

For development:

```bash
git clone https://github.com/LionScherer/liquipedia-mcp && cd liquipedia-mcp
pip install -e ".[dev]"
pytest && ruff check .
```

The tests use recorded/reconstructed API answers in `tests/fixtures` and never touch the
network, so they need no API key.

## Get your own API key

1. Read Liquipedia's API terms and request access at **https://liquipedia.net/api**.
   The free plan is for public, open-source projects that serve the esports community.
2. Keep the key secret. It belongs in an environment variable or a git-ignored `.env`
   file, never in code or in a repository.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `LIQUIPEDIA_API_KEY` | yes | Your LPDB API key. Sent only in the `Authorization` header; never logged. |
| `LIQUIPEDIA_USER_AGENT` | yes | Identifies **your** project and how to reach you, e.g. `"<your-project>/<version> (<contact>)"` → `"esports-helper/1.2 (https://github.com/you/esports-helper; you@example.org)"`. |
| `LIQUIPEDIA_MAX_REQUESTS_PER_HOUR` | no | Lower the per-process budget (1–60, default 60). Values above 60 are refused. |
| `LIQUIPEDIA_LOCKOUT_SECONDS` | no | Pause after an HTTP 429 (default 600, minimum 60). |

The server refuses to start when the key is missing or when the User-Agent is empty,
still the placeholder, a generic library default (`python-httpx/…`, `curl/…`, …) or has
no contact (e-mail address or URL). `liquipedia-mcp/<version>` is appended automatically.

See [`.env.example`](.env.example).

## Use with an MCP client

### Claude Desktop (or any client using the `mcpServers` format)

```json
{
  "mcpServers": {
    "liquipedia": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/LionScherer/liquipedia-mcp", "liquipedia-mcp"],
      "env": {
        "LIQUIPEDIA_API_KEY": "your-key",
        "LIQUIPEDIA_USER_AGENT": "my-assistant/1.0 (https://github.com/you/my-assistant)"
      }
    }
  }
}
```

### Streamable HTTP (local only)

```bash
liquipedia-mcp --transport streamable-http --host 127.0.0.1 --port 8000
# MCP endpoint: http://127.0.0.1:8000/mcp
```

The default bind address is `127.0.0.1`. Binding to any other address is refused unless
you pass `--allow-remote`.

> ⚠️ **Never expose this server to the internet.** Every tool call is paid for with *your*
> API key. A public endpoint lets strangers use your key, which violates Liquipedia's
> terms and can get the key revoked. If you need remote access, keep it inside your own
> private network or behind authentication you control.

### Tools

| Tool | What it does | Requests |
| --- | --- | --- |
| `get_results(wiki, team?, tournament?, max_tier=1, include_minor_types=false, limit=5)` | Finished matches, newest first, with series score, winner by name, every game score (incl. overtime). Champion picks + MVP for ≤ 3 LoL matches. | 1 |
| `get_upcoming(wiki, team?, tournament?, max_tier=1, include_minor_types=false, limit=10)` | Scheduled matches from now on, soonest first. TBD pairings are left out. | 1 |
| `get_matches_between(wikis, start_utc, end_utc, max_tier=1, include_minor_types=false, team?)` | Everything in a time range (≤ 31 days), several wikis in one request. Up to 50 matches with a known time, plus day-only matches (see below). | 1 |
| `get_standings(wiki, team? \| tournament?)` | Current table of a team (finds the phase itself) or all groups of a tournament (exact name). | 2–3 |
| `get_match_details(wiki, team, opponent?, limit=1)` | Every game of the team's latest match(es): scores, OT, length, kills, maps, MVP, champions. | 1 |

Tier filters (`1`=S, `2`=A, `3`=B, `4`=C, `5`=D) only apply to general queries; with a
team or tournament, all tiers are included. A tier filter keeps exactly tiers
`1..max_tier`: unranked events (`liquipediatier` `-1`) never pass, and minor tier types
(`Qualifier`, `Showmatch`, `Misc`, `Monthly`, `Weekly`, `Biweekly`, `Daily`, `Charity`)
are left out unless `include_minor_types=true`. Regular tournaments have an empty tier
type and always stay in.

Matches whose time is not announced yet (`dateexact=0`) only carry a day; the 00:00 in
their `date` is a placeholder (the structured result has `date_exact=false` and `day`).
`get_matches_between` treats them as whole UTC days: they are included only if their day
lies completely inside the range, or the range lies completely inside that day. A range
like 13:35 to 01:35 the next day therefore leaves the second day's day-only matches out
and says how many were skipped. Exact and day-only matches are limited separately, so
day-only matches cannot push exact ones out; a cut-off list says "… and N more". In the
text, more than five unplayed day-only matches of one tournament stage and day become
one line ("FIFAe World Cup 2026 – Group A: 16 matches on 2026-10-20, times not announced
yet"); the structured data still lists every match. Tool descriptions tell the model to read each
match line on its own, never invent totals, never present unplayed matches as 0–0, and to
cite Liquipedia.

## Use as a library

```python
import asyncio
from liquipedia_mcp import LiquipediaClient
from liquipedia_mcp.matches import get_results
from liquipedia_mcp.standings import get_standings


async def main():
    async with LiquipediaClient.from_env() as client:  # one client per process
        results = await get_results(client, "rocketleague", team="Team Falcons", limit=3)
        for m in results.matches:
            print(
                m.date,
                m.score_line,
                "winner:",
                m.winner_name,
                [(g.score1, g.score2, g.overtime) for g in m.games],
            )
        print(results.source.text)  # keep the attribution!

        table = await get_standings(client, "leagueoflegends", team="T1")
        print(table.to_dict())


asyncio.run(main())
```

All results are dataclasses with `to_dict()` (JSON-ready). Highlights:

- `Match.winner_name` is computed explicitly (from the scores, or LPDB's `winner` for
  forfeits). Pass names, not indices, to language models: index-based winners were
  reproducibly attributed to the wrong team.
- `Opponent.score` is `None` for unplayed matches (LPDB stores `-1` placeholders).
- `StandingsGroup.started` is `False` before the first match; placements are then
  cleared and `leader` is `None`.
- `liquipedia_mcp.format` contains the English formatter used by the server.

You can inject your own HTTP function (`LiquipediaClient(..., fetch=my_fetch)`), which is
how the tests run without a network.

## Respecting Liquipedia

Liquipedia is run by volunteers and Team Liquid, and the API is a shared resource. This
package is deliberately conservative:

- **Request budget.** At most **60 requests per hour per process** (sliding window), as
  allowed by the API terms. You can lower it, not raise it. When it is used up, the call
  fails with a clear error *instead of* sending a request. Cached answers keep working.
  If you run several processes with the same key, lower the budget so their sum stays
  within the limit.
- **No automatic retries.** Errors are reported, never retried in a loop. After an
  HTTP **429**, *all* requests pause for 10 minutes (configurable, or longer if the
  server sends `Retry-After`).
- **Caching.** Successful answers are cached for 5 minutes (time-range queries 10
  minutes); errors are cached for 1 minute so that polling clients cannot hammer the API.
  The cache is size-bounded and in memory.
- **Few, precise requests.** One request per match query (multiple wikis are combined
  with `|`), field projection via `query=…`, standings in 2–3 requests.
- **Identification.** A User-Agent naming your project and contact is mandatory, plus
  `liquipedia-mcp/<version>`. Responses are requested gzip-compressed.
- **No background traffic.** There are no health checks, warm-ups or polling loops;
  requests only happen when a tool is called.
- **Safe queries.** Team and tournament names are validated before they are placed in
  LPDB `conditions`: `[`, `]`, `{`, `}`, `|`, `::`, leading operators (`!`, `<`, `>`, `~`)
  and stand-alone `AND`/`OR` are rejected; wiki names must match `^[a-z0-9]+$`; limits are
  clamped.
- **Key hygiene.** The key is read from the environment only, is never logged and never
  appears in `repr()` or error messages. `.env` is git-ignored.
- **Attribution.** Every result carries `Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0`
  both in the text and as a structured `source` field.

### Your obligations as a downstream user

Data from Liquipedia is licensed under
[CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). If you show or publish
it (in a chat answer, a bot message, a website…), credit Liquipedia and keep the license
notice; derived data must stay under the same license. Do not strip the `source` field
when you re-format results. Follow Liquipedia's API terms for your own key.

## Data pitfalls handled

Discovered against real LPDB answers (Rocket League and League of Legends, July–September
2026):

- `order=date DESC` without `[[finished::1]]` returns the matches furthest in the
  *future* first, so results, upcoming matches and time ranges are separate queries.
- `winner` is a string (`"1"`, `"2"`, `""`), `finished` an integer. Unplayed scores are
  `-1`; undetermined opponents have empty names. Neither is ever shown as a result.
- Round names come from `match2bracketdata.header`; wiki shorthands like `!l4!x` are
  dropped instead of guessed (the `section`, e.g. "Playoffs", remains).
- Player names like `Diaz_(Brazilian_Player)` are cleaned to `Diaz`.
- Single games marked `notplayed`/`np` or without two valid scores are skipped.
- Standings store one row per team *per round*, unsorted; only the latest round counts.
  Tables exist before the first match with placements 1..n; those are reported as "not
  started". Only `definitestatus` is used (`currentstatus` is "down" for everyone before
  the start). Bo1 Swiss stages keep game records at 0–0; then only match records are shown.
- Team names are matched exactly by LPDB, but people say "FURIA Esports" where
  Liquipedia says "FURIA". When a team lookup finds nothing, it is retried once
  without affixes like "Esports"/"Gaming"/"Team", and the opponent filter of
  `get_match_details` compares names the same tolerant way.
- For team standings, the current phase is the played one with the latest end date, not
  the highest page id (which picked a January cup over a September league).

## Example output

From the test fixtures (reconstructed API answers), as the MCP server returns it:

```text
Latest results – Rocket League (S-Tier only), newest first:
1. 2026-09-14 18:30 UTC | RLCS 2026 - World Championship | Playoffs, Grand Final | Bo7
   Result: Team Falcons 4–1 Karmine Corp. Winner: Team Falcons.
   Games (Team Falcons–Karmine Corp): G1 1–0 (OT, DFH Stadium, 6:21), G2 2–1 (Mannfield), G3 0–3 (Champions Field), G4 1–0 (OT, Utopia Coliseum), G5 3–2 (Urban Central)
2. 2026-09-14 15:00 UTC | RLCS 2026 - World Championship | Playoffs | Bo7
   Result: Karmine Corp 4–0 Gentle Mates. Winner: Karmine Corp.
   Games (Karmine Corp–Gentle Mates): G1 1–0 (DFH Stadium), G2 1–0 (OT, Mannfield), G3 1–0 (Neo Tokyo), G4 1–0 (Forbidden Temple)
Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0
```

```text
Upcoming matches – Rocket League (S-Tier only), in chronological order:
1. 2026-10-24 14:00 UTC | RLCS 2027 - Paris Open | Swiss Stage, Round 1 | Bo5
   Team Falcons vs Karmine Corp – not played yet
2. 2026-10-25 (time TBA) | RLCS 2027 - Paris Open | Swiss Stage | Bo5
   NRG vs Gentle Mates – not played yet
(1 match(es) with opponents not determined yet were left out.)
Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0
```

```text
Standings – T1 (League of Legends)

LCK 2026 – Rounds 3-5 – Legend Group
1. Gen.G – matches 12–1 – games 25–6 – advanced
2. T1 – matches 10–3 – games 20–3 – advanced  (queried team)
3. Hanwha Life Esports – matches 8–5 – games 17–12 – advanced
4. Dplus KIA – matches 4–9 – games 10–19
5. KT Rolster – matches 1–12 – games 4–24 – eliminated
(Records are W–L.)
Leader: Gen.G
This stage is finished.

Next up for T1 (not started): 2026 World Championship – Swiss Stage

Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0
```

## License

- **Code:** MIT, see [LICENSE](LICENSE). © 2026 Lion Scherer.
- **Data** retrieved through this software: © Liquipedia contributors,
  [CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). The MIT license of
  the code does not apply to the data.

This project is not affiliated with or endorsed by Liquipedia or Team Liquid.
