#!/usr/bin/env python3
"""
music-discover — surface artist expansion candidates from Last.fm + ListenBrainz.

Commands:
  music-discover scan              Query Last.fm similar artists for every library artist
  music-discover lbz-recs          Pull ListenBrainz CF recommendations (needs 24-48h after import)
  music-discover report            Show ranked candidates
  music-discover report --tag X    Filter by tag (e.g. metal, post-hardcore, folk)
  music-discover report --min N    Minimum suggestion count (default: 2)
  music-discover status            Show cache state
"""

import json
import sys
import time
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, TextColumn

# ── Config ──────────────────────────────────────────────────────────────────────

CONFIG_PATH   = Path("~/.config/music-tools/config.yaml").expanduser()
LIBRARY_DIR   = Path("/vault/media/music")
CACHE_DIR     = Path("~/music_library/discovery").expanduser()

SIMILAR_CACHE = CACHE_DIR / "discovery_similar.json"
LBZ_CACHE     = CACHE_DIR / "discovery_lbz_recs.json"

console = Console()


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Library scan ────────────────────────────────────────────────────────────────

def library_artists() -> list[str]:
    """Return sorted list of artist names from vault directory structure."""
    skip = {"Non-Album", "Compilations", "_10_"}
    artists = [
        d.name for d in sorted(LIBRARY_DIR.iterdir())
        if d.is_dir() and d.name not in skip and not d.name.startswith(".")
    ]
    return artists


# ── Last.fm scan ────────────────────────────────────────────────────────────────

def cmd_scan() -> None:
    cfg = load_config()
    lfm = cfg["lastfm"]
    artists = library_artists()

    console.print(f"[bold]Library:[/bold] {len(artists)} artists\n")
    console.print(f"Querying Last.fm similar artists (5 req/sec)…\n")

    # Load existing cache to allow resuming
    existing: dict = {}
    if SIMILAR_CACHE.exists():
        with open(SIMILAR_CACHE) as f:
            existing = json.load(f)
        console.print(f"[dim]Resuming — {len(existing)} artists already cached[/dim]\n")

    results = dict(existing)
    to_fetch = [a for a in artists if a not in results]

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        task = progress.add_task("Fetching similar artists…", total=len(to_fetch))

        for artist in to_fetch:
            try:
                resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
                    "method":   "artist.getSimilar",
                    "artist":   artist,
                    "api_key":  lfm["api_key"],
                    "format":   "json",
                    "limit":    20,
                }, timeout=10).json()

                similar = resp.get("similarartists", {}).get("artist", [])
                results[artist] = [
                    {"name": s["name"], "match": float(s["match"])}
                    for s in similar
                ]
            except Exception as e:
                console.print(f"[dim]  {artist}: {e}[/dim]")
                results[artist] = []

            progress.advance(task)
            time.sleep(0.2)  # 5 req/sec

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SIMILAR_CACHE, "w") as f:
        json.dump(results, f)

    # Summary
    found     = sum(1 for v in results.values() if v)
    not_found = sum(1 for v in results.values() if not v)
    total_sug = sum(len(v) for v in results.values())
    unique    = len({s["name"] for v in results.values() for s in v})

    console.print(f"\n[green]✓[/green] Cached → {SIMILAR_CACHE}")
    console.print(f"  Artists with suggestions: {found}/{len(results)}")
    console.print(f"  Not found on Last.fm:     {not_found}")
    console.print(f"  Total suggestions:        {total_sug:,}")
    console.print(f"  Unique candidates:        {unique:,}")
    console.print(f"\nRun [bold]music-discover report[/bold] to see ranked results.")


# ── ListenBrainz CF recs ────────────────────────────────────────────────────────

