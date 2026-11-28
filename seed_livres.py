"""Import en masse de livres depuis une liste (une ligne par livre).

Formats de ligne acceptés :
    Titre - Auteur
    Titre - Auteur - ISBN       (ISBN facultatif, 10 ou 13 chiffres : recherche exacte, la plus fiable)
    Titre<TAB>Auteur            (tabulation, comme dans un copier-coller depuis un tableur)
    Titre                       (sans auteur : moins précis, le titre doit alors correspondre exactement)

Usage :
    python seed_livres.py                  # lit livres_list.txt
    python seed_livres.py ma_liste.txt
    python seed_livres.py --dry-run        # simulation : n'écrit rien en base
    python seed_livres.py --repli-liste    # si la recherche échoue, ajoute le livre tel qu'écrit dans la liste
    python seed_livres.py --sans-api       # aucune recherche en ligne : ajoute chaque ligne telle quelle
    python seed_livres.py --accepter-incertains

Un livre ajouté « tel quel » n'a ni couverture ni résumé. Sans --repli-liste, les lignes
introuvables ou incertaines sont écrites dans livres_a_corriger.txt.
"""
import argparse
import os
import re
import sys
import time

import requests

from seed_common import (
    MAX_CONSECUTIVE_ERRORS, identity_key, pick_best, prepare_environment,
    read_list, similar, tokens, write_report,
)

# « (à confirmer) », « (titre à vérifier) »... en fin de ligne : des notes personnelles, pas des données
NOTE_PATTERN = re.compile(r"\s*\([^)]*(?:confirmer|v[ée]rifier)[^)]*\)\s*$", re.IGNORECASE)
PLACEHOLDER_AUTHORS = ("auteur non lisible", "auteur collectif", "anonyme", "inconnu")


ISBN_LABEL = re.compile(r"\s*(?:[-\t]\s*)?\bISBN(?:-1[03])?\s*[:=]?\s*(?P<codes>[\dXx][\dXx\s,;/-]*)\s*$", re.IGNORECASE)
ISBN_PLAIN = re.compile(r"(?:\s*[-\t]\s*|\s+)(?P<codes>(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx])\s*$")


def split_isbn(line: str) -> tuple[str, list[str]]:
    """Détache les ISBN placés en fin de ligne. Formats acceptés :
        Glacé - Bernard Minier - 9782845635357
        Glacé - Bernard Minier - ISBN : 9782845635357, 2845635354
    Retourne (ligne sans ISBN, liste d'ISBN valides : 10 ou 13 chiffres)."""
    match = ISBN_LABEL.search(line) or ISBN_PLAIN.search(line)
    if not match:
        return line, []
    text = match.group("codes")
    codes = []
    for m in re.finditer(r"97[89](?:[-\s]?\d){10}", text):          # ISBN-13 d'abord
        codes.append(re.sub(r"[-\s]", "", m.group(0)))
    text = re.sub(r"97[89](?:[-\s]?\d){10}", " ", text)
    for chunk in re.split(r"[,;/\s]+", text):                        # puis les ISBN-10
        digits = chunk.replace("-", "").upper()
        if len(digits) == 10 and re.fullmatch(r"\d{9}[\dX]", digits) and digits not in codes:
            codes.append(digits)
    if not codes:
        return line, []
    return line[:match.start()].strip(), codes


def split_title_author(line: str) -> tuple[str, str]:
    """Sépare titre et auteur : tabulation d'abord, sinon le DERNIER ' - '
    (un titre peut contenir ' - ', un nom d'auteur presque jamais)."""
    line = NOTE_PATTERN.sub("", line).strip()
    if "\t" in line:
        title, author = line.split("\t", 1)
    elif " - " in line:
        title, author = line.rsplit(" - ", 1)
    else:
        title, author = line, ""

    title = NOTE_PATTERN.sub("", title).strip()
    author = NOTE_PATTERN.sub("", author).strip().rstrip("?").strip()
    if any(author.lower().startswith(p) for p in PLACEHOLDER_AUTHORS):
        author = ""
    return title, author


