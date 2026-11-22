import requests

API_KEY = "b9e11dd2b1af80d311f2fb0f381a5ddc" 
BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def search_and_get_movie_details(title: str, year: str = None) -> dict | None:
    # 1. Tentative dans la base des FILMS
    search_url = f"{BASE_URL}/search/movie"
    results = []
    
    if year:
        params = {"api_key": API_KEY, "query": title, "year": year, "language": "fr-FR"}
        res = requests.get(search_url, params=params, headers=HEADERS)
        if res.status_code == 200:
            results = res.json().get("results", [])

    if not results:
        params = {"api_key": API_KEY, "query": title, "language": "fr-FR"}
        res = requests.get(search_url, params=params, headers=HEADERS)
        if res.status_code == 200:
            results = res.json().get("results", [])

    # Si un film est trouvé, on récupère ses détails
    if results:
        movie_id = results[0]["id"]
        details_url = f"{BASE_URL}/movie/{movie_id}"
        details_res = requests.get(details_url, params={"api_key": API_KEY, "append_to_response": "credits", "language": "fr-FR"}, headers=HEADERS)
        
        if details_res.status_code == 200:
            data = details_res.json()
            crew = data.get("credits", {}).get("crew", [])
            director = next((m["name"] for m in crew if m["job"] == "Director"), "Inconnu")
            actors = ", ".join([a["name"] for a in data.get("credits", {}).get("cast", [])[:5]])
            genres = ", ".join([g["name"] for g in data.get("genres", [])])
            poster_path = data.get("poster_path")
            release_date = data.get("release_date", "")
            
            return {
                "title": data.get("title"),
                "year": release_date.split("-")[0] if release_date else "Inconnue",
                "director": director,
                "actors": actors,
                "genres": genres,
                "synopsis": data.get("overview", "Aucun synopsis disponible."),
                "poster_url": f"{IMAGE_BASE_URL}{poster_path}" if poster_path else ""
            }

    # 2. Si aucun film n'est trouvé, on cherche dans la base des SÉRIES TV (/search/tv)
    tv_search_url = f"{BASE_URL}/search/tv"
    tv_results = []
    
    if year:
        params = {"api_key": API_KEY, "query": title, "first_air_date_year": year, "language": "fr-FR"}
        res = requests.get(tv_search_url, params=params, headers=HEADERS)
        if res.status_code == 200:
            tv_results = res.json().get("results", [])

    if not tv_results:
        params = {"api_key": API_KEY, "query": title, "language": "fr-FR"}
        res = requests.get(tv_search_url, params=params, headers=HEADERS)
        if res.status_code == 200:
            tv_results = res.json().get("results", [])

    if tv_results:
        tv_id = tv_results[0]["id"]
        tv_details_url = f"{BASE_URL}/tv/{tv_id}"
        tv_details_res = requests.get(tv_details_url, params={"api_key": API_KEY, "append_to_response": "credits", "language": "fr-FR"}, headers=HEADERS)
        
        if tv_details_res.status_code == 200:
            data = tv_details_res.json()
            # Pour les séries, le créateur remplace souvent le réalisateur
            creators = data.get("created_by", [])
            director = creators[0]["name"] if creators else "Inconnu"
            actors = ", ".join([a["name"] for a in data.get("credits", {}).get("cast", [])[:5]])
            genres = ", ".join([g["name"] for g in data.get("genres", [])])
            poster_path = data.get("poster_path")
            first_air = data.get("first_air_date", "")
            
            return {
                "title": data.get("name"),  # Les séries utilisent "name" au lieu de "title"
                "year": first_air.split("-")[0] if first_air else "Inconnue",
                "director": director,
                "actors": actors,
                "genres": genres,
                "synopsis": data.get("overview", "Aucun synopsis disponible."),
                "poster_url": f"{IMAGE_BASE_URL}{poster_path}" if poster_path else ""
            }

    return None

# ---------------------------------------------------------------------------
# Recherche avec choix (page « Ajouter ») : plusieurs candidats au lieu du premier
# ---------------------------------------------------------------------------
def search_candidates(title: str, max_results: int = 6) -> list[dict]:
    """Retourne plusieurs films (puis séries) correspondant au titre, pour que l'utilisateur choisisse."""
    cleaned = title.strip()
    if not cleaned:
        return []

    candidates: list[dict] = []
    for kind, endpoint, title_key, date_key in (
        ("movie", "/search/movie", "title", "release_date"),
        ("tv", "/search/tv", "name", "first_air_date"),
    ):
        res = requests.get(
            f"{BASE_URL}{endpoint}",
            params={"api_key": API_KEY, "query": cleaned, "language": "fr-FR"},
            headers=HEADERS,
            timeout=10,
        )
        res.raise_for_status()
        for item in res.json().get("results", []):
            poster_path = item.get("poster_path")
            date = item.get(date_key) or ""
            candidates.append({
                "kind": kind,
                "tmdb_id": item["id"],
                "title": item.get(title_key) or "Titre inconnu",
                "year": date.split("-")[0] if date else "",
                "overview": item.get("overview") or "",
                "poster_url": f"{IMAGE_BASE_URL}{poster_path}" if poster_path else "",
            })

    # Les films d'abord, puis les séries ; on garde les mieux classés de chaque catégorie
    movies = [c for c in candidates if c["kind"] == "movie"]
    shows = [c for c in candidates if c["kind"] == "tv"]
    merged = movies[:max_results] + shows[: max(0, max_results - len(movies[:max_results]))]
    return merged[:max_results]


def get_details(kind: str, tmdb_id: int) -> dict | None:
    """Détails complets d'un film ('movie') ou d'une série ('tv') choisi par son identifiant TMDB."""
    if kind not in ("movie", "tv"):
        return None

    res = requests.get(
        f"{BASE_URL}/{kind}/{int(tmdb_id)}",
        params={"api_key": API_KEY, "append_to_response": "credits", "language": "fr-FR"},
        headers=HEADERS,
        timeout=10,
    )
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
