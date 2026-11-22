import os
import re
from typing import Any
import requests

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
DEFAULT_TIMEOUT = 10


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


def search_book(query: str, max_results: int = 1, lang: str = "fr") -> list[dict[str, Any]]:
    """
    Recherche un livre sur Google Books par titre, auteur ou ISBN.

    Retourne une liste de dictionnaires normalisés pour la Médiathèque.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    # Si l'utilisateur saisit un ISBN (10 ou 13 chiffres avec éventuels tirets/espaces)
    normalized_isbn = re.sub(r"[-\s]", "", cleaned_query)
    if re.fullmatch(r"(?:\d{10}|\d{13}|\d{9}[\dXx])", normalized_isbn):
        q_param = f"isbn:{normalized_isbn}"
    else:
        q_param = cleaned_query

    params: dict[str, Any] = {
        "q": q_param,
        "maxResults": max(1, min(max_results, 40)),
        "printType": "books",
        "langRestrict": lang,
    }

    api_key = os.getenv("GOOGLE_BOOKS_API_KEY")
    if api_key:
        params["key"] = api_key

    response = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    payload = response.json()

    items = payload.get("items") or []
    results: list[dict[str, Any]] = []

    for item in items:
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


def get_book(query: str, lang: str = "fr") -> dict[str, Any] | None:
    """Retourne le premier résultat trouvé pour une requête donnée, ou None."""
    results = search_book(query=query, max_results=1, lang=lang)
    return results[0] if results else None