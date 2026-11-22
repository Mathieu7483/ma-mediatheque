import os
from pathlib import Path

import requests

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
DEFAULT_TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


class TMDBConfigError(requests.RequestException):
    """Clé TMDB absente : hérite de RequestException pour être affichée comme les autres erreurs d'API."""


def _api_key() -> str:
    """Lit TMDB_API_KEY dans l'environnement, sinon dans le fichier .env à la racine du projet.

    Lue au moment de l'appel (et non à l'import) : app.py charge le .env après avoir importé
    ce module, et seed.py peut être lancé seul, sans passer par app.py.
    """
    key = os.getenv("TMDB_API_KEY", "").strip()
    if key:
        return key

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if line.startswith("TMDB_API_KEY") and "=" in line:
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value

    raise TMDBConfigError("TMDB_API_KEY absente : ajoute-la dans le fichier .env.")


def _get(path: str, **params) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}",
        params={"api_key": _api_key(), "language": "fr-FR", **params},
        headers=HEADERS,
        timeout=DEFAULT_TIMEOUT,
    )


def get_details(kind: str, tmdb_id: int) -> dict | None:
    """Détails complets d'un film ('movie') ou d'une série ('tv') choisi par son identifiant TMDB."""
    if kind not in ("movie", "tv"):
        return None

    res = _get(f"/{kind}/{int(tmdb_id)}", append_to_response="credits")
    if res.status_code != 200:
        return None
    data = res.json()

    actors = ", ".join(a["name"] for a in data.get("credits", {}).get("cast", [])[:5])
    genres = ", ".join(g["name"] for g in data.get("genres", []))
    poster_path = data.get("poster_path")

    if kind == "movie":
        crew = data.get("credits", {}).get("crew", [])
        director = next((m["name"] for m in crew if m.get("job") == "Director"), "Inconnu")
        title = data.get("title")
        date = data.get("release_date", "")
    else:
        # Pour les séries, le créateur remplace le réalisateur
        creators = data.get("created_by", [])
        director = creators[0]["name"] if creators else "Inconnu"
        title = data.get("name")
        date = data.get("first_air_date", "")

    return {
        "title": title,
        "year": date.split("-")[0] if date else "Inconnue",
        "director": director,
        "actors": actors,
        "genres": genres,
        "synopsis": data.get("overview") or "Aucun synopsis disponible.",
        "poster_url": f"{IMAGE_BASE_URL}{poster_path}" if poster_path else "",
    }


def search_candidates(title: str, max_results: int = 6) -> list[dict]:
    """Plusieurs films (puis séries) correspondant au titre, pour que l'utilisateur choisisse."""
    cleaned = title.strip()
    if not cleaned:
        return []

    movies: list[dict] = []
    shows: list[dict] = []
    for kind, endpoint, title_key, date_key, bucket in (
        ("movie", "/search/movie", "title", "release_date", movies),
        ("tv", "/search/tv", "name", "first_air_date", shows),
    ):
        res = _get(endpoint, query=cleaned)
        res.raise_for_status()
        for item in res.json().get("results", []):
            poster_path = item.get("poster_path")
            date = item.get(date_key) or ""
            bucket.append({
                "kind": kind,
                "tmdb_id": item["id"],
                "title": item.get(title_key) or "Titre inconnu",
                "year": date.split("-")[0] if date else "",
                "overview": item.get("overview") or "",
                "poster_url": f"{IMAGE_BASE_URL}{poster_path}" if poster_path else "",
            })

    # Les films d'abord, puis les séries pour compléter
    merged = movies[:max_results]
    merged += shows[: max(0, max_results - len(merged))]
    return merged


def search_and_get_movie_details(title: str, year: str = None) -> dict | None:
    """Premier résultat (film, sinon série) avec ses détails. Utilisé par seed.py (import en masse)."""
    for kind, endpoint, year_param in (
        ("movie", "/search/movie", "year"),
        ("tv", "/search/tv", "first_air_date_year"),
    ):
        results = []
        if year:
            res = _get(endpoint, query=title, **{year_param: year})
            if res.status_code == 200:
                results = res.json().get("results", [])
        if not results:
            res = _get(endpoint, query=title)
            if res.status_code == 200:
                results = res.json().get("results", [])

        if results:
            details = get_details(kind, results[0]["id"])
            if details:
                return details

    return None