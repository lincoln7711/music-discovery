# music-discover — User Guide & Result Interpretation

## Overview

`music-discover` cross-references your vault library (414 artists) against Last.fm's
similarity graph and ListenBrainz's collaborative filtering engine to surface artists
you'd likely enjoy but don't own yet. The output is a ranked, filterable candidate list
you can feed directly into `music-adder`.

---

## Commands Quick Reference

```bash
music-discover status                         # what's cached, when it was run
music-discover scan                           # query Last.fm for all library artists (~2 min)
music-discover lbz-recs                       # pull ListenBrainz CF recs (24-48h after import)
music-discover report                         # full ranked list, top 50
music-discover report --tag metal             # filter by genre tag
music-discover report --tag post-hardcore     # narrow to a subgenre
music-discover report --min 5                 # only artists suggested by 5+ of your artists
music-discover report --limit 100             # show more results
```

---

## Understanding the Report Columns

### Score
A composite number combining *how often* an artist was suggested across your library
with *how confidently* Last.fm matched them.

```
score = avg_match × log(suggestion_count + 1)
```

- A **high count, high match** artist scores best — Last.fm is consistently confident
  across many of your artists
- A **low count, very high match** artist (e.g. a near-twin of one specific artist you
  own) scores lower than something mentioned by 20 artists at moderate match
- If ListenBrainz also recommends them, score gets a **+25% boost** (LBZ column shows ✓)

**Rule of thumb:**
| Score | What it means |
|-------|--------------|
| > 2.0 | Very strong signal — mentioned by many artists at high confidence |
| 1.5–2.0 | Strong — worth investigating |
| 1.0–1.5 | Moderate — good for genre-filtered deep dives |
| < 1.0 | Weak — niche or single-artist suggestions |

### Suggested (count)
How many of your library artists triggered this candidate. **Staind appearing in 26
suggestions** means 26 of your artists have Staind as a neighbour in Last.fm's graph.
That's a very strong signal regardless of absolute score.

### LBZ ✓
ListenBrainz also recommended this artist via collaborative filtering — meaning other
users with similar taste to yours listen to them. Cross-source agreement is the
strongest possible signal. This column will populate once ListenBrainz processes your
listen import (24–48 hours after running `listen-import submit`).

### Tags
Last.fm's top genre tags for the candidate. Use these to quickly assess fit and to build
filtered queries.

### Because you like…
The library artists that surfaced this candidate. Shows up to 3, with "+N more". This
is your most useful column for *why* — if you see "Tool, A Perfect Circle, Puscifer"
you know exactly what sonic territory is being described.

---

## Filtering Noise

Your library contains some electronic/DnB content which pulls in a cluster of dubstep
and drum-and-bass suggestions that may not interest you. Filter them out:

```bash
# Show only metal-adjacent results
music-discover report --tag metal

# Post-hardcore / emo / screamo
music-discover report --tag post-hardcore

# Grunge and alt-rock (90s-adjacent)
music-discover report --tag grunge
music-discover report --tag "alternative rock" --min 5

# Celtic / folk (for Becca's library direction)
music-discover report --tag folk
music-discover report --tag celtic
```

If you want to permanently exclude genres from the main report, let me know and I can
add a `--exclude-tag` flag.

---

## The Signal Tiers

After running a scan of your 412-artist vault, here's how to think about the results:

### Tier 1 — Act on these (score > 1.5, count > 8)
These are consensus picks. Multiple corners of your library agree. Start here.
Examples from your first scan: Staind (26), Trapt (18), Evans Blue (14), Candlebox (14).

### Tier 2 — Worth a listen (score 1.0–1.5, or strong count in a specific genre)
Good candidates for a filtered search. Run `--tag metalcore` or `--tag post-hardcore`
and look at count ≥ 5 in that context.

### Tier 3 — Deep cuts (score < 1.0, --min 2)
Niche suggestions from one or two very specific artists you own. Low volume but
occasionally a gem — especially useful if you're a fan of one specific artist and want
their closest sonic neighbours.

---

## Working with the Results

### From report to music-adder
1. Note artists you want to explore
2. Find a YouTube playlist URL (official channel or fan upload)
3. Add to a batch file:
   ```
   # Staind
   https://www.youtube.com/playlist?list=...
   ```
4. Run: `music-adder batch ~/new_artists.txt`

### The full CSV
Every candidate (not just the top 50) is saved to:
```
~/music_library/discovery/discovery_candidates.csv
```
Columns: rank, name, score, count, lbz_boost, tags, suggested_by

Good for sorting, filtering in a spreadsheet, or grepping:
```bash
grep -i "metalcore" ~/music_library/discovery/discovery_candidates.csv | head -20
```

---

## Re-scanning

Last.fm's similarity data doesn't change often, but your library does. Re-run `scan`
after adding a significant batch of new artists to update the cache. The scan resumes
from where it left off if interrupted.

```bash
# After adding 20 new artists via music-adder:
music-discover scan    # fetches only the new ones, skips cached
music-discover report
```

---

## ListenBrainz Recommendations

The `lbz-recs` command queries ListenBrainz's collaborative filtering engine — it looks
at users with similar listening histories and surfaces what they enjoy that you don't.
This is a different signal from Last.fm's graph-based similarity.

**Timeline:** ListenBrainz batch-processes recommendations on a schedule. After running
`listen-import submit`, wait 24–48 hours then:

```bash
music-discover lbz-recs     # pulls and caches recs
music-discover report       # LBZ ✓ column now populated
```

Once active, artists with both a high Last.fm score **and** a LBZ ✓ are your highest
confidence picks — two independent systems agreed.

---

## Interpreting Your First Scan

**What the dubstep cluster tells you:** Your library has enough electronic content
(from the Amazon Music years, likely) that DnB/dubstep artists appear in the similarity
graph. If that's not your direction, use `--tag metal` or `--tag rock` to suppress them.
If it *is* something you want to explore, `--tag dubstep --min 3` will give you a clean
focused list.

**What the nu-metal / post-grunge cluster tells you:** Staind, Trapt, Evans Blue, Cold,
Smile Empty Soul, Candlebox scoring in the top 20 reflects a strong 2000s-era alt-rock
core in your library (Nickelback, Puddle of Mudd, Creed adjacency). These are safe bets
for enjoyment even if not artistically groundbreaking.

**What the metalcore cluster tells you:** Killswitch Engage, All That Remains, Silverstein,
Scary Kids Scaring Kids appearing mid-table means your heavier material (Atreyu, Chiodos,
A Day to Remember territory) is pulling in modern metalcore. High ceiling for discovery
here.

---

## Workflow Summary

```
music-discover scan
    ↓
music-discover report --tag metal          # find metal picks
music-discover report --tag post-hardcore  # find post-hc picks
music-discover report --min 8             # consensus picks only
    ↓
Pick artists → find YouTube URLs → music-adder batch
    ↓
(wait 24-48h after listen-import submit)
music-discover lbz-recs
music-discover report                      # now with LBZ boost column
```
