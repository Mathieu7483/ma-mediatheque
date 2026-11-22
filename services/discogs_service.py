import os
from typing import Any
import requests

DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"
DISCOGS_RELEASE_URL = "https://api.discogs.com/releases/{release_id}"
DEFAULT_TIMEOUT = 10


def is_authenticated() -> bool:
    """Sans token, Discogs renvoie des images vides (spacer.gif) : pas de pochettes."""
    return bool(os.getenv("DISCOGS_TOKEN"))


def _get_headers() -> dict[str, str]:
    """Discogs exige un User-Agent explicite ; on y joint le token s'il est défini."""
    user_agent = os.getenv("DISCOGS_USER_AGENT", "MathieuMediatheque/1.0")
    headers = {"User-Agent": user_agent}
    token = os.getenv("DISCOGS_TOKEN")
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    return headers


def _split_artist_and_title(raw_title: str, fallback_artist: str = "") -> tuple[str, str]:
    """Découpe un titre Discogs type 'Pink Floyd - The Dark Side of the Moon'."""
    if " - " in raw_title:
        artist_part, title_part = raw_title.split(" - ", 1)
        return (artist_part.strip() or fallback_artist or "Artiste inconnu"), title_part.strip()
    return (fallback_artist.strip() or "Artiste inconnu"), raw_title.strip() or "Album inconnu"


def _clean_cover_url(url: str | None) -> str | None:
    if not url or "spacer.gif" in url:
        return None
    return url


def _extract_tracklist(raw_tracks: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Extrait les pistes utiles (position, titre, durée) en ignorant les titres de section vides."""
    tracks: list[dict[str, str]] = []
    for entry in raw_tracks or []:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        tracks.append({
            "position": (entry.get("position") or "").strip(),
            "title": title,
            "duration": (entry.get("duration") or "").strip(),
        })
    return tracks


def _format_tracklist_text(tracks: list[dict[str, str]]) -> str:
    """Formate la tracklist en texte lisible pour stockage en base."""
    lines: list[str] = []
    for track in tracks:
        prefix = f"{track['position']}. " if track["position"] else ""
        suffix = f" ({track['duration']})" if track["duration"] else ""
        lines.append(f"{prefix}{track['title']}{suffix}")
    return "\n".join(lines)


def get_release_details(release_id: int | str) -> dict[str, Any] | None:
    """Récupère les détails complets d'une release Discogs (pochettes HD et tracklist)."""
    rid = str(release_id).strip()
    if not rid.isdigit():
        return None

    params: dict[str, Any] = {}
    token = os.getenv("DISCOGS_TOKEN")
    if token:
        params["token"] = token

    url = DISCOGS_RELEASE_URL.format(release_id=rid)
    response = requests.get(
        url,
        params=params,
        headers=_get_headers(),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    artists_list = data.get("artists") or []
    artist_names = [a.get("name", "").strip() for a in artists_list if a.get("name")]
    cleaned_artists = [
        name.split(" (")[0] if name.endswith(")") and " (" in name else name
        for name in artist_names
    ]
    artist = ", ".join(cleaned_artists) if cleaned_artists else "Artiste inconnu"

    images_raw = data.get("images") or []
    covers: list[str] = []
    for img in images_raw:
        img_url = _clean_cover_url(img.get("uri") or img.get("uri150") or img.get("resource_url"))
        if img_url and img_url not in covers:
            covers.append(img_url)

    cover_url = covers[0] if covers else _clean_cover_url(data.get("thumb"))
    tracks = _extract_tracklist(data.get("tracklist"))

    return {
        "discogs_id": data.get("id"),
        "title": (data.get("title") or "Album inconnu").strip(),
        "artist": artist,
        "creator": artist,
        "year": str(data["year"]) if data.get("year") else "",
        "genres": ", ".join(data.get("genres") or []),
        "styles": ", ".join(data.get("styles") or []),
        "cover_url": cover_url,
        "covers": covers,
        "tracklist": tracks,
        "tracklist_text": _format_tracklist_text(tracks),
    }


def search_albums(
    query: str,
    artist: str = "",
    max_results: int = 6,
    include_tracklist: bool = False,
) -> list[dict[str, Any]]:
    """Recherche des éditions CD sur Discogs."""
    cleaned_query = query.strip()
    cleaned_artist = artist.strip()
    if not cleaned_query and not cleaned_artist:
        return []

    params: dict[str, Any] = {
        "type": "release",
        "format": "CD",
        "per_page": max(1, min(max_results, 25)),
    }

    if cleaned_query:
        params["q"] = cleaned_query
    if cleaned_artist:
        params["artist"] = cleaned_artist

    token = os.getenv("DISCOGS_TOKEN")
    if token:
        params["token"] = token

    response = requests.get(
        DISCOGS_SEARCH_URL,
        params=params,
        headers=_get_headers(),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        raw_title = item.get("title") or ""
        parsed_artist, parsed_title = _split_artist_and_title(raw_title, cleaned_artist)

        genres_list = item.get("genre") or []
        styles_list = item.get("style") or []
        barcodes_list = item.get("barcode") or []
        cover_url = _clean_cover_url(item.get("cover_image") or item.get("thumb"))

        entry: dict[str, Any] = {
            "discogs_id": item.get("id"),
            "title": parsed_title,
            "artist": parsed_artist,
            "creator": parsed_artist,
            "year": str(item["year"]) if item.get("year") else "",
            "genres": ", ".join(genres_list),
            "styles": ", ".join(styles_list),
            "barcode": barcodes_list[0] if barcodes_list else None,
            "cover_url": cover_url,
            "tracklist": [],
            "tracklist_text": "",
        }

        if include_tracklist and item.get("id"):
            try:
                details = get_release_details(item["id"])
                if details:
                    entry["cover_url"] = details["cover_url"] or entry["cover_url"]
                    entry["tracklist"] = details["tracklist"]
                    entry["tracklist_text"] = details["tracklist_text"]
            except requests.RequestException:
                pass

        results.append(entry)

    return results