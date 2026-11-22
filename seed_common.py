"""Outils communs aux scripts d'import en masse (seed_cd.py, seed_livres.py)."""
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent
MAX_CONSECUTIVE_ERRORS = 5  # on arrête si l'API répond en erreur 5 fois de suite


def prepare_environment() -> None:
    """Se place dans le dossier du projet (la base dvds.db y est référencée en relatif) et charge .env."""
    os.chdir(PROJECT_DIR)
    env_path = PROJECT_DIR / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


def read_list(filepath: str) -> list[str]:
    """Lit une liste : une ligne par élément, '#' pour commenter, doublons du fichier supprimés."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Le fichier '{filepath}' est introuvable.")
    seen: set[str] = set()
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        cleaned = raw.replace("\xa0", " ").strip()
        if cleaned and not cleaned.startswith("#") and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            lines.append(cleaned)
    return lines


def tokens(text: str | None) -> frozenset[str]:
    """Mots en minuscules, sans accents ni ponctuation : 'Hugo, Victor' == 'Victor Hugo'."""
    if not text:
        return frozenset()
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return frozenset(re.findall(r"[a-z0-9]+", ascii_text.lower()))


def similar(a: str | None, b: str | None) -> bool:
    """Vrai si les mots de l'un sont tous contenus dans l'autre ('Alien' ~ 'Alien (Remastered)')."""
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb and (ta <= tb or tb <= ta))


def identity_key(title: str | None, creator: str | None) -> tuple[frozenset[str], frozenset[str]]:
    return tokens(title), tokens(creator)


def pick_best(results: list[dict], title: str, creator: str, creator_key: str) -> tuple[dict, bool]:
    """Choisit le résultat le plus proche de la ligne. Retourne (résultat, sûr ?).

    'Sûr' = le titre ET le créateur (artiste/auteur, s'il est indiqué) correspondent.
    """
    best, best_score, best_sure = results[0], -1, False
    for result in results:
        title_ok = similar(title, result.get("title"))
        creator_ok = similar(creator, result.get(creator_key)) if creator else True
        exact = tokens(title) == tokens(result.get("title"))
        score = 2 * title_ok + creator_ok + exact
        if score > best_score:
            best, best_score, best_sure = result, score, title_ok and creator_ok
    return best, best_sure


def with_retry(func, *args, retries: int = 3, wait: int = 30, **kwargs):
    """Appelle func ; sur une erreur 429 (trop de requêtes), patiente puis réessaie."""
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 429 and attempt < retries:
                retry_after = response.headers.get("Retry-After", "")
                delay = int(retry_after) if retry_after.isdigit() else wait
                print(f"    Limite atteinte (429) : pause de {delay}s puis nouvel essai...")
                time.sleep(delay)
                continue
            raise


def write_report(path: str, entries: list[str]) -> None:
    """Écrit les lignes à corriger (réutilisables telles quelles dans la liste) ; supprime l'ancien rapport si vide."""
    target = Path(path)
    if entries:
        header = "# Lignes à corriger puis à remettre dans ta liste (le texte après '#' est une indication).\n"
        target.write_text(header + "\n".join(entries) + "\n", encoding="utf-8")
    elif target.exists():
        target.unlink()