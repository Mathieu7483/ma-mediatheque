"""Import en masse de CD depuis une liste « Artiste - Album » (une ligne par album).

Usage :
    python seed_cd.py                      # lit cd_list.txt
    python seed_cd.py ma_liste.txt
    python seed_cd.py --dry-run            # montre ce qui serait ajouté, sans rien écrire
    python seed_cd.py --accepter-incertains

Chaque album : 1 recherche Discogs + 1 appel de détails (pochette HD et tracklist).
Les lignes introuvables ou incertaines sont écrites dans cd_a_corriger.txt.
"""
import argparse
import sys
import time

import requests

from seed_common import (
    MAX_CONSECUTIVE_ERRORS, identity_key, pick_best, prepare_environment,
    read_list, with_retry, write_report,
)

PAUSE_SECONDS = 1.2  # Discogs : 60 appels/min avec un token


def split_artist_album(line: str) -> tuple[str, str]:
    """'Daft Punk - Discovery' -> ('Daft Punk', 'Discovery'). Coupe au premier ' - '."""
    if " - " in line:
        artist, album = line.split(" - ", 1)
        return artist.strip(), album.strip()
    return "", line.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe des CD depuis une liste 'Artiste - Album'.")
    parser.add_argument("fichier", nargs="?", default="cd_list.txt")
    parser.add_argument("--dry-run", action="store_true", help="n'écrit rien en base")
    parser.add_argument("--accepter-incertains", action="store_true",
                        help="ajoute aussi les résultats dont l'artiste/le titre ne correspondent pas exactement")
    args = parser.parse_args()

    prepare_environment()
    from database import Database
    from services.discogs_service import get_release_details, is_authenticated, search_albums

    if not is_authenticated():
        print("DISCOGS_TOKEN absent du .env : sans lui, pas de pochettes ni de tracklists,\n"
              "et Discogs limite à 25 appels/min. Ajoute ton token puis relance.")
        return 1

    try:
        lines = read_list(args.fichier)
    except FileNotFoundError as exc:
        print(f"Erreur : {exc}")
        return 1

    db = Database()
    known_ids = {a["discogs_id"] for a in db.get_all_albums() if a.get("discogs_id")}
    known_keys = {identity_key(a["title"], a["artist"]) for a in db.get_all_albums()}

    print(f"Début de l'importation de {len(lines)} albums{' (simulation)' if args.dry_run else ''}...")
    added, skipped, to_fix = 0, 0, []
    consecutive_errors = 0

    for index, line in enumerate(lines, 1):
        artist, album = split_artist_album(line)
        print(f"[{index}/{len(lines)}] {line}")

        try:
            results = with_retry(search_albums, query=album, artist=artist, max_results=5)
            consecutive_errors = 0
        except requests.RequestException as exc:
            consecutive_errors += 1
            print(f"  -> [ERREUR] {exc}")
            to_fix.append(f"{line}  # erreur réseau, à réessayer")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print("Trop d'erreurs d'affilée : arrêt. Relance plus tard (les albums déjà ajoutés seront ignorés).")
                break
            time.sleep(PAUSE_SECONDS)
            continue
        time.sleep(PAUSE_SECONDS)

        if not results:
            print("  -> [INTROUVABLE]")
            to_fix.append(f"{line}  # aucun résultat sur Discogs")
            continue

        best, sure = pick_best(results, album, artist, "artist")
        if not sure and not args.accepter_incertains:
            print(f"  -> [INCERTAIN] proposition : {best['artist']} - {best['title']}")
            to_fix.append(f"{line}  # à vérifier, Discogs propose : {best['artist']} - {best['title']} (id {best['discogs_id']})")
            continue

        if best["discogs_id"] in known_ids or identity_key(best["title"], best["artist"]) in known_keys:
            print(f"  -> [DÉJÀ PRÉSENT] {best['artist']} - {best['title']}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  -> [OK, simulation] {best['artist']} - {best['title']} ({best['year']})")
            continue

        album_data = {
            "discogs_id": best["discogs_id"], "title": best["title"], "artist": best["artist"],
            "year": best["year"], "genres": best["genres"], "styles": best["styles"],
            "barcode": best.get("barcode"), "cover_url": best["cover_url"], "tracklist": "",
        }
        try:
            details = with_retry(get_release_details, best["discogs_id"])
            if details:
                album_data["cover_url"] = details["cover_url"] or album_data["cover_url"]
                album_data["tracklist"] = details["tracklist_text"]
                album_data["year"] = details["year"] or album_data["year"]
                album_data["genres"] = details["genres"] or album_data["genres"]
                album_data["styles"] = details["styles"] or album_data["styles"]
        except requests.RequestException:
            print("  (pochette/tracklist indisponibles pour cet album)")
        time.sleep(PAUSE_SECONDS)

        db.add_album(album_data)
        known_ids.add(album_data["discogs_id"])
        known_keys.add(identity_key(album_data["title"], album_data["artist"]))
        added += 1
        tracks = album_data["tracklist"].count("\n") + 1 if album_data["tracklist"] else 0
        print(f"  -> [SUCCÈS] {album_data['artist']} - {album_data['title']} ({album_data['year']}), {tracks} pistes")

    write_report("cd_a_corriger.txt", to_fix)
    print(f"\nTerminé : {added} ajoutés, {skipped} déjà présents, {len(to_fix)} à corriger"
          f"{' (voir cd_a_corriger.txt)' if to_fix else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())