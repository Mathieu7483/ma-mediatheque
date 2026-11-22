import os
from pathlib import Path
from flask import Flask, flash, redirect, render_template, request, url_for
import requests

from database import Database
from services.books_service import search_book
from services.discogs_service import get_release_details, is_authenticated, search_albums
from services.tmdb_service import get_details, search_candidates


def _load_dotenv_file() -> None:
    """Charge les variables de .env (à côté de app.py) sans dépendance externe."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        print(f"[.env] introuvable : {env_path}")
        return
    # utf-8-sig : ignore le BOM que Notepad/Windows ajoute et qui casse la 1re clé
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # On n'écrase pas une vraie variable, mais on remplace une variable vide
        if key and value and not os.environ.get(key):
            os.environ[key] = value
    print(f"[.env] chargé depuis {env_path} - DISCOGS_TOKEN "
          f"{'présent' if os.getenv('DISCOGS_TOKEN') else 'ABSENT'}")


_load_dotenv_file()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-mediatheque")
db = Database()

MEDIA_TYPES = {"dvd": "DVD", "cd": "CD", "livre": "Livre"}
# Page de collection vers laquelle on revient après un ajout
COLLECTION_ENDPOINT = {"dvd": "index", "cd": "cd_list", "livre": "books_list"}


# ---------------------------------------------------------------------------
# Accueil et pages de collection : elles n'affichent que ce que tu possèdes
# ---------------------------------------------------------------------------
@app.route("/")
def hub():
    return render_template(
        "index.html",
        stats=db.get_stats(),
        recent_items=db.get_recent_items(limit=6),
        error=None,
    )


# Endpoint nommé 'index' sur /dvd pour préserver url_for('index') dans les templates
@app.route("/dvd", endpoint="index")
def dvd_catalogue():
    search = request.args.get("q", "").strip()
    selected_genre = request.args.get("genre", "").strip()

    return render_template(
        "dvd.html",
        dvds=db.get_all_dvds(search_query=search, genre_filter=selected_genre),
        search=search,
        selected_genre=selected_genre,
        all_genres=db.get_all_genres(),
    )


@app.route("/cd")
def cd_list():
    collection_query = request.args.get("q", "").strip()
    return render_template(
        "cd.html",
        albums=db.get_all_albums(search_query=collection_query),
        collection_query=collection_query,
        error=None,
    )


@app.route("/livres")
def books_list():
    collection_query = request.args.get("q", "").strip()
    return render_template(
        "livres.html",
        books=db.get_all_books(search_query=collection_query),
        collection_query=collection_query,
        error=None,
    )


@app.route("/delete/<int:dvd_id>", methods=["POST"])
def delete_dvd(dvd_id):
    db.delete_dvd(dvd_id)
    flash("Le DVD a été retiré de la DVDthèque.", "info")
    return redirect(url_for("index"))


@app.route("/cd/delete/<int:album_id>", methods=["POST"])
def delete_cd(album_id):
    db.delete_album(album_id)
    flash("L'album a été retiré de la CDthèque.", "info")
    return redirect(url_for("cd_list"))


@app.route("/livres/delete/<int:book_id>", methods=["POST"])
def delete_book(book_id):
    db.delete_book(book_id)
    flash("Le livre a été retiré de la Bibliothèque.", "info")
    return redirect(url_for("books_list"))


# ---------------------------------------------------------------------------
# Page « Ajouter » unique : recherche, choix du résultat, enregistrement
# ---------------------------------------------------------------------------
def _search_media(media_type: str, query: str, artist: str) -> tuple[list, str | None]:
    """Lance la recherche adaptée au type de média. Retourne (résultats, message d'erreur)."""
    try:
        if media_type == "dvd":
            results = search_candidates(query, max_results=6)
            return results, (None if results else f"Aucun film ou série trouvé pour « {query} ».")

        if media_type == "cd":
            results = search_albums(query=query, artist=artist, max_results=6)
            if not results:
                return results, "Aucun album CD trouvé sur Discogs pour cette recherche."
            if not is_authenticated():
                return results, (
                    "DISCOGS_TOKEN absent : Discogs ne fournit alors ni pochettes ni "
                    "tracklists. Ajoute ton token dans le fichier .env."
                )
            return results, None

        results = search_book(query=query, max_results=6, lang="fr")
        return results, (None if results else f"Aucun livre trouvé pour « {query} ».")

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "inconnu"
        return [], f"Erreur HTTP ({status}) pendant la recherche. Vérifie ta clé/ton token ou réessaie."
    except requests.RequestException as exc:
        return [], f"Erreur réseau pendant la recherche : {exc}"


def _save_dvd(form) -> tuple[str | None, str | None]:
    kind = form.get("tmdb_kind", "").strip()
    tmdb_id = form.get("tmdb_id", "").strip()
    if kind not in ("movie", "tv") or not tmdb_id.isdigit():
        return None, "Film invalide : relance la recherche."
    try:
        dvd_data = get_details(kind, int(tmdb_id))
    except requests.RequestException as exc:
        return None, f"Erreur réseau lors de l'appel à TMDB : {exc}"
    if not dvd_data:
        return None, "Impossible de récupérer les détails de ce film."
    db.add_dvd(dvd_data)
    return f"« {dvd_data['title']} » ajouté à la DVDthèque.", None


def _save_album(form) -> tuple[str | None, str | None]:
    title = form.get("title", "").strip()
    if not title:
        return None, "Le titre de l'album est requis."
    artist = form.get("artist", "Artiste inconnu").strip()
    discogs_id_raw = form.get("discogs_id", "").strip()

    album_data = {
        "discogs_id": int(discogs_id_raw) if discogs_id_raw.isdigit() else None,
        "title": title,
        "artist": artist,
        "year": form.get("year", "").strip(),
        "genres": form.get("genres", "").strip(),
        "styles": form.get("styles", "").strip(),
        "barcode": form.get("barcode", "").strip() or None,
        "cover_url": form.get("cover_url", "").strip() or None,
        "tracklist": "",
    }

    # La recherche Discogs ne renvoie pas la tracklist : on la récupère ici,
    # une seule fois, pour l'album choisi (évite 6 appels par recherche).
    note = ""
    if album_data["discogs_id"]:
        try:
            details = get_release_details(album_data["discogs_id"])
            if details:
                album_data["cover_url"] = details["cover_url"] or album_data["cover_url"]
                album_data["tracklist"] = details["tracklist_text"]
        except requests.RequestException:
            note = " (pochette/tracklist indisponibles pour l'instant)"

    db.add_album(album_data)
    return f"« {title} » ({artist}) ajouté à la CDthèque{note}.", None


def _save_book(form) -> tuple[str | None, str | None]:
    title = form.get("title", "").strip()
    if not title:
        return None, "Le titre du livre est requis."
    author = form.get("author", "Auteur inconnu").strip()
    pages_raw = form.get("page_count", "").strip()

    db.add_book({
        "google_id": form.get("google_id", "").strip() or None,
        "title": title,
        "author": author,
        "year": form.get("year", "").strip(),
        "summary": form.get("summary", "").strip() or "Aucun résumé disponible.",
        "cover_url": form.get("cover_url", "").strip() or None,
        "isbn": form.get("isbn", "").strip() or None,
        "page_count": int(pages_raw) if pages_raw.isdigit() else None,
    })
    return f"« {title} » ({author}) ajouté à la Bibliothèque.", None


_SAVERS = {"dvd": _save_dvd, "cd": _save_album, "livre": _save_book}


@app.route("/ajouter", methods=["GET", "POST"])
def add_page():
    media_type = (request.values.get("type") or "dvd").strip().lower()
    if media_type not in MEDIA_TYPES:
        media_type = "dvd"

    if request.method == "POST":
        message, error = _SAVERS[media_type](request.form)
        if message:
            flash(message, "success")
            return redirect(url_for(COLLECTION_ENDPOINT[media_type]))
        return render_template(
            "add.html", media_type=media_type, media_types=MEDIA_TYPES,
            query="", artist="", results=[], error=error,
        )

    query = request.args.get("query", "").strip()
    artist = request.args.get("artist", "").strip() if media_type == "cd" else ""
    results, error = [], None
    if query or artist:
        results, error = _search_media(media_type, query, artist)

    return render_template(
        "add.html", media_type=media_type, media_types=MEDIA_TYPES,
        query=query, artist=artist, results=results, error=error,
    )


# Anciennes adresses : on renvoie vers la page unique pour ne rien casser
@app.route("/add", endpoint="add_dvd", methods=["GET", "POST"])
def add_dvd_redirect():
    return redirect(url_for("add_page", type="dvd"))


@app.route("/ajouter-media", endpoint="add_media", methods=["GET", "POST"])
def add_media_redirect():
    media_type = (request.values.get("media_type") or "dvd").strip().lower()
    return redirect(url_for("add_page", type=media_type, query=request.values.get("query", "")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