def cmd_lbz_recs() -> None:
    cfg = load_config()
    lbz = cfg["listenbrainz"]
    headers = {"Authorization": f"Token {lbz['token']}"}

    console.print("[bold]Fetching ListenBrainz CF recommendations…[/bold]\n")

    resp = requests.get(
        f"https://api.listenbrainz.org/1/cf/recommendation/user/{lbz['username']}/recording",
        headers=headers,
        params={"count": 1000},
    )

    if resp.status_code == 204:
        console.print(
            "[yellow]ListenBrainz hasn't generated recommendations yet.[/yellow]\n"
            "This usually takes 24–48 hours after a listen import.\n"
            "Try again tomorrow — run [bold]music-discover lbz-recs[/bold]."
        )
        return

    data = resp.json()
    recs = data.get("payload", {}).get("mbids", [])

    if not recs:
        console.print("[yellow]No recommendations returned yet.[/yellow]")
        return

    # Extract artist names from recording metadata
    import musicbrainzngs
    musicbrainzngs.set_useragent("music-discovery", "0.1.0",
                                  "https://github.com/lincoln7711/music-discovery")

    artist_names: list[str] = []
    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        task = progress.add_task("Resolving artist names…", total=len(recs))
        for rec in recs:
            try:
                result = musicbrainzngs.get_recording_by_id(
                    rec["recording_mbid"], includes=["artist-credits"]
                )
                credits = result["recording"].get("artist-credit", [])
                for c in credits:
                    if isinstance(c, dict) and "artist" in c:
                        artist_names.append(c["artist"]["name"])
                        break
            except Exception:
                pass
            progress.advance(task)
            time.sleep(1.1)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LBZ_CACHE, "w") as f:
        json.dump({"artists": artist_names, "raw_count": len(recs)}, f)

    console.print(f"\n[green]✓[/green] {len(artist_names)} artist names resolved from {len(recs)} recommendations")
    console.print(f"Saved → {LBZ_CACHE}")


# ── Report ──────────────────────────────────────────────────────────────────────

def cmd_report(min_count: int = 2, tag_filter: str | None = None,
               limit: int = 50) -> None:
    if not SIMILAR_CACHE.exists():
        console.print("[yellow]No scan data — run music-discover scan first[/yellow]")
        return

    cfg = load_config()
    lfm = cfg["lastfm"]

    with open(SIMILAR_CACHE) as f:
        similar_data = json.load(f)

    library = set(library_artists())
    # Normalise library names for comparison
    library_norm = {a.lower().strip() for a in library}

    # Load ListenBrainz boost set if available
    lbz_artists: set[str] = set()
    if LBZ_CACHE.exists():
        with open(LBZ_CACHE) as f:
            lbz_data = json.load(f)
        lbz_artists = {a.lower().strip() for a in lbz_data.get("artists", [])}

    # Aggregate candidates
    candidates: dict[str, dict] = {}
    for source_artist, suggestions in similar_data.items():
        for s in suggestions:
            name  = s["name"]
            norm  = name.lower().strip()
            if norm in library_norm:
                continue  # already own it
            if name not in candidates:
                candidates[name] = {
                    "name":         name,
                    "count":        0,
                    "total_match":  0.0,
                    "suggested_by": [],
                    "lbz_boost":    norm in lbz_artists,
                }
            candidates[name]["count"]       += 1
            candidates[name]["total_match"] += s["match"]
            candidates[name]["suggested_by"].append(source_artist)

    # Score: avg_match * log(count+1) gives a natural boost for frequently appearing artists
    import math
    for c in candidates.values():
        avg_match = c["total_match"] / c["count"]
        c["score"] = avg_match * math.log(c["count"] + 1)
        if c["lbz_boost"]:
            c["score"] *= 1.25

    # Filter by minimum suggestion count
    filtered = [c for c in candidates.values() if c["count"] >= min_count]

    # Fetch tags for top candidates (only if not yet cached)
    tag_cache_path = CACHE_DIR / "discovery_tags.json"
    tag_cache: dict[str, list[str]] = {}
    if tag_cache_path.exists():
        with open(tag_cache_path) as f:
            tag_cache = json.load(f)

    top_names = {c["name"] for c in sorted(filtered, key=lambda x: -x["score"])[:200]}
    needs_tags = [n for n in top_names if n not in tag_cache]

    if needs_tags:
        console.print(f"[dim]Fetching tags for {len(needs_tags)} artists…[/dim]")
        for name in needs_tags:
            try:
                resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
                    "method":   "artist.getTopTags",
                    "artist":   name,
                    "api_key":  lfm["api_key"],
                    "format":   "json",
                }, timeout=10).json()
                tags = [t["name"].lower()
                        for t in resp.get("toptags", {}).get("tag", [])[:5]]
                tag_cache[name] = tags
            except Exception:
                tag_cache[name] = []
            time.sleep(0.2)

        with open(tag_cache_path, "w") as f:
            json.dump(tag_cache, f)

    # Apply tag filter
    for c in filtered:
        c["tags"] = tag_cache.get(c["name"], [])

    if tag_filter:
        tf = tag_filter.lower()
        filtered = [c for c in filtered if any(tf in t for t in c["tags"])]

    filtered.sort(key=lambda x: -x["score"])

    # Display
    title = f"Expansion Candidates"
    if tag_filter:
        title += f" — tag: {tag_filter}"
    title += f" (min {min_count} suggestions, top {limit})"

    t = Table(title=title, show_header=True, show_lines=False)
    t.add_column("#",           style="dim",    width=4)
    t.add_column("Artist",      style="bold",   min_width=24)
    t.add_column("Score",       justify="right", width=6)
    t.add_column("Suggested",   justify="right", width=9)
    t.add_column("LBZ",         width=4)
    t.add_column("Tags",        style="dim",    min_width=30)
    t.add_column("Because you like…", style="dim", min_width=30)

    for i, c in enumerate(filtered[:limit], 1):
        by = ", ".join(c["suggested_by"][:3])
        if len(c["suggested_by"]) > 3:
            by += f" +{len(c['suggested_by'])-3}"
        lbz = "[green]✓[/green]" if c["lbz_boost"] else ""
        tags = ", ".join(c["tags"][:4])
        t.add_row(
            str(i),
            c["name"],
            f"{c['score']:.2f}",
            str(c["count"]),
            lbz,
            tags,
            by,
        )

    console.print(t)
    console.print(f"\n[dim]{len(filtered)} total candidates | "
                  f"showing top {min(limit, len(filtered))}[/dim]")

    if lbz_artists:
        lbz_hits = sum(1 for c in filtered if c["lbz_boost"])
        console.print(f"[dim]ListenBrainz boost applied to {lbz_hits} candidates[/dim]")
    else:
        console.print(f"[dim]ListenBrainz recommendations not yet available — "
                      f"run music-discover lbz-recs after 24–48h[/dim]")

    # Save full results to CSV
    import csv
    out_path = CACHE_DIR / "discovery_candidates.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "name", "score", "count",
                                          "lbz_boost", "tags", "suggested_by"])
        w.writeheader()
        for i, c in enumerate(filtered, 1):
            w.writerow({
                "rank":        i,
                "name":        c["name"],
                "score":       f"{c['score']:.3f}",
                "count":       c["count"],
                "lbz_boost":   c["lbz_boost"],
                "tags":        "; ".join(c["tags"]),
                "suggested_by": ", ".join(c["suggested_by"]),
            })
    console.print(f"[dim]Full list → {out_path}[/dim]")


