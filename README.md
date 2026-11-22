<p align="center">
<img src="https://raw.githubusercontent.com/Mathieu7483/Ma-DVDth-que/main/Ma%20dvdth%C3%A8que.jpg" width="800px" alt="Ma médiathèque Banner">
</p>

# 📚 Ma médiathèque

> Une application web locale style *Prime Video* développée en Python et Flask pour gérer, cataloguer et explorer sa collection physique de **DVD, CD et livres**.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-black?style=for-the-badge&logo=flask&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-purple?style=for-the-badge&logo=bootstrap&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-informational?style=for-the-badge&logo=sqlite&logoColor=white)
![TMDb API](https://img.shields.io/badge/API-TMDb-green?style=for-the-badge&logo=themoviedb&logoColor=white)
![Discogs](https://img.shields.io/badge/API-Discogs-orange?style=for-the-badge)
![Google Books](https://img.shields.io/badge/API-Google%20Books-red?style=for-the-badge&logo=googlebooks&logoColor=white)

---

## ✨ Fonctionnalités

* **Trois collections** : 🎬 DVD (films et séries), 💿 CD et 📖 livres, chacune avec sa page qui affiche uniquement ce que vous possédez.
* **Page d'accueil** : accès rapide aux trois collections et liste des **ajouts récents**, tous types confondus, triés par date d'ajout.
* **Page « Ajouter » unique (`/ajouter`)** : un seul formulaire pour les trois types, avec recherche automatique :
  * **DVD** : affiches, synopsis, réalisateurs, acteurs et genres via **TMDb** ;
  * **CD** : pochettes et tracklists via **Discogs** ;
  * **Livres** : couvertures, auteurs, résumés via **Google Books**, avec **Open Library** en secours.
* **Gestion des séries TV** : prise en charge des intégrales en plus des longs-métrages.
* **Ajout manuel sur mesure** : pour les éditions spéciales, raretés ou objets non référencés.
* **Interface style streaming** : design sombre, épuré et responsive (Bootstrap).
* **Suppression en un clic** depuis la fiche d'une œuvre.
* **Import en masse par scripts** : une liste texte par collection, avec dédoublonnage, simulation (`--dry-run`) et rapport des lignes à corriger.

---

## 🛠️ Stack technique

* **Back-end** : Python, Flask (routes, templates Jinja2)
* **Base de données** : SQLite (`dvds.db`, via `database.py`), avec migrations automatiques et légères au démarrage
* **Services externes** : TMDb (DVD), Discogs (CD), Google Books + Open Library (livres)
* **Front-end** : HTML5, CSS3, Bootstrap 5

---

## 🚀 Installation & lancement local

### 1. Cloner le projet

```bash
git clone https://github.com/Mathieu7483/ma-mediatheque.git
cd ma-mediatheque
```

### 2. Environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurer les clés API (fichier `.env`)

Créez un fichier `.env` à la racine du projet (il ne doit **jamais** être publié : vérifiez qu'il figure dans `.gitignore`) :

```env
TMDB_API_KEY=votre_cle_tmdb
DISCOGS_TOKEN=votre_token_discogs
GOOGLE_BOOKS_API_KEY=votre_cle_google_books
```

| Variable | Pour quoi faire | Obligatoire ? |
|---|---|---|
| `TMDB_API_KEY` | Affiches et infos des DVD | Oui pour les DVD |
| `DISCOGS_TOKEN` | Pochettes et tracklists des CD (sans token, Discogs ne renvoie ni l'un ni l'autre) | Oui pour les CD |
| `GOOGLE_BOOKS_API_KEY` | Recherche de livres. Sans clé, Google limite vite les requêtes (erreur 429) | Fortement conseillée |

Où les obtenir : [TMDb](https://www.themoviedb.org/settings/api) · [Discogs](https://www.discogs.com/settings/developers) · [Google Cloud](https://console.cloud.google.com/) (activer l'API *Books*).

### 4. Lancer l'application

```bash
python3 app.py
```

Ouvrez ensuite `http://127.0.0.1:5000`.

---

## 📥 Remplir la médiathèque avec les scripts d'import

Chaque collection a sa liste texte (une ligne par œuvre, les lignes commençant par `#` sont ignorées) et son script. Les scripts peuvent être relancés sans risque : ce qui est déjà en base est ignoré.

| Collection | Script | Format d'une ligne |
|---|---|---|
| 🎬 DVD | `seed.py` | `Titre` |
| 💿 CD | `seed_cd.py` | `Artiste - Album` |
| 📖 Livres | `seed_livres.py` | `Titre - Auteur` (ou `Titre` seul, ou `Titre<TAB>Auteur`) |

`seed_common.py` contient le code partagé par les scripts (lecture du `.env`, normalisation des textes, choix du meilleur résultat, rapports).

### 🎬 DVD

```bash
python3 seed.py
```

### 💿 CD

```bash
python seed_cd.py --dry-run               # simulation : n'écrit rien en base
python seed_cd.py                         # import réel
python seed_cd.py ma_liste.txt            # autre fichier de liste
python seed_cd.py --accepter-incertains   # ajoute aussi les résultats dont le titre ou l'artiste ne correspondent pas exactement
```

### 📖 Livres

```bash
python seed_livres.py --dry-run                # simulation : n'écrit rien en base
python seed_livres.py                          # import réel (résultats sûrs uniquement)
python seed_livres.py --repli-liste --dry-run  # simulation avec repli sur la liste
python seed_livres.py --repli-liste            # si la recherche échoue, ajoute le livre tel qu'écrit dans la liste
python seed_livres.py --sans-api               # aucune recherche en ligne : ajoute chaque ligne telle quelle
python seed_livres.py ma_liste.txt             # autre fichier de liste
python seed_livres.py --accepter-incertains    # accepte aussi les résultats approximatifs
```

Comment lire les résultats :

* **`[SUCCÈS]`** : livre trouvé et ajouté avec couverture et résumé.
* **`[INCERTAIN]`** : la recherche propose un autre titre ou auteur. Sans option, la ligne est écrite dans `livres_a_corriger.txt`.
* **`[AJOUTÉ TEL QUEL]`** (avec `--repli-liste` ou `--sans-api`) : livre ajouté tel qu'écrit dans votre liste, sans couverture ni résumé.
* **`[DÉJÀ PRÉSENT]`** : le livre est déjà dans la collection, il est ignoré.

Conseils :

* Commencez toujours par un `--dry-run`.
* Sans option de repli, après 5 erreurs réseau d'affilée le script s'arrête ; les lignes à reprendre sont dans `livres_a_corriger.txt` (et `cd_a_corriger.txt` pour les CD). Corrigez-les puis relancez.
* Avec `--repli-liste`, après 5 erreurs réseau d'affilée le script bascule hors ligne pour le reste de la liste au lieu de s'arrêter.
* Une note personnelle entre parenthèses en fin de ligne, comme `(auteur à vérifier)`, est ignorée par le script.

---

## 📂 Structure du projet

```text
Directory structure:
└── mathieu7483-ma-mediatheque/
    ├── README.md
    ├── app.py
    ├── cd_list.txt
    ├── database.py
    ├── dvd-navbar.patch
    ├── livres_list.txt
    ├── movies_list.txt
    ├── page-ajouter.patch
    ├── requirements.txt
    ├── seed.py
    ├── seed_cd.py
    ├── seed_common.py
    ├── seed_livres.py
    ├── services/
    │   ├── books_service.py
    │   ├── discogs_service.py
    │   └── tmdb_service.py
    ├── static/
    │   └── style.css
    └── templates/
        ├── _flashes.html
        ├── add.html
        ├── base.html
        ├── cd.html
        ├── dvd.html
        ├── index.html
        └── livres.html

```

---

## 👤 Auteur

Projet personnel développé par **Mathieu** dans le cadre de son apprentissage de la programmation.