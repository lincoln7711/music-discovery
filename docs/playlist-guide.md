# music-playlist — User Guide

## Overview

`music-playlist` generates M3U playlists from your local vault library. No streaming
required — every playlist resolves to absolute file paths playable in Plex, VLC,
foobar2000, or anything that reads M3U.

Playlists are saved to `/vault/media/playlists/`.

---

## Commands

### `similar <artist>` — Artist neighbourhood
Builds a playlist from the seed artist + library artists that Last.fm considers similar.

```bash
music-playlist similar Tool
music-playlist similar "Alice in Chains" --length 90
music-playlist similar Korn --length 45 --no-shuffle
```

Great for: "I'm in a Tool mood and want more of that vibe."
Output: `similar_Tool.m3u`

---

### `tag <tag>` — Genre/mood filter
Finds all library artists that Last.fm tags with the given genre, then samples from them.
Tags are cached after first use — subsequent runs are instant.

```bash
music-playlist tag metal --length 60
music-playlist tag post-hardcore --length 45
music-playlist tag folk --length 90          # Becca-adjacent
music-playlist tag celtic --length 120
music-playlist tag grunge --length 60
music-playlist tag "alternative rock"
```

**First run is slow** (~2 min) while it fetches tags for all 412 artists. After that,
cached — instant. Tag matching is substring: `tag metal` matches `metal`, `metalcore`,
`nu metal`, `death metal`, etc.

Great for: mood playlists, genre deep dives, themed listening sessions.
Output: `tag_metal.m3u`, `tag_post-hardcore.m3u`, etc.

---

### `era <start> <end>` — Year range
Pulls tracks from albums released in the given year range.

```bash
music-playlist era 1990 1999 --length 60    # 90s
music-playlist era 1994 2003                # grunge era through nu-metal peak
music-playlist era 2000 2010 --length 90
music-playlist era 2015 2026                # modern
```

Year is parsed from the album directory name `Album (Year)`. Non-Album tracks and
undated albums are excluded.

Great for: nostalgic sessions, era-specific vibes.
Output: `era_1990_1999.m3u`

---

### `gateway <artist>` — Introduction playlist
Leads with the artist's most popular tracks (per Last.fm play counts), followed by
album deep cuts if more length is needed. Best playlist to share with someone new to
an artist.

```bash
music-playlist gateway Tool --length 60
music-playlist gateway "Slipknot" --length 45
music-playlist gateway "The Cure" --length 90 --no-shuffle
```

`--no-shuffle` preserves the popularity order, which is intentional here.

Great for: introducing an artist to someone, or rediscovering your own collection
starting from the hits.
Output: `gateway_Tool.m3u`

---

### `deep-cuts <artist>` — B-sides and album tracks
The inverse of gateway — library tracks that do **not** appear in Last.fm's top 50.
These are the album tracks that casual fans skip.

```bash
music-playlist deep-cuts "Alice in Chains"
music-playlist deep-cuts Tool --length 120
music-playlist deep-cuts Opeth
```

Great for: you know an artist well and want a fresh experience from your existing
library without replaying the hits.
Output: `deep_cuts_Alice_in_Chains.m3u`

---

### `mix <artist1> <artist2> ...` — Blend artists
Pulls tracks from specific artists and shuffles them together. Useful for custom
combinations that don't fit neatly into a tag.

```bash
music-playlist mix Tool "A Perfect Circle"
music-playlist mix Atreyu Chiodos "A Day to Remember" --length 90
music-playlist mix Enya "Loreena McKennitt" "Secret Garden" --length 120
```

Unknown artists are skipped with a warning. Quote artists with spaces.
Output: `mix_Tool_APerfectCi.m3u`

---

## Common Options

| Option | Default | Description |
|--------|---------|-------------|
| `--length N` | 60 | Target playlist length in minutes |
| `--out /path/x.m3u` | auto | Custom output path |
| `--no-shuffle` | off | Keep tracks in album/track order |

---

## Where Playlists Go

All playlists land in `/vault/media/playlists/` unless `--out` is specified.
Filename is auto-generated from the command and artist/tag:

```
/vault/media/playlists/similar_Tool.m3u
/vault/media/playlists/tag_metal.m3u
/vault/media/playlists/era_1994_2003.m3u
/vault/media/playlists/gateway_Tool.m3u
/vault/media/playlists/deep_cuts_Alice_in_Chains.m3u
/vault/media/playlists/mix_Tool_APerfectCi.m3u
```

Plex will pick these up automatically if `/vault/media/playlists/` is in your library.

---

## Tips & Tricks

**Tag playlist first run is slow, but cached forever:**
```bash
music-playlist tag metal   # ~2 min first time
music-playlist tag metal   # instant after that
```

**Becca's library direction (folk/celtic/world):**
```bash
music-playlist tag folk --length 120
music-playlist tag celtic
music-playlist mix Enya "Loreena McKennitt" "Secret Garden" "Celtic Woman"
music-playlist similar "Loreena McKennitt" --length 90
```

**Long drives / background listening:**
```bash
music-playlist era 1994 2003 --length 180
music-playlist tag "alternative rock" --length 120 --min-length 180
```

**Artist you just added and want to explore properly:**
```bash
music-playlist gateway "Staind" --length 60 --no-shuffle   # hits first
music-playlist deep-cuts "Staind"                           # then b-sides
```

**Pre-party / high energy:**
```bash
music-playlist tag "nu metal" --length 90
music-playlist mix Slipknot Korn "Rage Against the Machine" --length 60
```

---

## Playlist Length Accuracy

The `--length` target is approximate — the playlist stops when the next track would
push it 5% over the target. Actual playlists will be within a song or two of the
requested length.

---

## Re-running

Running the same command again **overwrites** the previous playlist at that path.
Use `--out` to save a variant without clobbering:

```bash
music-playlist similar Tool --length 45 --out ~/playlists/tool_short.m3u
music-playlist similar Tool --length 120 --out ~/playlists/tool_long.m3u
```