def search_with_patience(query: str) -> list[dict]:
    """Cherche le livre. Une limitation de Google (429) n'est PAS un « introuvable » :
    on patiente et on réessaie, et Open Library n'est le dernier recours qu'au 3e essai."""
    from services.books_service import search_book

    for attempt in (1, 2, 3):
        try:
            try:
                return search_book(query=query, max_results=5, lang="fr", fallback_on_error=(attempt == 3))
            except TypeError:
                # books_service.py ancien (sans fallback_on_error) : appel simple
                return search_book(query=query, max_results=5, lang="fr")
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (400, 401, 403) and attempt < 3:
                # Erreur de configuration, pas de limitation : attendre ne sert à rien
                return search_book(query=query, max_results=5, lang="fr", fallback_on_error=True)
            if attempt == 3:
                raise
            wait = 20 * attempt
            print(f"    Google limite les requêtes ({type(exc).__name__}) : pause de {wait}s puis nouvel essai...")
            time.sleep(wait)
    return []


def already_in_collection(title: str, author: str, books: list[dict]) -> bool:
    """Doublon souple : casse, accents et ponctuation ignorés, mais titre COMPLET identique
    (« Net Force » et « Net Force 2 : Programmes fantômes » sont deux livres différents)."""
    for book in books:
        if tokens(title) == tokens(book.get("title")) and (not author or similar(author, book.get("author"))):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe des livres depuis une liste 'Titre - Auteur'.")
    parser.add_argument("fichier", nargs="?", default="livres_list.txt")
    parser.add_argument("--dry-run", action="store_true", help="n'écrit rien en base")
    parser.add_argument("--repli-liste", action="store_true",
                        help="si la recherche échoue (erreur, introuvable, incertain), ajoute le livre tel qu'écrit dans la liste")
    parser.add_argument("--sans-api", action="store_true",
                        help="aucune recherche en ligne : ajoute chaque ligne telle quelle (sans couverture ni résumé)")
    parser.add_argument("--accepter-incertains", action="store_true",
                        help="ajoute aussi les résultats dont le titre/l'auteur ne correspondent pas exactement")
    args = parser.parse_args()

    prepare_environment()
    from database import Database

    pause = 0.5 if os.getenv("GOOGLE_BOOKS_API_KEY") else 2.0
    if pause > 1 and not args.sans_api:
        print("Astuce : sans GOOGLE_BOOKS_API_KEY dans le .env, Google bloque vite (erreur 429) ;\n"
              "le script ralentit et réessaie, mais l'import sera long.\n")

    try:
        lines = read_list(args.fichier)
    except FileNotFoundError as exc:
        print(f"Erreur : {exc}")
        return 1

    db = Database()
    books = db.get_all_books()
    known_isbns = {b["isbn"] for b in books if b.get("isbn")}
    known_keys = {identity_key(b["title"], b["author"]) for b in books}

    fallback_allowed = args.repli_liste or args.sans_api
    api_down = args.sans_api  # vrai : on n'appelle plus aucune API
    mode = " (simulation)" if args.dry_run else ""
    print(f"Début de l'importation de {len(lines)} livres{mode}...")
    added, from_list, skipped, to_fix = 0, 0, 0, []
    consecutive_errors = 0

    for index, line in enumerate(lines, 1):
        line, isbns = split_isbn(NOTE_PATTERN.sub("", line).strip())
        title, author = split_title_author(line)
        print(f"[{index}/{len(lines)}] {title}" + (f" - {author}" if author else "") + (f" [ISBN {', '.join(isbns)}]" if isbns else ""))
        clean_line = f"{title} - {author}" if author else title

        best = None
        reason = "recherche en ligne désactivée"
        if not api_down:
            try:
                results, by_isbn = [], False
                for code in isbns:
                    results = search_with_patience(code)
                    if results:
                        by_isbn = True
                        break
                if not results:
                    results = search_with_patience(f"{title} {author}".strip())
                consecutive_errors = 0
            except requests.RequestException as exc:
                consecutive_errors += 1
                reason = "erreur réseau, à réessayer"
                print(f"  -> [ERREUR] {exc}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    if not fallback_allowed:
                        to_fix.append(f"{clean_line}  # {reason}")
                        print("Trop d'erreurs d'affilée : arrêt. Relance plus tard "
                              "(les livres déjà ajoutés seront ignorés), ou utilise --repli-liste.")
                        break
                    api_down = True
                    print("  Trop d'erreurs d'affilée : la suite est traitée sans recherche en ligne.")
            else:
                if not results:
                    reason = "aucun résultat"
                else:
                    candidate, sure = pick_best(results, title, author, "author")
                    if by_isbn:
                        sure = True  # l'ISBN identifie le livre sans ambiguïté
                    elif not author:
                        # Sans auteur pour recouper, on exige le titre exact (évite un autre livre au titre voisin)
                        sure = tokens(title) == tokens(candidate["title"])
                    if sure or args.accepter_incertains:
                        best = candidate
                    else:
                        reason = f"à vérifier, proposition : {candidate['title']} - {candidate['author']}"
                        print(f"  -> [INCERTAIN] proposition : {candidate['title']} - {candidate['author']}")
            if not api_down:
                time.sleep(pause)

        if best is None:
            # Pas de résultat exploitable de la recherche
            if not fallback_allowed:
                if reason == "aucun résultat":
                    print("  -> [INTROUVABLE]")
                to_fix.append(f"{clean_line}  # {reason}")
                continue

            if already_in_collection(title, author, books):
                print(f"  -> [DÉJÀ PRÉSENT] {clean_line}")
                skipped += 1
                continue

            entry = {
                "google_id": None, "title": title, "author": author or "Auteur inconnu", "year": None,
                "summary": "Aucun résumé disponible.", "cover_url": None, "isbn": (isbns[0] if isbns else None), "page_count": None,
            }
            if not args.dry_run:
                db.add_book(entry)
            books.append(entry)
            from_list += 1
            print(f"  -> [{'OK, simulation' if args.dry_run else 'AJOUTÉ TEL QUEL'}] {clean_line}")
            continue

        # Résultat sûr de la recherche en ligne
        if (best.get("isbn") and best["isbn"] in known_isbns) or identity_key(best["title"], best["author"]) in known_keys \
                or already_in_collection(best["title"], best["author"], books):
            print(f"  -> [DÉJÀ PRÉSENT] {best['title']} - {best['author']}")
            skipped += 1
            continue

        entry = {
            "google_id": best.get("google_id"), "title": best["title"], "author": best["author"],
            "year": best.get("year"), "summary": best.get("summary"), "cover_url": best.get("cover_url"),
            "isbn": best.get("isbn"), "page_count": best.get("page_count"),
        }
        if args.dry_run:
            print(f"  -> [OK, simulation] {best['title']} - {best['author']} ({best['year']})")
            continue

        db.add_book(entry)
        books.append(entry)
        if best.get("isbn"):
            known_isbns.add(best["isbn"])
        known_keys.add(identity_key(best["title"], best["author"]))
        added += 1
        print(f"  -> [SUCCÈS] {best['title']} - {best['author']} ({best['year']})")

    write_report("livres_a_corriger.txt", to_fix)
    detail = f", dont {from_list} tels quels" if from_list else ""
    print(f"\nTerminé : {added + from_list} ajoutés{detail}, {skipped} déjà présents, {len(to_fix)} à corriger"
          f"{' (voir livres_a_corriger.txt)' if to_fix else ''}.")
    if args.dry_run:
        print("(simulation : rien n'a été écrit en base)")
    return 0


if __name__ == "__main__":
    sys.exit(main())