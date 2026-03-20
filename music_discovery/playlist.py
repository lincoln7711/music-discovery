#!/usr/bin/env python3
"""
music-playlist — generate M3U playlists from the vault library.

Commands:
  music-playlist similar <artist>            Tracks from artists similar to <artist>
  music-playlist tag <tag>                   Tracks from artists matching a genre tag
  music-playlist era <start> <end>           Tracks from albums released in year range
  music-playlist gateway <artist>            Most popular tracks — good introduction playlist
  music-playlist deep-cuts <artist>          Album tracks not in Last.fm top tracks
  music-playlist mix <artist> <artist> ...   Blend specific artists together

Global options:
  --length <minutes>    Target playlist length in minutes (default: 60)
  --out <path>          Output path (default: /vault/media/playlists/<name>.m3u)
  --no-shuffle          Keep tracks in album/track order (default: shuffled)
"""

import json
import random
import re
import sys
import time
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.table import Table

# ── Config ──────────────────────────────────────────────────────────────────────

CONFIG_PATH   = Path("~/.config/music-tools/config.yaml").expanduser()
INVENTORY     = Path("/home/smitty/music_library/quality/quality_inventory.json")
CACHE_DIR     = Path("~/music_library/discovery").expanduser()
PLAYLIST_DIR  = Path("/vault/media/playlists")
TAG_CACHE     = CACHE_DIR / "discovery_tags.json"
SIMILAR_CACHE = CACHE_DIR / "discovery_similar.json"

console = Console()


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Track index ─────────────────────────────────────────────────────────────────

def load_tracks() -> list[dict]:
    """Load inventory and normalise artist/title for Non-Album tracks."""
    with open(INVENTORY) as f:
        tracks = json.load(f)

    for t in tracks:
        # Non-Album tracks have artist='music' — parse from filename instead
        if t.get("album") == "Non-Album" or t.get("artist") == "music":
            stem = Path(t["filename"]).stem
            if " - " in stem:
                parts = stem.split(" - ", 1)
                t["artist"] = parts[0].strip()
                t["title"]  = parts[1].strip()
            else:
                t["title"] = stem
        else:
            stem = Path(t["filename"]).stem
            # Strip leading track number (e.g. "01 " or "01 - ")
            t["title"] = re.sub(r"^\d{1,3}\s*[-.]?\s*", "", stem).strip()

        # Extract year from album string
        m = re.search(r"\((\d{4})\)", t.get("album", ""))
        t["year"] = int(m.group(1)) if m else None

    return tracks


def tracks_by_artist(tracks: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for t in tracks:
        artist = t.get("artist", "").strip()
        if artist:
            idx.setdefault(artist.lower(), []).append(t)
    return idx


def find_artist(name: str, idx: dict[str, list[dict]]) -> str | None:
    """Case-insensitive artist lookup, returns canonical key or None."""
    norm = name.lower().strip()
    if norm in idx:
        return norm
    # Partial match
    matches = [k for k in idx if norm in k or k in norm]
    if len(matches) == 1:
        return matches[0]
    if matches:
        console.print(f"[yellow]Ambiguous artist '{name}': {[idx[m][0]['artist'] for m in matches[:5]]}[/yellow]")
    return None


# ── Last.fm helpers ─────────────────────────────────────────────────────────────

_tag_cache: dict[str, list[str]] = {}

def _load_tag_cache() -> None:
    global _tag_cache
    if TAG_CACHE.exists():
        with open(TAG_CACHE) as f:
            _tag_cache = json.load(f)

def _save_tag_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(TAG_CACHE, "w") as f:
        json.dump(_tag_cache, f)

def get_artist_tags(artist: str, api_key: str) -> list[str]:
    if artist in _tag_cache:
        return _tag_cache[artist]
    try:
        resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getTopTags", "artist": artist,
            "api_key": api_key, "format": "json",
        }, timeout=10).json()
        tags = [t["name"].lower() for t in resp.get("toptags", {}).get("tag", [])[:8]]
    except Exception:
        tags = []
    _tag_cache[artist] = tags
    time.sleep(0.2)
    return tags

def get_top_tracks(artist: str, api_key: str, limit: int = 50) -> list[str]:
    """Return list of normalised track titles from Last.fm top tracks."""
    try:
        resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getTopTracks", "artist": artist,
            "api_key": api_key, "format": "json", "limit": limit,
        }, timeout=10).json()
        return [t["name"].lower().strip()
                for t in resp.get("toptracks", {}).get("track", [])]
    except Exception:
        return []