# ── Status ──────────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    artists = library_artists()
    console.print(f"Library artists: [bold]{len(artists)}[/bold]\n")

    t = Table.grid(padding=(0, 2))
    for label, path in [
        ("Similar artists cache", SIMILAR_CACHE),
        ("ListenBrainz recs",     LBZ_CACHE),
    ]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            mtime = path.stat().st_mtime
            from datetime import datetime
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            if isinstance(data, dict) and "artists" not in data:
                count = f"{len(data)} artists scanned"
            else:
                count = f"{len(data.get('artists', []))} recs"
            t.add_row(f"[green]✓[/green] {label}", count, f"[dim]{ts}[/dim]")
        else:
            t.add_row(f"[dim]✗ {label}[/dim]", "[dim]not fetched[/dim]", "")
    console.print(t)


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="music-discover")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("scan",     help="Query Last.fm similar artists for library")
    sub.add_parser("lbz-recs", help="Pull ListenBrainz CF recommendations")
    sub.add_parser("status",   help="Show cache state")

    rep = sub.add_parser("report", help="Show ranked expansion candidates")
    rep.add_argument("--tag",     help="Filter by genre tag")
    rep.add_argument("--min",     type=int, default=2,  help="Min suggestion count (default 2)")
    rep.add_argument("--limit",   type=int, default=50, help="Max rows to show (default 50)")

    args = parser.parse_args()

    if args.cmd == "scan":
        cmd_scan()
    elif args.cmd == "lbz-recs":
        cmd_lbz_recs()
    elif args.cmd == "report":
        cmd_report(min_count=args.min, tag_filter=args.tag, limit=args.limit)
    elif args.cmd == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
