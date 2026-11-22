"""Import en masse de livres depuis une liste « Titre - Auteur » (une ligne par livre).

Usage :
    python seed_livres.py                  # lit livres_list.txt
    python seed_livres.py ma_liste.txt
    python seed_livres.py --dry-run
    python seed_livres.py --accepter-incertains

Un titre seul (sans ' - Auteur') fonctionne aussi, mais est moins précis.
Les lignes introuvables ou incertaines sont écrites dans livres_a_corriger.txt.
"""
import argparse
import os
import sys
import time

import requests

from seed_common import (
    MAX_CONSECUTIVE_ERRORS, identity_key, pick_best, prepare_environment,
    read_list, write_report,
)


def split_title_author(line: str) -> tuple[str, str]:
    """'Le Petit Prince - Antoine de Saint-Exupéry' -> (titre, auteur). Coupe au DERNIER ' - '
    (un titre peut contenir ' - ', un nom d'auteur presque jamais)."""
    if " - " in line:
        title, author = line.rsplit(" - ", 1)
        return title.strip(), author.strip()
    return line.strip(), ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe des livres depuis une liste 'Titre - Auteur'.")
    parser.add_argument("fichier", nargs="?", default="livres_list.txt")
    parser.add_argument("--dry-run", action="store_true", help="n'écrit rien en base")
    parser.add_argument("--accepter-incertains", action="store_true",
                        help="ajoute aussi les résultats dont le titre/l'auteur ne correspondent pas exactement")
    args = parser.parse_args()

    prepare_environment()
    from database import Database
    from services.books_service import search_book

    pause = 0.5 if os.getenv("GOOGLE_BOOKS_API_KEY") else 2.0
    if pause > 1:
        print("Astuce : sans GOOGLE_BOOKS_API_KEY dans le .env, Google bloque vite (erreur 429) ;\n"
              "le script ralentit et se rabat sur Open Library (sans résumés).\n")

    try:
        lines = read_list(args.fichier)
    except FileNotFoundError as exc:
        print(f"Erreur : {exc}")
        return 1

    db = Database()
    known_isbns = {b["isbn"] for b in db.get_all_books() if b.get("isbn")}
    known_keys = {identity_key(b["title"], b["author"]) for b in db.get_all_books()}

    print(f"Début de l'importation de {len(lines)} livres{' (simulation)' if args.dry_run else ''}...")
    added, skipped, to_fix = 0, 0, []
    consecutive_errors = 0

    for index, line in enumerate(lines, 1):
        title, author = split_title_author(line)
        print(f"[{index}/{len(lines)}] {line}")

        try:
            results = search_book(query=f"{title} {author}".strip(), max_results=5, lang="fr")
            consecutive_errors = 0
        except requests.RequestException as exc:
            consecutive_errors += 1
            print(f"  -> [ERREUR] {exc}")
            to_fix.append(f"{line}  # erreur réseau, à réessayer")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print("Trop d'erreurs d'affilée : arrêt. Relance plus tard (les livres déjà ajoutés seront ignorés).")
                break
            time.sleep(pause)
            continue
        time.sleep(pause)

        if not results:
            print("  -> [INTROUVABLE]")
            to_fix.append(f"{line}  # aucun résultat")
            continue

        best, sure = pick_best(results, title, author, "author")
        if not sure and not args.accepter_incertains:
            print(f"  -> [INCERTAIN] proposition : {best['title']} - {best['author']}")
            to_fix.append(f"{line}  # à vérifier, proposition : {best['title']} - {best['author']}")
            continue

        if (best.get("isbn") and best["isbn"] in known_isbns) or identity_key(best["title"], best["author"]) in known_keys:
            print(f"  -> [DÉJÀ PRÉSENT] {best['title']} - {best['author']}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  -> [OK, simulation] {best['title']} - {best['author']} ({best['year']})")
            continue

        db.add_book({
            "google_id": best.get("google_id"), "title": best["title"], "author": best["author"],
            "year": best.get("year"), "summary": best.get("summary"), "cover_url": best.get("cover_url"),
            "isbn": best.get("isbn"), "page_count": best.get("page_count"),
        })
        if best.get("isbn"):
            known_isbns.add(best["isbn"])
        known_keys.add(identity_key(best["title"], best["author"]))
        added += 1
        print(f"  -> [SUCCÈS] {best['title']} - {best['author']} ({best['year']})")

    write_report("livres_a_corriger.txt", to_fix)
    print(f"\nTerminé : {added} ajoutés, {skipped} déjà présents, {len(to_fix)} à corriger"
          f"{' (voir livres_a_corriger.txt)' if to_fix else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
