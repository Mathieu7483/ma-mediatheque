import os
from pathlib import Path
from flask import Flask, flash, redirect, render_template, request, url_for
import requests

from database import Database
from services.books_service import search_book
from services.discogs_service import get_release_details, search_albums
from services.tmdb_service import search_and_get_movie_details


def _load_dotenv_file() -> None:
    """Charge les variables de .env si présent sans dépendance externe obligatoire."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_file()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-mediatheque")
db = Database()


@app.route("/")
def hub():
    stats = db.get_stats()
    recent_items = db.get_recent_items(limit=6)
    return render_template(
        "index.html",
        stats=stats,
        recent_items=recent_items,
        error=None,
    )


@app.route("/ajouter-media", methods=["POST"])
def add_media():
    media_type = request.form.get("media_type", "dvd").strip().lower()
    query = request.form.get("query", "").strip()

    if not query:
        return render_template(
            "index.html",
            stats=db.get_stats(),
            recent_items=db.get_recent_items(limit=6),
            error="Saisis un terme de recherche pour ajouter un média.",
        )

    if media_type == "dvd":
        dvd_data = search_and_get_movie_details(query)
        if dvd_data:
            db.add_dvd(dvd_data)
            return redirect(url_for("index"))
        return render_template(
            "index.html",
            stats=db.get_stats(),
            recent_items=db.get_recent_items(limit=6),
            error=f"Aucun film trouvé pour '{query}'.",
        )

    if media_type == "cd":
        try:
            search_results = search_albums(query=query, max_results=6)
            error = None if search_results else f"Aucun CD trouvé pour '{query}'."
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "inconnu"
            search_results = []
            error = f"Erreur HTTP Discogs ({status}). Vérifie ton token ou ta requête."
        except requests.RequestException as exc:
            search_results = []
            error = f"Erreur réseau lors de l'appel à Discogs : {exc}"

        albums = db.get_all_albums()
        return render_template(
            "cd.html",
            albums=albums,
            search_results=search_results,
            query_text=query,
            artist_text="",
            collection_query="",
            error=error,
        )

    if media_type == "livre":
        try:
            search_results = search_book(query=query, max_results=6, lang="fr")
            error = None if search_results else f"Aucun livre trouvé pour '{query}'."
        except requests.RequestException as exc:
            search_results = []
            error = f"Erreur réseau lors de l'appel à Google Books : {exc}"

        books = db.get_all_books()
        return render_template(
            "livres.html",
            books=books,
            search_results=search_results,
            query_text=query,
            collection_query="",
            error=error,
        )

    return redirect(url_for("hub"))


# Endpoint nommé 'index' sur /dvd pour préserver url_for('index') dans dvd.html et add.html
@app.route("/dvd", endpoint="index")
def dvd_catalogue():
    search = request.args.get("q", "").strip()
    selected_genre = request.args.get("genre", "").strip()

    dvds = db.get_all_dvds(search_query=search, genre_filter=selected_genre)
    all_genres = db.get_all_genres()

    return render_template(
        "dvd.html",
        dvds=dvds,
        search=search,
        selected_genre=selected_genre,
        all_genres=all_genres,
    )


@app.route("/add", methods=["GET", "POST"])
def add_dvd():
    error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if title:
            dvd_data = search_and_get_movie_details(title)
            if dvd_data:
                db.add_dvd(dvd_data)
                return redirect(url_for("index"))
            error = f"Aucun film trouvé pour '{title}'."
    return render_template("add.html", error=error)


@app.route("/delete/<int:dvd_id>", methods=["POST"])
def delete_dvd(dvd_id):
    db.delete_dvd(dvd_id)
    return redirect(url_for("index"))


@app.route("/cd", methods=["GET", "POST"])
def cd_list():
    search_results = []
    query_text = ""
    artist_text = ""
    error = None
    collection_query = request.args.get("q", "").strip()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "search":
            query_text = request.form.get("query", "").strip()
            artist_text = request.form.get("artist", "").strip()

            if not query_text and not artist_text:
                error = "Saisis un album, un code-barres ou un groupe/artiste."
            else:
                try:
                    search_results = search_albums(
                        query=query_text,
                        artist=artist_text,
                        max_results=6,
                    )
                    if not search_results:
                        error = "Aucun album CD trouvé sur Discogs pour cette recherche."
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else "inconnu"
                    error = f"Erreur HTTP Discogs ({status}). Vérifie ton token ou ta requête."
                except requests.RequestException as exc:
                    error = f"Erreur réseau lors de l'appel à Discogs : {exc}"

        elif action == "save":
            title = request.form.get("title", "").strip()
            artist = request.form.get("artist", "Artiste inconnu").strip()
            discogs_id_raw = request.form.get("discogs_id", "").strip()

            if title:
                album_data = {
                    "discogs_id": int(discogs_id_raw) if discogs_id_raw.isdigit() else None,
                    "title": title,
                    "artist": artist,
                    "year": request.form.get("year", "").strip(),
                    "genres": request.form.get("genres", "").strip(),
                    "styles": request.form.get("styles", "").strip(),
                    "barcode": request.form.get("barcode", "").strip() or None,
                    "cover_url": request.form.get("cover_url", "").strip() or None,
                }
                db.add_album(album_data)
                flash(f"« {title} » ({artist}) ajouté à la CDthèque.", "success")
                return redirect(url_for("cd_list"))
            error = "Le titre de l'album est requis."

    albums = db.get_all_albums(search_query=collection_query)
    return render_template(
        "cd.html",
        albums=albums,
        search_results=search_results,
        query_text=query_text,
        artist_text=artist_text,
        collection_query=collection_query,
        error=error,
    )


@app.route("/cd/delete/<int:album_id>", methods=["POST"])
def delete_cd(album_id):
    db.delete_album(album_id)
    flash("L'album a été retiré de la CDthèque.", "info")
    return redirect(url_for("cd_list"))


@app.route("/livres", methods=["GET", "POST"])
def books_list():
    search_results = []
    query_text = ""
    error = None
    collection_query = request.args.get("q", "").strip()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "search":
            query_text = request.form.get("query", "").strip()
            if not query_text:
                error = "Saisis un titre, un auteur ou un ISBN pour rechercher un livre."
            else:
                try:
                    search_results = search_book(query=query_text, max_results=6, lang="fr")
                    if not search_results:
                        error = f"Aucun livre trouvé pour « {query_text} »."
                except requests.RequestException as exc:
                    error = f"Erreur réseau lors de l'appel à Google Books : {exc}"

        elif action == "save":
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "Auteur inconnu").strip()
            year_raw = request.form.get("year", "").strip()
            pages_raw = request.form.get("page_count", "").strip()

            if title:
                book_data = {
                    "google_id": request.form.get("google_id", "").strip() or None,
                    "title": title,
                    "author": author,
                    "year": year_raw,
                    "summary": request.form.get("summary", "").strip() or "Aucun résumé disponible.",
                    "cover_url": request.form.get("cover_url", "").strip() or None,
                    "isbn": request.form.get("isbn", "").strip() or None,
                    "page_count": int(pages_raw) if pages_raw.isdigit() else None,
                }
                db.add_book(book_data)
                flash(f"« {title} » ({author}) ajouté à la Bibliothèque.", "success")
                return redirect(url_for("books_list"))
            error = "Le titre du livre est requis."

    books = db.get_all_books(search_query=collection_query)
    return render_template(
        "livres.html",
        books=books,
        search_results=search_results,
        query_text=query_text,
        collection_query=collection_query,
        error=error,
    )


@app.route("/livres/delete/<int:book_id>", methods=["POST"])
def delete_book(book_id):
    db.delete_book(book_id)
    flash("Le livre a été retiré de la Bibliothèque.", "info")
    return redirect(url_for("books_list"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)