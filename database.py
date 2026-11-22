import sqlite3


class Database:
    def __init__(self, db_name="dvds.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            # 1. Table existante DVD (inchangée + migration douce conservée)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dvds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    year TEXT,
                    director TEXT,
                    actors TEXT,
                    genres TEXT,
                    synopsis TEXT,
                    poster_url TEXT,
                    created_at TIMESTAMP
                )
            """)
            cursor = conn.execute("PRAGMA table_info(dvds)")
            columns = [column[1] for column in cursor.fetchall()]
            if "genres" not in columns:
                conn.execute("ALTER TABLE dvds ADD COLUMN genres TEXT")
            if "created_at" not in columns:
                # Les anciens DVD restent à NULL (= "ajoutés avant le suivi des dates")
                conn.execute("ALTER TABLE dvds ADD COLUMN created_at TIMESTAMP")

            # 2. Nouvelle table Albums (CDthèque)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS albums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discogs_id INTEGER,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    year TEXT,
                    genres TEXT,
                    styles TEXT,
                    barcode TEXT,
                    cover_url TEXT,
                    tracklist TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            album_columns = [column[1] for column in conn.execute("PRAGMA table_info(albums)").fetchall()]
            if "tracklist" not in album_columns:
                conn.execute("ALTER TABLE albums ADD COLUMN tracklist TEXT")

            # 3. Nouvelle table Livres (Bibliothèque)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_id TEXT,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL,
                    year TEXT,
                    summary TEXT,
                    cover_url TEXT,
                    isbn TEXT,
                    page_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    # =========================================================================
    # DVDthèque (méthodes existantes préservées)
    # =========================================================================

    def add_dvd(self, dvd_data: dict):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO dvds (title, year, director, actors, genres, synopsis, poster_url, created_at)
                VALUES (:title, :year, :director, :actors, :genres, :synopsis, :poster_url, datetime('now'))
            """, dvd_data)
            conn.commit()

    def get_all_dvds(self, search_query="", genre_filter="") -> list:
        with self.get_connection() as conn:
            query = "SELECT * FROM dvds WHERE 1=1"
            params = []

            if search_query:
                query += " AND (title LIKE ? OR director LIKE ? OR actors LIKE ? OR genres LIKE ?)"
                p = f"%{search_query}%"
                params.extend([p, p, p, p])

            if genre_filter:
                query += " AND genres LIKE ?"
                params.append(f"%{genre_filter}%")

            query += " ORDER BY title ASC"
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_all_genres(self) -> list:
        """Récupère la liste de tous les genres uniques présents dans la base."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT genres FROM dvds WHERE genres IS NOT NULL AND genres != ''")
            raw_genres = cursor.fetchall()
            genres_set = set()
            for row in raw_genres:
                for g in row["genres"].split(","):
                    genres_set.add(g.strip())
            return sorted(list(genres_set))

    def delete_dvd(self, dvd_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM dvds WHERE id = ?", (dvd_id,))
            conn.commit()

    # =========================================================================
    # CDthèque (albums)
    # =========================================================================

    def add_album(self, album_data: dict):
        payload = {
            "discogs_id": album_data.get("discogs_id"),
            "title": album_data.get("title", ""),
            "artist": album_data.get("artist", "Artiste inconnu"),
            "year": str(album_data["year"]) if album_data.get("year") is not None else "",
            "genres": album_data.get("genres", ""),
            "styles": album_data.get("styles", ""),
            "barcode": album_data.get("barcode"),
            "cover_url": album_data.get("cover_url"),
            "tracklist": album_data.get("tracklist", ""),
        }
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO albums (discogs_id, title, artist, year, genres, styles, barcode, cover_url, tracklist)
                VALUES (:discogs_id, :title, :artist, :year, :genres, :styles, :barcode, :cover_url, :tracklist)
            """, payload)
            conn.commit()

    def get_all_albums(self, search_query="") -> list:
        with self.get_connection() as conn:
            query = "SELECT * FROM albums WHERE 1=1"
            params = []

            if search_query:
                query += " AND (title LIKE ? OR artist LIKE ? OR genres LIKE ? OR styles LIKE ?)"
                p = f"%{search_query}%"
                params.extend([p, p, p, p])

            query += " ORDER BY id DESC"
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def delete_album(self, album_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
            conn.commit()

    # =========================================================================
    # Bibliothèque (books)
    # =========================================================================

    def add_book(self, book_data: dict):
        payload = {
            "google_id": book_data.get("google_id"),
            "title": book_data.get("title", ""),
            "author": book_data.get("author", "Auteur inconnu"),
            "year": str(book_data["year"]) if book_data.get("year") is not None else "",
            "summary": book_data.get("summary", ""),
            "cover_url": book_data.get("cover_url"),
            "isbn": book_data.get("isbn"),
            "page_count": book_data.get("page_count"),
        }
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO books (google_id, title, author, year, summary, cover_url, isbn, page_count)
                VALUES (:google_id, :title, :author, :year, :summary, :cover_url, :isbn, :page_count)
            """, payload)
            conn.commit()

    def get_all_books(self, search_query="") -> list:
        with self.get_connection() as conn:
            query = "SELECT * FROM books WHERE 1=1"
            params = []

            if search_query:
                query += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"
                p = f"%{search_query}%"
                params.extend([p, p, p])

            query += " ORDER BY id DESC"
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def delete_book(self, book_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()

    # =========================================================================
    # Hub / Statistiques & Ajouts récents
    # =========================================================================

    def get_stats(self) -> dict:
        with self.get_connection() as conn:
            dvd_count = conn.execute("SELECT COUNT(*) FROM dvds").fetchone()[0]
            cd_count = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
            books_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

        return {
            "dvd": dvd_count,
            "cd": cd_count,
            "books": books_count,
            "total": dvd_count + cd_count + books_count,
        }

    def get_recent_items(self, limit: int = 6) -> list:
        """Retourne les derniers éléments ajoutés toutes collections confondues.

        Le tri se fait sur la date d'ajout (created_at), commune aux trois tables.
        Trier sur l'id ne marche pas : chaque table a sa propre numérotation, donc
        les DVD (ids élevés) masqueraient toujours les CD et les livres récents.
        Les anciens DVD sans date passent après tout ce qui est daté, classés par id.
        """
        items = []

        def sort_key(row) -> tuple:
            return (row["created_at"] or "", row["id"])

        with self.get_connection() as conn:
            for row in conn.execute(
                "SELECT id, title, year, director, poster_url, created_at FROM dvds "
                "ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?", (limit,)
            ):
                items.append({
                    "sort_key": sort_key(row),
                    "media_type": "dvd",
                    "media_label": "DVD",
                    "title": row["title"],
                    "creator": row["director"] or "Réalisateur inconnu",
                    "year": row["year"],
                    "cover_url": row["poster_url"],
                })

            for row in conn.execute(
                "SELECT id, title, year, artist, cover_url, created_at FROM albums "
                "ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?", (limit,)
            ):
                items.append({
                    "sort_key": sort_key(row),
                    "media_type": "cd",
                    "media_label": "CD",
                    "title": row["title"],
                    "creator": row["artist"] or "Artiste inconnu",
                    "year": row["year"],
                    "cover_url": row["cover_url"],
                })

            for row in conn.execute(
                "SELECT id, title, year, author, cover_url, created_at FROM books "
                "ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?", (limit,)
            ):
                items.append({
                    "sort_key": sort_key(row),
                    "media_type": "books",
                    "media_label": "Livre",
                    "title": row["title"],
                    "creator": row["author"] or "Auteur inconnu",
                    "year": row["year"],
                    "cover_url": row["cover_url"],
                })

        items.sort(key=lambda x: x["sort_key"], reverse=True)
        for item in items:
            del item["sort_key"]
        return items[:limit]