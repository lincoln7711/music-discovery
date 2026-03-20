#!/usr/bin/env python3
"""
listen-import — pull full listen history, merge sources, submit gaps to ListenBrainz.

Commands:
  listen-import fetch-lastfm     Pull full Last.fm history → cache
  listen-import parse-amazon     Parse Amazon export → cache
  listen-import compare          Show timeline overlap between sources
  listen-import submit           Submit Amazon gap listens to ListenBrainz
  listen-import status           Show cache state and counts
"""

import csv
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import musicbrainzngs
import pylast
import requests
import yaml
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

# ── Config ─────────────────────────────────────────────────────────────────────

CONFIG_PATH  = Path("~/.config/music-tools/config.yaml").expanduser()
CACHE_DIR    = Path("~/music_library/discovery").expanduser()
AMAZON_ZIP   = Path("/vault/media/incoming/amazon_music/Amazon-Music.zip")

LASTFM_CACHE    = CACHE_DIR / "lastfm_history.json"
AMAZON_CACHE    = CACHE_DIR / "amazon_history.json"
COMBINED_CACHE  = CACHE_DIR / "combined_history.json"

console = Console()

musicbrainzngs.set_useragent("music-discovery", "0.1.0", "https://github.com/lincoln7711/music-discovery")


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def lastfm_network(cfg: dict) -> pylast.LastFMNetwork:
    lfm = cfg["lastfm"]
    return pylast.LastFMNetwork(
        api_key=lfm["api_key"],
        api_secret=lfm["api_secret"],
        username=lfm["username"],
    )


# ── Last.fm fetch ──────────────────────────────────────────────────────────────

def cmd_fetch_lastfm() -> None:
    cfg = load_config()
    lfm = cfg["lastfm"]
    username = lfm["username"]
    api_key  = lfm["api_key"]

    # Get total count first
    resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
        "method": "user.getinfo", "user": username,
        "api_key": api_key, "format": "json",
    }).json()
    total = int(resp["user"]["playcount"])
    limit = 200
    total_pages = (total // limit) + 1
    console.print(f"[bold]Last.fm:[/bold] {username} — {total:,} scrobbles, {total_pages} pages…\n")

    scrobbles = []

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        task = progress.add_task("Fetching Last.fm pages…", total=total_pages)

        for page in range(1, total_pages + 2):
            resp = requests.get("https://ws.audioscrobbler.com/2.0/", params={
                "method": "user.getrecenttracks",
                "user": username, "api_key": api_key,
                "format": "json", "limit": limit, "page": page,
            }).json()

            tracks = resp.get("recenttracks", {}).get("track", [])
            if not tracks:
                break

            for t in tracks:
                if "@attr" in t and t["@attr"].get("nowplaying"):
                    continue  # skip now playing
                date = t.get("date", {}).get("uts")
                if not date:
                    continue
                scrobbles.append({
                    "source":    "lastfm",
                    "timestamp": int(date),
                    "artist":    t.get("artist", {}).get("#text", ""),
                    "title":     t.get("name", ""),
                    "album":     t.get("album", {}).get("#text", ""),
                })

            progress.advance(task)
            time.sleep(0.25)

            actual_pages = int(resp["recenttracks"]["@attr"]["totalPages"])
            if page >= actual_pages:
                break

    scrobbles.sort(key=lambda x: x["timestamp"])
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LASTFM_CACHE, "w") as f:
        json.dump(scrobbles, f)

    console.print(f"\n[green]✓[/green] Saved {len(scrobbles):,} scrobbles → {LASTFM_CACHE}")
    _show_year_breakdown(scrobbles, "Last.fm")


# ── Amazon parse ───────────────────────────────────────────────────────────────

