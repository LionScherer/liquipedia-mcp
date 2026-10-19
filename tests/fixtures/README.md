# Test fixtures

Reconstructed LPDB v3 API answers (`{"result": [...]}` envelopes), modelled on real
responses for the `rocketleague` and `leagueoflegends` wikis. Team, player and tournament
names are public esports data; dates, scores and page ids are made up to cover specific
edge cases:

| File | Covers |
| --- | --- |
| `rl_results.json` | finished matches, overtime games, `!l4!x` bracket shorthand, `notplayed`/`np` games, winner as string, player name suffixes |
| `rl_upcoming.json` | `-1` placeholder scores, a TBD opponent, a day-only (`dateexact=0`) match |
| `lol_match_details.json` | MVP per game, champion picks, kills, game length, an empty player slot |
| `lol_team_entries.json` | standings entries of one team, rounds unsorted (r9…r1, r13…r10), a newer not-started phase, a cup with a higher page id but an earlier end date |
| `lol_team_tables.json` | `standingstable` rows for those pages |
| `lol_team_full_table.json` | the full league table, several rounds per team, shuffled |
| `lol_worlds_not_started_*.json` | a table before the first match (all 0–0, placements 1..n, `currentstatus` "down") |
| `lol_swiss_bo1_entries.json` | Bo1 Swiss stage with game records stuck at 0–0 |
| `rl_tier_mixed.json` | tier `"-1"` (unranked) and `""` matches, a tier-1 `Showmatch`, real S-Tier results |
| `mixed_date_only.json` | 30 day-only (`dateexact=0`, `00:00:00`) FIFAe matches in two groups plus 3 exact LoL matches, two wikis |
| `rl_tournament_*.json` | tournament lookup with two groups and all `definitestatus` values |