def get_similar_artists(artist: str, api_key: str, limit: int = 20) -> list[str]:
    """Return similar artist names from Last.fm (or cache)."""
    if SIMILAR_CACHE.exists():
        with open(SIMILAR_CACHE) as f:
            cache = json.load(f)
        # Try exact or case-insensitive key match
        for key in cache:
            if key.lower() == artist.lower():
                return [s["name"] for s in cache[key]]
    try:
        resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getSimilar", "artist": artist,
            "api_key": api_key, "format": "json", "limit": limit,
        }, timeout=10).json()
        return [s["name"] for s in resp.get("similarartists", {}).get("artist", [])]
    except Exception:
        return []


# ── Playlist builder ────────────────────────────────────────────────────────────

def build_m3u(tracks: list[dict], path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("#EXTM3U\n")
        f.write(f"#PLAYLIST:{title}\n")
        for t in tracks:
            dur = int(t.get("duration_s") or -1)
            artist = t.get("artist", "")
            title_str = t.get("title", Path(t["path"]).stem)
            f.write(f"#EXTINF:{dur},{artist} - {title_str}\n")
            f.write(f"{t['path']}\n")

def trim_to_length(tracks: list[dict], minutes: int, shuffle: bool = True) -> list[dict]:
    """Sample tracks up to target length."""
    pool = list(tracks)
    if shuffle:
        random.shuffle(pool)
    result, total = [], 0
    target_s = minutes * 60
    for t in pool:
        dur = t.get("duration_s") or 0
        if total + dur > target_s * 1.05:  # 5% overshoot allowed
            break
        result.append(t)
        total += dur
        if total >= target_s:
            break
    return result

def report_playlist(tracks: list[dict], out_path: Path) -> None:
    total_s = sum(t.get("duration_s") or 0 for t in tracks)
    mins, secs = divmod(int(total_s), 60)
    console.print(f"\n[green]✓[/green] [bold]{len(tracks)} tracks[/bold] — {mins}m {secs:02d}s")
    console.print(f"[dim]{out_path}[/dim]\n")

    t = Table.grid(padding=(0, 2))
    for track in tracks[:10]:
        artist = track.get("artist", "")
        title  = track.get("title", "")
        album  = track.get("album", "")
        dur_s  = int(track.get("duration_s") or 0)
        t.add_row(
            f"[bold]{artist}[/bold]",
            title,
            f"[dim]{album}[/dim]",
            f"[dim]{dur_s//60}:{dur_s%60:02d}[/dim]"
        )
    if len(tracks) > 10:
        t.add_row("[dim]…[/dim]", f"[dim]+{len(tracks)-10} more[/dim]", "", "")
    console.print(t)


# ── Playlist commands ───────────────────────────────────────────────────────────

def cmd_similar(seed: str, length: int, shuffle: bool, out: Path | None) -> None:
    cfg = load_config()
    api_key = cfg["lastfm"]["api_key"]
    tracks = load_tracks()
    idx = tracks_by_artist(tracks)
    _load_tag_cache()

    seed_key = find_artist(seed, idx)
    seed_tracks = idx.get(seed_key, []) if seed_key else []

    similar_names = get_similar_artists(seed, api_key, limit=30)
    console.print(f"[bold]Similar to:[/bold] {seed}")
    console.print(f"Last.fm found {len(similar_names)} similar artists\n")

    # Find which similar artists are in the library
    pool = list(seed_tracks)
    found_similar = []
    for name in similar_names:
        key = find_artist(name, idx)
        if key:
            found_similar.append(idx[key][0]["artist"])
            pool.extend(idx[key])

    if found_similar:
        console.print(f"[green]In your library:[/green] {', '.join(found_similar[:8])}"
                      + (f" +{len(found_similar)-8} more" if len(found_similar) > 8 else ""))
    else:
        console.print("[yellow]No similar artists found in library — using seed artist only[/yellow]")

    if not pool:
        console.print(f"[red]Artist '{seed}' not found in library[/red]")
        return

    result = trim_to_length(pool, length, shuffle)
    slug = re.sub(r"[^\w\s-]", "", seed).strip().replace(" ", "_")
    out_path = out or PLAYLIST_DIR / f"similar_{slug}.m3u"
    build_m3u(result, out_path, f"Similar to {seed}")
    report_playlist(result, out_path)
    _save_tag_cache()


def cmd_tag(tag: str, length: int, shuffle: bool, out: Path | None) -> None:
    cfg = load_config()
    api_key = cfg["lastfm"]["api_key"]
    tracks = load_tracks()
    idx = tracks_by_artist(tracks)
    _load_tag_cache()

    console.print(f"[bold]Tag playlist:[/bold] {tag}\n")
    console.print("[dim]Checking artist tags (cached where possible)…[/dim]")

    pool = []
    matched_artists = []
    tag_lower = tag.lower()

    all_artists = list(idx.keys())
    for artist_key in all_artists:
        canonical = idx[artist_key][0]["artist"]
        tags = get_artist_tags(canonical, api_key)
        if any(tag_lower in t for t in tags):
            matched_artists.append(canonical)
            pool.extend(idx[artist_key])

    _save_tag_cache()

    if not pool:
        console.print(f"[yellow]No library artists found with tag '{tag}'[/yellow]")
        return

    console.print(f"[green]{len(matched_artists)} artists matched:[/green] "
                  f"{', '.join(matched_artists[:8])}"
                  + (f" +{len(matched_artists)-8} more" if len(matched_artists) > 8 else ""))

    result = trim_to_length(pool, length, shuffle)
    slug = re.sub(r"[^\w\s-]", "", tag).strip().replace(" ", "_")
    out_path = out or PLAYLIST_DIR / f"tag_{slug}.m3u"
    build_m3u(result, out_path, f"{tag.title()} Mix")
    report_playlist(result, out_path)


def cmd_era(start: int, end: int, length: int, shuffle: bool, out: Path | None) -> None:
    tracks = load_tracks()

    pool = [t for t in tracks if t.get("year") and start <= t["year"] <= end]
    if not pool:
        console.print(f"[yellow]No tracks found for {start}–{end}[/yellow]")
        return

    artists = len({t.get("artist") for t in pool})
    console.print(f"[bold]Era {start}–{end}:[/bold] {len(pool)} tracks from {artists} artists\n")

    result = trim_to_length(pool, length, shuffle)
    out_path = out or PLAYLIST_DIR / f"era_{start}_{end}.m3u"
    build_m3u(result, out_path, f"{start}–{end} Era Mix")
    report_playlist(result, out_path)


def cmd_gateway(artist: str, length: int, shuffle: bool, out: Path | None) -> None:
    cfg = load_config()
    api_key = cfg["lastfm"]["api_key"]
    tracks = load_tracks()
    idx = tracks_by_artist(tracks)

    key = find_artist(artist, idx)
    if not key:
        console.print(f"[red]Artist '{artist}' not found in library[/red]")
        return

    artist_tracks = idx[key]
    top_titles = get_top_tracks(artist, api_key, limit=30)

    # Find library tracks that match Last.fm top tracks
    gateway: list[dict] = []
    rest: list[dict] = []
    for t in artist_tracks:
        title_norm = t.get("title", "").lower().strip()
        # Fuzzy match: check if any top title is contained in or matches the track title
        is_top = any(
            top in title_norm or title_norm in top
            for top in top_titles
        )
        if is_top:
            gateway.append(t)
        else:
            rest.append(t)

    console.print(f"[bold]Gateway playlist:[/bold] {idx[key][0]['artist']}")
    console.print(f"  Top tracks in library:    [green]{len(gateway)}[/green]")
    console.print(f"  Other tracks in library:  [dim]{len(rest)}[/dim]\n")

    # Lead with top tracks, pad with other tracks if needed
    pool = gateway + rest
    result = trim_to_length(pool, length, shuffle=False)  # keep top-track order
    slug = re.sub(r"[^\w\s-]", "", artist).strip().replace(" ", "_")
    out_path = out or PLAYLIST_DIR / f"gateway_{slug}.m3u"
    build_m3u(result, out_path, f"{artist} — Gateway")
    report_playlist(result, out_path)


def cmd_deep_cuts(artist: str, length: int, shuffle: bool, out: Path | None) -> None:
    cfg = load_config()
    api_key = cfg["lastfm"]["api_key"]
    tracks = load_tracks()
    idx = tracks_by_artist(tracks)

    key = find_artist(artist, idx)
    if not key:
        console.print(f"[red]Artist '{artist}' not found in library[/red]")
        return

    artist_tracks = idx[key]
    top_titles = get_top_tracks(artist, api_key, limit=50)

    deep: list[dict] = []
    for t in artist_tracks:
        title_norm = t.get("title", "").lower().strip()
        is_top = any(top in title_norm or title_norm in top for top in top_titles)
        if not is_top:
            deep.append(t)

    console.print(f"[bold]Deep cuts:[/bold] {idx[key][0]['artist']}")
    console.print(f"  Tracks in library:  {len(artist_tracks)}")
    console.print(f"  Not in Last.fm top 50: [green]{len(deep)}[/green]\n")

    if not deep:
        console.print("[yellow]All library tracks appear in Last.fm top 50 — no deep cuts found[/yellow]")
        return

    result = trim_to_length(deep, length, shuffle)
    slug = re.sub(r"[^\w\s-]", "", artist).strip().replace(" ", "_")
    out_path = out or PLAYLIST_DIR / f"deep_cuts_{slug}.m3u"
    build_m3u(result, out_path, f"{artist} — Deep Cuts")
    report_playlist(result, out_path)


def cmd_mix(artists: list[str], length: int, shuffle: bool, out: Path | None) -> None:
    tracks = load_tracks()
    idx = tracks_by_artist(tracks)

    pool = []
    found = []
    for name in artists:
        key = find_artist(name, idx)
        if key:
            found.append(idx[key][0]["artist"])
            pool.extend(idx[key])
        else:
            console.print(f"[yellow]'{name}' not found in library, skipping[/yellow]")

    if not pool:
        console.print("[red]No matching artists found[/red]")
        return

    console.print(f"[bold]Mix:[/bold] {', '.join(found)}\n")
    result = trim_to_length(pool, length, shuffle)
    slug = "_".join(re.sub(r"[^\w]", "", a)[:10] for a in found[:3])
    out_path = out or PLAYLIST_DIR / f"mix_{slug}.m3u"
    build_m3u(result, out_path, " + ".join(found))
    report_playlist(result, out_path)


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    def add_common(p):
        p.add_argument("--length",     type=int,  default=60,   help="Target length in minutes")
        p.add_argument("--out",        type=str,  default=None, help="Output .m3u path")
        p.add_argument("--no-shuffle", action="store_true",     help="Preserve track order")

    parser = argparse.ArgumentParser(prog="music-playlist")
    sub = parser.add_subparsers(dest="cmd")

    p_sim = sub.add_parser("similar",    help="Artists similar to a seed artist")
    p_sim.add_argument("artist", nargs="+")
    add_common(p_sim)

    p_tag = sub.add_parser("tag",        help="Artists matching a genre tag")
    p_tag.add_argument("tag")
    add_common(p_tag)

    p_era = sub.add_parser("era",        help="Tracks from a year range")
    p_era.add_argument("start", type=int)
    p_era.add_argument("end",   type=int)
    add_common(p_era)

    p_gw  = sub.add_parser("gateway",    help="Popular tracks — introduction playlist")
    p_gw.add_argument("artist", nargs="+")
    add_common(p_gw)

    p_dc  = sub.add_parser("deep-cuts",  help="Album tracks not in Last.fm top 50")
    p_dc.add_argument("artist", nargs="+")
    add_common(p_dc)

    p_mix = sub.add_parser("mix",        help="Blend specific artists")
    p_mix.add_argument("artists", nargs="+")
    add_common(p_mix)

    args = parser.parse_args()
    shuffle = not args.no_shuffle
    out = Path(args.out) if args.out else None

    if args.cmd == "similar":
        cmd_similar(" ".join(args.artist), args.length, shuffle, out)
    elif args.cmd == "tag":
        cmd_tag(args.tag, args.length, shuffle, out)
    elif args.cmd == "era":
        cmd_era(args.start, args.end, args.length, shuffle, out)
    elif args.cmd == "gateway":
        cmd_gateway(" ".join(args.artist), args.length, shuffle, out)
    elif args.cmd == "deep-cuts":
        cmd_deep_cuts(" ".join(args.artist), args.length, shuffle, out)
    elif args.cmd == "mix":
        cmd_mix(args.artists, args.length, shuffle, out)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