def cmd_parse_amazon() -> None:
    if not AMAZON_ZIP.exists():
        console.print(f"[red]Amazon zip not found: {AMAZON_ZIP}[/red]")
        return

    console.print(f"[bold]Parsing Amazon Music export…[/bold]\n")

    with zipfile.ZipFile(AMAZON_ZIP) as z:
        listen_raw  = z.read("listening.csv").decode("utf-8-sig")
        library_raw = z.read("library.csv").decode("utf-8-sig")

    listens  = list(csv.DictReader(listen_raw.splitlines()))
    library  = list(csv.DictReader(library_raw.splitlines()))

    # Build lookup tables
    lib_by_track_asin  = {r["asin"]: r for r in library if r["asin"]}
    artist_by_asin     = {r["artistAsin"]: r["artistName"]
                          for r in library if r["artistAsin"] and r["artistName"]}

    resolved, unresolved_raw = [], []

    for row in listens:
        # Skip very short plays (< 10s) and init failures
        try:
            duration_ms = int(row["consumptionDurationMs"] or 0)
        except ValueError:
            duration_ms = 0
        if duration_ms < 10_000 or row["terminationReason"] == "trackInitFailed":
            continue

        ts_str = row["timestamp"].replace(" UTC", "").strip()
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
        except ValueError:
            continue

        title = row["title"].strip()

        # Try track ASIN → library
        if row["asin"] in lib_by_track_asin:
            lib = lib_by_track_asin[row["asin"]]
            resolved.append({
                "source":    "amazon",
                "timestamp": ts,
                "artist":    lib["artistName"],
                "title":     lib["title"],
                "album":     lib["albumName"],
                "mbid":      None,
            })
        # Try artist ASIN → library
        elif row["artistAsin"] in artist_by_asin:
            resolved.append({
                "source":    "amazon",
                "timestamp": ts,
                "artist":    artist_by_asin[row["artistAsin"]],
                "title":     title,
                "album":     "",
                "mbid":      None,
            })
        else:
            unresolved_raw.append({"timestamp": ts, "title": title,
                                   "artist_asin": row["artistAsin"]})

    console.print(f"Resolved via library:   [green]{len(resolved)}[/green]")
    console.print(f"Needs MusicBrainz lookup: [yellow]{len(unresolved_raw)}[/yellow]")

    # MusicBrainz title search for unresolved
    # Group by artist_asin to minimise API calls
    asin_groups: dict[str, list] = {}
    for r in unresolved_raw:
        asin_groups.setdefault(r["artist_asin"], []).append(r)

    mb_resolved, mb_failed = 0, 0

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        # Sample one title per artist_asin to find artist name
        task = progress.add_task("MusicBrainz lookups…", total=len(unresolved_raw))

        asin_artist_cache: dict[str, str] = {}

        for artist_asin, rows in asin_groups.items():
            # Try to find artist name from first title in group
            sample_title = rows[0]["title"]
            artist_name = None

            if artist_asin not in asin_artist_cache:
                try:
                    result = musicbrainzngs.search_recordings(
                        recording=sample_title, limit=3
                    )
                    for rec in result["recording-list"]:
                        if rec.get("artist-credit"):
                            candidate = rec["artist-credit"][0].get("artist", {}).get("name", "")
                            if candidate:
                                asin_artist_cache[artist_asin] = candidate
                                artist_name = candidate
                                break
                except Exception:
                    pass
                time.sleep(1.1)  # MusicBrainz rate limit
            else:
                artist_name = asin_artist_cache[artist_asin]

            for r in rows:
                if artist_name:
                    resolved.append({
                        "source":    "amazon",
                        "timestamp": r["timestamp"],
                        "artist":    artist_name,
                        "title":     r["title"],
                        "album":     "",
                        "mbid":      None,
                    })
                    mb_resolved += 1
                else:
                    mb_failed += 1
                progress.advance(task)

    resolved.sort(key=lambda x: x["timestamp"])

    console.print(f"\nMusicBrainz resolved:  [green]{mb_resolved}[/green]")
    console.print(f"Unresolvable (no MBID): [dim]{mb_failed}[/dim]")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(AMAZON_CACHE, "w") as f:
        json.dump(resolved, f)

    console.print(f"\n[green]✓[/green] Saved {len(resolved):,} Amazon listens → {AMAZON_CACHE}")
    _show_year_breakdown(resolved, "Amazon")


# ── Compare ────────────────────────────────────────────────────────────────────

