# music-discovery — Roadmap

**Status:** Planning. Not started.

---

## What This Does

Three loosely coupled tools built on top of the existing vault library:

1. **`music-discover`** — cross-references your library against Last.fm + ListenBrainz to surface
   artists you'd likely enjoy but don't have yet. Outputs a ranked expansion list.
2. **`music-playlist`** — generates M3U playlists from your existing library using mood/energy/
   similarity logic. No streaming required — everything resolves to local file paths.
3. **`listen-import`** — one-time import of your Amazon Music listen history into ListenBrainz,
   so the recommendation engine has your full listening picture (not just 2007–whenever).

These are independent but share the library scan and Last.fm client code.

---

## Tool 1 — music-discover

### Goal
Feed your 414-artist library into Last.fm's similar-artist graph, deduplicate against what you
already own, and return a ranked list of artists worth investigating.

### Data sources
| Source | What it provides |
|--------|-----------------|
| Last.fm `artist.getSimilar` | Similar artists with a match score (0–1) |
| Last.fm `artist.getInfo` | Tags (genre), listener count, play count |
| ListenBrainz `similar-users` + `recommendations` | Collaborative filtering — what people with similar taste listen to |
| Your library (`/vault/media/music/`) | The "already own" exclusion list |

### Pipeline

```
Walk /vault/media/music/ → artist list (414 artists)
    ↓
For each artist → Last.fm artist.getSimilar (top 10–20 results)
    ↓
Aggregate all suggestions, deduplicate, exclude artists already in library
    ↓
For each candidate → Last.fm artist.getInfo (tags, listener count)
    ↓
Score candidates:
  - weighted average of match scores across all your artists that surfaced them
  - bonus for high listener count (filters obscure one-hit wonders)
  - bonus if also surfaced by ListenBrainz recommendations
    ↓
Output: ranked TSV/CSV — artist | score | tags | why_suggested
```

### ListenBrainz integration
- Submit your library as a "loved tracks" or listen history → improves their recommendation model
- Call `GET /1/cf/recommendation/user/{username}/recording` for collaborative filtering results
- Requires ListenBrainz account + API token

### Commands
```bash
music-discover scan          # build/refresh similarity graph from library
music-discover report        # show ranked expansion candidates
music-discover report --min-score 0.6 --tag metal   # filtered view
```

---

## Tool 2 — music-playlist

### Goal
Generate M3U playlists from your local library. No mood detection API needed — use the
MusicBrainz tags and Last.fm tags you already pull during discovery, plus file metadata.

### Playlist types

| Type | Logic |
|------|-------|
| **Similar to artist** | Seed artist → Last.fm similar → find matching files in library |
| **By tag/mood** | Filter library by Last.fm tag (e.g. "melancholic", "driving", "post-hardcore") |
| **Era** | Filter by album year range |
| **Deep cuts** | Tracks from albums you have but never appear in "top tracks" |
| **Gateway** | Mid-energy tracks from artists you want to introduce to someone (Becca use case) |

### Output
Standard M3U with absolute paths — works directly in VLC, Plex, foobar2000, anything.

```
#EXTM3U
#EXTINF:214,Alice in Chains - Rooster
/vault/media/music/Alice in Chains/Dirt (1992)/09 Rooster.opus
...
```

### Commands
```bash
music-playlist similar "Alice in Chains"       # similar-artist playlist
music-playlist tag "post-hardcore" --length 60 # 60-min tag playlist
music-playlist era 1994 2003 --length 90        # era playlist
music-playlist gateway "Tool"                   # introduction playlist for an artist
```

Playlists saved to `/vault/media/playlists/`.

---

## Tool 3 — listen-import

### Goal
One-time import of Amazon Music listen history into ListenBrainz so your full listening
picture is available for recommendations — not just post-reactivation Last.fm scrobbles.

### What you have
- Amazon Music export (listen history CSV/JSON — request via Amazon data export)
- Last.fm history from 2007 (partial — gaps during Amazon Music years)

### Pipeline
```
Parse Amazon export → normalize to (artist, title, timestamp) tuples
    ↓
Match to MusicBrainz recordings (fuzzy text search, same pipeline as music-adder)
    ↓
Submit to ListenBrainz as "import" listen type via API
    (ListenBrainz accepts historical imports with original timestamps)
    ↓
Report: X listens submitted, Y unmatched (saved for manual review)
```

### Why ListenBrainz and not Last.fm?
Last.fm's API does not accept historical scrobble imports — timestamps must be recent.
ListenBrainz explicitly supports bulk historical imports and is designed for this.

---

## Shared Infrastructure

Both `music-discover` and `music-playlist` need:
- Library artist/track index (same ffprobe scan as music-quality — could share the JSON)
- Last.fm API client (pylast library)
- Cache layer — Last.fm rate limits to 5 req/sec; similar-artist data doesn't change often,
  cache to disk for 30 days

Config extends `~/.config/music-tools/config.yaml`:
```yaml
lastfm:
  api_key: YOUR_KEY
  api_secret: YOUR_SECRET
  username: YOUR_USERNAME

listenbrainz:
  token: YOUR_TOKEN
  username: YOUR_USERNAME
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `pylast` | Last.fm API client |
| `requests` | ListenBrainz REST API |
| `musicbrainzngs` | Already available from music-adder |
| `rich` | Terminal output (consistent with other tools) |

---

## Key Paths

| Path | Purpose |
|------|---------|
| `/vault/media/music/` | Smitty's library |
| `/vault/media/becca_music/` | Becca's library |
| `/vault/media/playlists/` | Output directory for M3U playlists |
| `~/.config/music-tools/config.yaml` | Shared config (extend existing file) |
| `~/music_library/discovery/` | Cached similarity data, ranked reports |

---

## Build Order

1. **`listen-import`** first — gets your full history into ListenBrainz before running
   recommendations. One-shot tool, standalone, no dependencies on the others.
2. **`music-discover`** — needs Last.fm API key and library artist list. Produces the
   expansion candidate list and the tag/similarity cache that playlist uses.
3. **`music-playlist`** — depends on the tag cache from music-discover. Build last.

---

## What's Not In Scope

- Audio analysis / BPM detection for playlist ordering (overkill for now)
- Streaming integration (Spotify, Apple Music) — local library only
- Automatic download of discovery results — that's `music-adder`'s job; discovery just
  outputs a list you feed into a batch file
