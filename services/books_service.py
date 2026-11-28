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
_key_warned = False
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


def _search_google_books(q_param: str, max_results: int, lang: str | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "q": q_param,
        "maxResults": max(1, min(max_results, 40)),
        "printType": "books",
    }
    # langRestrict écarte les éditions dont la langue n'est pas renseignée : on l'évite pour un ISBN
    if lang:
        params["langRestrict"] = lang
    # Sans clé, le quota Google est partagé par IP et saturé très vite (429).
    api_key = os.getenv("GOOGLE_BOOKS_API_KEY")
    if api_key:
        params["key"] = api_key

    global _key_warned
    try:
        payload = _get_with_retry(GOOGLE_BOOKS_URL, params).json()
    except requests.HTTPError as exc:
        # 400/403 avec une clé : clé invalide, API « Books » non activée ou clé restreinte.
        # On réessaie sans clé plutôt que de tout bloquer.
        status = exc.response.status_code if exc.response is not None else None
        if "key" in params and status in (400, 403):
            if not _key_warned:
                print(f"[Google Books] clé API refusée (HTTP {status}) : vérifie qu'elle est valide, que "
                      "l'API « Books API » est activée dans Google Cloud et que la clé n'est pas restreinte. "
                      "Poursuite sans clé.")
                _key_warned = True
            params.pop("key")
            payload = _get_with_retry(GOOGLE_BOOKS_URL, params).json()
        else:
            raise

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


def normalize_isbn(text: str) -> str | None:
    """Retourne l'ISBN nettoyé (sans tirets/espaces) si le texte en est un, sinon None."""
    cleaned = re.sub(r"[-\s]", "", text or "")
    return cleaned.upper() if re.fullmatch(r"\d{13}|\d{9}[\dXx]|\d{10}", cleaned) else None


def isbn_variants(isbn: str) -> list[str]:
    """ISBN-13 et ISBN-10 du même livre : Google n'en connaît parfois qu'un des deux."""
    if len(isbn) == 10:
        core = "978" + isbn[:9]
        check = (10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core)) % 10) % 10
        return [core + str(check), isbn]
    if len(isbn) == 13 and isbn.startswith("978"):
        core = isbn[3:12]
        total = sum(int(d) * (10 - i) for i, d in enumerate(core))
        check = (11 - total % 11) % 11
        return [isbn, core + ("X" if check == 10 else str(check))]
    return [isbn]


def search_book(query: str, max_results: int = 1, lang: str = "fr",
                fallback_on_error: bool = True) -> list[dict[str, Any]]:
    """
    Recherche un livre par titre, auteur ou ISBN.

    Google Books en premier (avec retry sur 429), puis Open Library en repli quand Google
    ne trouve rien. Si Google est en ERREUR (429, panne) : repli sur Open Library, sauf si
    fallback_on_error=False, auquel cas l'erreur est propagée (utile pour un import en masse :
    une limitation de Google ne doit pas être prise pour « livre introuvable »).
    Les résultats sont gardés en cache quelques minutes.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    cache_key = (cleaned_query.lower(), max_results, lang)
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    isbn = normalize_isbn(cleaned_query)

    results: list[dict[str, Any]] | None = None
    try:
        if isbn:
            # Recherche exacte, sans restriction de langue, avec les deux formes de l'ISBN
            for variant in isbn_variants(isbn):
                results = _search_google_books(f"isbn:{variant}", max_results, None)
                if results:
                    break
        else:
            results = _search_google_books(cleaned_query, max_results, lang)
            if not results:
                results = _search_google_books(cleaned_query, max_results, None)
    except requests.RequestException:
        if not fallback_on_error:
            raise
        results = None  # Google en échec

    if not results:  # None (échec de Google) ou [] (rien trouvé) : on tente Open Library
        if isbn:
            results = []
            for variant in isbn_variants(isbn):
                results = _search_open_library(f"isbn:{variant}", max_results)
                if results:
                    break
        else:
            results = _search_open_library(cleaned_query, max_results)

    if results:
        _cache[cache_key] = (time.time(), results)
    return results


def get_book(query: str, lang: str = "fr") -> dict[str, Any] | None:
    """Retourne le premier résultat trouvé pour une requête donnée, ou None."""
    results = search_book(query=query, max_results=1, lang=lang)
    return results[0] if results else None