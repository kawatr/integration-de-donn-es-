# 🎧 OpenSound

Pipeline Big Data qui croise le dataset **Spotify** (Kaggle) avec l'**API Last.fm** pour analyser la popularité musicale, et restitue les résultats dans un dashboard **Streamlit** d'aide à la décision artiste.

## Sommaire

- [Contexte](#contexte)
- [Architecture](#architecture)
- [Stack technique](#stack-technique)
- [Structure du projet](#structure-du-projet)
- [Modèle de données](#modèle-de-données)
- [Installation & lancement](#installation--lancement)
- [Le pipeline ETL](#le-pipeline-etl)
- [Le dashboard](#le-dashboard)
- [Limites connues](#limites-connues--todo)

## Contexte

La popularité Spotify mesure l'écoute sur une seule plateforme, mais pas la notoriété culturelle globale d'un artiste. Last.fm apporte une audience communautaire (`listeners`, `playcount`) et des tags culturels indépendants. OpenSound croise les deux pour répondre à des questions concrètes :

- Quels genres et artistes dominent le classement (popularité × audience) ?
- La durée d'un titre ou son contenu explicite influencent-ils sa popularité ?
- Quels genres sont les plus représentés dans le catalogue ?
- Quelles tendances culturelles ressortent des tags Last.fm ? Le volume de production d'un artiste est-il lié à sa popularité ?

## Architecture

```
┌──────────────────┐      ┌───────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  CSV Kaggle       │      │  Airflow           │      │  PostgreSQL       │      │  Streamlit        │
│  + API Last.fm    │ ───► │  DAG opensound_etl │ ───► │  schéma en étoile │ ───► │  Dashboard        │
└──────────────────┘      └───────────────────┘      └──────────────────┘      └──────────────────┘
```

3 services Docker Compose :

| Service     | Image                 | Rôle                                             |
|-------------|-----------------------|---------------------------------------------------|
| `postgres`  | `postgres:15`         | Stockage (schéma en étoile)                       |
| `airflow`   | `apache/airflow:2.8.0`| Orchestration quotidienne du pipeline ETL         |
| `dashboard` | `python:3.11-slim`    | Restitution Streamlit + Plotly                    |

## Stack technique

- **Orchestration** : Apache Airflow 2.8 (`schedule_interval="@daily"`, `catchup=False`)
- **Stockage** : PostgreSQL 15
- **Traitement** : Python / pandas / psycopg2 / requests
- **Restitution** : Streamlit + Plotly
- **Conteneurisation** : Docker Compose

## Structure du projet

```
opensound/
├── dags/
│   └── opensound_etl.py     # DAG Airflow : extract → transform → load
├── dashboard/
│   └── app.py                # Dashboard Streamlit
├── data/
│   └── tracks.csv             # Dataset Spotify (Kaggle, ~114 000 titres)
├── sql/
│   └── init.sql               # Schéma initial PostgreSQL
├── docker-compose.yml
└── requirements.txt
```

## Modèle de données

Schéma en étoile, rechargé (`TRUNCATE` + réinsertion) à chaque exécution du DAG :

| Table          | Colonnes principales                                                                 |
|----------------|----------------------------------------------------------------------------------------|
| `dim_tracks`   | `track_id`, `track_name`, `artists`, `genre`, `popularity`, `duration_s`, `explicit`, `danceability`, `energy`, `valence`, `tempo` |
| `dim_tags`     | `tag_name`, `reach`, `taggings`                                                        |
| `fact_artists` | `artist_name`, `nb_titres`, `popularite_moy`, `duree_moy_s`, `danceability_moy`, `energy_moy`, `valence_moy`, `tempo_moy`, `genres`, `listeners`, `playcount`, `lastfm_url` |
| `dim_decades`  | `track_id`, `track_name`, `artists`, `popularity`, `year`, `decade`                    |

## Installation & lancement

### Prérequis

- Docker et Docker Compose
- Une clé API [Last.fm](https://www.last.fm/api/account/create) (gratuite)

### Étapes

```bash
git clone <url-du-repo>
cd opensound
```

⚠️ Avant de lancer le projet, externalise la clé API Last.fm (voir [Limites connues](#limites-connues--todo)) au lieu d'utiliser celle codée en dur dans `dags/opensound_etl.py`.

```bash
docker compose up -d
```

| Interface       | URL                          | Identifiants          |
|-----------------|-------------------------------|------------------------|
| Airflow         | http://localhost:8080         | `admin` / `admin`     |
| Dashboard       | http://localhost:8501         | —                      |
| PostgreSQL      | `localhost:5432`              | `opensound` / `opensound` |

Dans l'interface Airflow, active puis déclenche le DAG **`opensound_etl`** pour lancer la première exécution du pipeline. Le dashboard se peuple automatiquement une fois le `load` terminé.

## Le pipeline ETL

Le DAG `opensound_etl` (`dags/opensound_etl.py`) s'exécute quotidiennement et enchaîne :

**Extract** (4 tâches, en partie parallèles) :
- `extract_kaggle` — charge le CSV Spotify (~114 000 titres)
- `extract_lastfm_artists` — infos Last.fm (`artist.getInfo`) pour les 100 premiers artistes solo
- `extract_lastfm_tags` — top 50 tags culturels (`chart.getTopTags`)
- `extract_lastfm_decades` — échantillon de 200 titres → année et décennie de sortie (`track.getInfo`)

**Transform** :
- Nettoyage des titres (suppression des lignes incomplètes, conversion durée/booléen)
- Agrégation par artiste (nb de titres, moyennes des features audio)
- Jointure avec les statistiques Last.fm

**Load** :
- Création des tables si nécessaire, `TRUNCATE` puis insertion dans PostgreSQL (idempotence)

Dépendances des tâches :
```
extract_kaggle >> [extract_lastfm_artists, extract_lastfm_decades]
[extract_lastfm_artists, extract_lastfm_tags, extract_lastfm_decades] >> transform >> load
```

## Le dashboard

Le dashboard Streamlit (`dashboard/app.py`) affiche une vue globale (KPIs) puis répond à 4 questions d'analyse :

- **Q1** — Quels genres et artistes dominent le classement ?
- **Q2** — Impact de la durée et du contenu explicite sur la popularité
- **Q3** — Volume de titres par genre
- **Q4** — Tendances culturelles (tags Last.fm) et lien catalogue / popularité

## Limites connues & TODO

- [ ] **Sécurité** : la clé API Last.fm est actuellement codée en dur dans `dags/opensound_etl.py` — à sortir en variable d'environnement / secret Airflow avant tout partage public du repo
- [ ] Échantillon limité à 100 artistes et 200 titres pour les appels Last.fm (limitation de débit de l'API gratuite)
- [ ] Reconstitution de l'année de sortie approximative (basée sur le wiki Last.fm)
- [ ] `requirements.txt` à compléter (dépendances actuellement installées à la volée dans le conteneur `dashboard`)
- [ ] Pistes d'évolution : stockage cloud (S3/ADLS), modèle de recommandation ML, historisation des scores dans le temps