def cmd_compare() -> None:
    if not LASTFM_CACHE.exists():
        console.print("[yellow]Last.fm cache missing — run fetch-lastfm first[/yellow]")
        return
    if not AMAZON_CACHE.exists():
        console.print("[yellow]Amazon cache missing — run parse-amazon first[/yellow]")
        return

    with open(LASTFM_CACHE) as f:
        lastfm = json.load(f)
    with open(AMAZON_CACHE) as f:
        amazon = json.load(f)

    # Year breakdown side by side
    def by_year(listens):
        counts: dict[int, int] = {}
        for l in listens:
            y = datetime.fromtimestamp(l["timestamp"], tz=timezone.utc).year
            counts[y] = counts.get(y, 0) + 1
        return counts

    lf_years = by_year(lastfm)
    am_years = by_year(amazon)
    all_years = sorted(set(lf_years) | set(am_years))

    t = Table(title="Listen History by Year", show_header=True)
    t.add_column("Year", style="bold")
    t.add_column("Last.fm", justify="right")
    t.add_column("Amazon", justify="right")
    t.add_column("Combined", justify="right")
    t.add_column("Coverage")

    for year in all_years:
        lf = lf_years.get(year, 0)
        am = am_years.get(year, 0)
        combined = lf + am
        bar = "█" * min(40, combined // 50)
        t.add_row(str(year), str(lf) if lf else "—", str(am) if am else "—",
                  str(combined), f"[cyan]{bar}[/cyan]")

    console.print(t)
    console.print(f"\nTotal Last.fm:  {len(lastfm):,}")
    console.print(f"Total Amazon:   {len(amazon):,}")
    console.print(f"Combined:       {len(lastfm) + len(amazon):,}")

    # Estimate gap: Amazon listens with no Last.fm scrobble within ±60s
    lfm_timestamps = set(l["timestamp"] for l in lastfm)
    gap_fills = [a for a in amazon
                 if not any(abs(a["timestamp"] - t) < 60 for t in lfm_timestamps)]
    console.print(f"\nAmazon listens not in Last.fm (gap fills): [green]{len(gap_fills):,}[/green]")
    console.print("These are the listens that would be submitted to ListenBrainz.")


# ── Submit ─────────────────────────────────────────────────────────────────────

def cmd_submit() -> None:
    if not AMAZON_CACHE.exists():
        console.print("[yellow]Amazon cache missing — run parse-amazon first[/yellow]")
        return

    cfg = load_config()
    lbz = cfg["listenbrainz"]

    with open(AMAZON_CACHE) as f:
        amazon = json.load(f)

    # If Last.fm cache exists, use it to deduplicate
    lfm_timestamps: set[int] = set()
    if LASTFM_CACHE.exists():
        with open(LASTFM_CACHE) as f:
            lastfm = json.load(f)
        lfm_timestamps = set(l["timestamp"] for l in lastfm)
        console.print(f"Deduplicating against {len(lfm_timestamps):,} Last.fm scrobbles…")

    # Only submit listens not already in Last.fm (within ±60s), with required fields
    to_submit = [
        a for a in amazon
        if a.get("artist") and a.get("title")
        and not any(abs(a["timestamp"] - t) < 60 for t in lfm_timestamps)
    ]

    console.print(f"[bold]Submitting {len(to_submit):,} listens to ListenBrainz…[/bold]")
    console.print("[dim]Rate limit: 1 req/sec, batches of 100[/dim]\n")

    headers = {
        "Authorization": f"Token {lbz['token']}",
        "Content-Type": "application/json",
    }

    submitted, failed = 0, 0
    batch_size = 100

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        task = progress.add_task("Submitting…", total=len(to_submit))

        for i in range(0, len(to_submit), batch_size):
            batch = to_submit[i : i + batch_size]
            payload_listens = []
            for listen in batch:
                track_meta: dict = {
                    "artist_name": listen["artist"],
                    "track_name":  listen["title"],
                    "additional_info": {
                        "music_service":      "music.amazon.com",
                        "submission_client":  "music-discovery",
                    },
                }
                if listen.get("album"):
                    track_meta["release_name"] = listen["album"]
                entry = {
                    "listened_at":   listen["timestamp"],
                    "track_metadata": track_meta,
                }
                if listen.get("mbid"):
                    entry["track_metadata"]["additional_info"]["recording_mbid"] = listen["mbid"]
                payload_listens.append(entry)

            payload = {"listen_type": "import", "payload": payload_listens}
            try:
                resp = requests.post(
                    "https://api.listenbrainz.org/1/submit-listens",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                if resp.status_code == 200:
                    submitted += len(batch)
                else:
                    console.print(f"[yellow]Batch {i//batch_size+1} failed: {resp.status_code} {resp.text[:80]}[/yellow]")
                    failed += len(batch)
            except Exception as e:
                console.print(f"[red]Batch error: {e}[/red]")
                failed += len(batch)

            progress.advance(task, len(batch))
            time.sleep(1.0)

    console.print(f"\n[green]✓ Submitted: {submitted:,}[/green]")
    if failed:
        console.print(f"[red]✗ Failed:    {failed:,}[/red]")


# ── Status ─────────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    t = Table.grid(padding=(0, 2))
    for label, path in [
        ("Last.fm cache", LASTFM_CACHE),
        ("Amazon cache", AMAZON_CACHE),
    ]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            t.add_row(f"[green]✓[/green] {label}", f"{len(data):,} listens", f"[dim]{mtime}[/dim]")
        else:
            t.add_row(f"[dim]✗ {label}[/dim]", "[dim]not fetched[/dim]", "")
    console.print(t)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _show_year_breakdown(listens: list, label: str) -> None:
    from collections import Counter
    years = Counter(
        datetime.fromtimestamp(l["timestamp"], tz=timezone.utc).year
        for l in listens
    )
    console.print(f"\n[bold]{label} by year:[/bold]")
    for year in sorted(years):
        bar = "█" * min(40, years[year] // 50)
        console.print(f"  {year}: {years[year]:5d}  [cyan]{bar}[/cyan]")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    cmds = {
        "fetch-lastfm": cmd_fetch_lastfm,
        "parse-amazon": cmd_parse_amazon,
        "compare":      cmd_compare,
        "submit":       cmd_submit,
        "status":       cmd_status,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        console.print("[bold]listen-import[/bold] — merge listen history and submit to ListenBrainz\n")
        for name in cmds:
            console.print(f"  listen-import [bold cyan]{name}[/bold cyan]")
        sys.exit(1)

    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
