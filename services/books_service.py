import os
import re
import time
from typing import Any
import requests

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 2          # nombre de nouvelles tentatives après un 429 / 5xx
CACHE_TTL_SECONDS = 600  # 10 min : évite de re-solliciter l'API pour la même recherche

_HEADERS = {"User-Agent": os.getenv("BOOKS_USER_AGENT", "MathieuMediatheque/1.0")}
_cache: dict[tuple[str, int, str], tuple[float, list[dict[str, Any]]]] = {}


def _extract_year(published_date: str | None) -> int | None:
    """Extrait l'année sur 4 chiffres depuis une chaîne type '2021-05-14' ou '2021'."""
    if not published_date:
        return None
    match = re.search(r"\b(1[4-9]\d{2}|20\d{2})\b", published_date)
    return int(match.group(1)) if match else None


def _extract_cover_url(image_links: dict[str, Any] | None) -> str | None:
    """Sélectionne la meilleure couverture disponible et force le protocole HTTPS."""
    if not image_links:
        return None
    for key in ("thumbnail", "smallThumbnail", "medium", "large"):
        url = image_links.get(key)
        if url:
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            return url
    return None


def _extract_isbn(identifiers: list[dict[str, str]] | None) -> str | None:
    """Récupère l'ISBN-13 en priorité, sinon l'ISBN-10."""
    if not identifiers:
        return None
    isbn_13 = None
    isbn_10 = None
    for entry in identifiers:
        id_type = entry.get("type")
        identifier = entry.get("identifier")
        if id_type == "ISBN_13" and identifier:
            isbn_13 = identifier
        elif id_type == "ISBN_10" and identifier:
            isbn_10 = identifier
    return isbn_13 or isbn_10


def _get_with_retry(url: str, params: dict[str, Any]) -> requests.Response:
    """GET avec nouvelles tentatives (backoff) sur 429 et 5xx. Respecte Retry-After si court."""
    response = requests.get(url, params=params, headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
    for attempt in range(MAX_RETRIES):
        if response.status_code != 429 and response.status_code < 500:
            break
        retry_after = response.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
        time.sleep(min(delay, 5))
        response = requests.get(url, params=params, headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response


def _search_google_books(q_param: str, max_results: int, lang: str) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "q": q_param,
        "maxResults": max(1, min(max_results, 40)),
        "printType": "books",
        "langRestrict": lang,
    }
    # Sans clé, le quota Google est partagé par IP et saturé très vite (429).
    api_key = os.getenv("GOOGLE_BOOKS_API_KEY")
    if api_key:
        params["key"] = api_key

    payload = _get_with_retry(GOOGLE_BOOKS_URL, params).json()

    results: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        volume_info = item.get("volumeInfo") or {}
        authors = volume_info.get("authors") or []
        author_str = ", ".join(authors) if authors else "Auteur inconnu"

        results.append({
            "google_id": item.get("id"),
            "title": volume_info.get("title") or "Titre inconnu",
            "subtitle": volume_info.get("subtitle"),
            "author": author_str,
            "creator": author_str,  # Alias pratique pour le Hub / ajouts récents
            "year": _extract_year(volume_info.get("publishedDate")),
            "summary": volume_info.get("description") or "Aucun résumé disponible.",
            "cover_url": _extract_cover_url(volume_info.get("imageLinks")),
            "isbn": _extract_isbn(volume_info.get("industryIdentifiers")),
            "page_count": volume_info.get("pageCount"),
        })
    return results


def _search_open_library(q_param: str, max_results: int) -> list[dict[str, Any]]:
    """Repli gratuit et sans clé : Open Library."""
    params: dict[str, Any] = {
        "q": q_param,
        "limit": max(1, min(max_results, 40)),
        "fields": "key,title,subtitle,author_name,first_publish_year,isbn,cover_i,number_of_pages_median",
    }
    payload = _get_with_retry(OPEN_LIBRARY_URL, params).json()

    results: list[dict[str, Any]] = []
    for doc in payload.get("docs") or []:
        authors = doc.get("author_name") or []
        author_str = ", ".join(authors) if authors else "Auteur inconnu"
        isbns = doc.get("isbn") or []
        isbn_13 = next((i for i in isbns if len(i) == 13), None)
        cover_id = doc.get("cover_i")

        results.append({
            "google_id": None,
            "title": doc.get("title") or "Titre inconnu",
            "subtitle": doc.get("subtitle"),
            "author": author_str,
            "creator": author_str,
            "year": doc.get("first_publish_year"),
            "summary": "Aucun résumé disponible.",
            "cover_url": OPEN_LIBRARY_COVER_URL.format(cover_id=cover_id) if cover_id else None,
            "isbn": isbn_13 or (isbns[0] if isbns else None),
            "page_count": doc.get("number_of_pages_median"),
        })
    return results


def search_book(query: str, max_results: int = 1, lang: str = "fr") -> list[dict[str, Any]]:
    """
    Recherche un livre par titre, auteur ou ISBN.

    Google Books en premier (avec retry sur 429), puis Open Library en repli.
    Les résultats sont gardés en cache quelques minutes.
    Lève requests.RequestException seulement si les deux services échouent.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    cache_key = (cleaned_query.lower(), max_results, lang)
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    # Si l'utilisateur saisit un ISBN (10 ou 13 chiffres avec éventuels tirets/espaces)
    normalized_isbn = re.sub(r"[-\s]", "", cleaned_query)
    if re.fullmatch(r"(?:\d{10}|\d{13}|\d{9}[\dXx])", normalized_isbn):
        q_param = f"isbn:{normalized_isbn}"
    else:
        q_param = cleaned_query

    try:
        results = _search_google_books(q_param, max_results, lang)
        # Google ne trouve rien : on tente Open Library avant de conclure
        if not results:
            results = _search_open_library(q_param, max_results)
    except requests.RequestException:
        results = _search_open_library(q_param, max_results)

    if results:
        _cache[cache_key] = (time.time(), results)
    return results


def get_book(query: str, lang: str = "fr") -> dict[str, Any] | None:
    """Retourne le premier résultat trouvé pour une requête donnée, ou None."""
    results = search_book(query=query, max_results=1, lang=lang)
    return results[0] if results else None
