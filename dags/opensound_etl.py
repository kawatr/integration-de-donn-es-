from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
import psycopg2
import requests

API_KEY = "40b84a562b6a1875e163366d62152bb1"
CSV = "/opt/airflow/data/tracks.csv"
DB = dict(host="postgres", dbname="opensound", user="opensound", password="opensound")

def extract_kaggle():
    df = pd.read_csv(CSV, index_col=0)
    print(f"[KAGGLE] {len(df)} morceaux chargés")
    return df.to_json()

def extract_lastfm_artists(**context):
    df = pd.read_json(context['ti'].xcom_pull(task_ids='extract_kaggle'))
    artists = df[~df['artists'].str.contains(';', na=False)]['artists'].unique()[:100]
    results = []
    for name in artists:
        try:
            r = requests.get("http://ws.audioscrobbler.com/2.0/", params={
                "method": "artist.getInfo",
                "artist": name,
                "api_key": API_KEY,
                "format": "json"
            }, timeout=5)
            data = r.json().get("artist", {})
            stats = data.get("stats", {})
            results.append({
                "artist_name": name,
                "listeners": int(stats.get("listeners", 0)),
                "playcount": int(stats.get("playcount", 0)),
                "lastfm_url": data.get("url", "")
            })
        except Exception as e:
            print(f"[LASTFM] Erreur pour {name}: {e}")
    print(f"[LASTFM] {len(results)} artistes récupérés")
    return pd.DataFrame(results).to_json()

def extract_lastfm_tags():
    r = requests.get("http://ws.audioscrobbler.com/2.0/", params={
        "method": "chart.getTopTags",
        "api_key": API_KEY,
        "format": "json",
        "limit": 50
    })
    tags = r.json().get("tags", {}).get("tag", [])
    df = pd.DataFrame([{
        "tag_name": t["name"],
        "reach": int(t.get("reach", 0)),
        "taggings": int(t.get("taggings", 0))
    } for t in tags])
    print(f"[LASTFM] {len(df)} tags récupérés")
    return df.to_json()

def extract_lastfm_decades(**context):
    df = pd.read_json(context['ti'].xcom_pull(task_ids='extract_kaggle'))
    sample = df[~df['artists'].str.contains(';', na=False)].sample(min(200, len(df)), random_state=42)
    results = []
    for _, row in sample.iterrows():
        try:
            r = requests.get("http://ws.audioscrobbler.com/2.0/", params={
                "method": "track.getInfo",
                "artist": row['artists'],
                "track": row['track_name'],
                "api_key": API_KEY,
                "format": "json"
            }, timeout=5)
            data = r.json().get("track", {})
            wiki = data.get("wiki", {})
            published = wiki.get("published", "")
            year = None
            if published:
                try:
                    year = int(published.split(" ")[-1].replace(".", "")[:4])
                    if year < 1900 or year > 2030:
                        year = None
                except:
                    pass
            if year:
                results.append({
                    "track_id": row['track_id'],
                    "track_name": row['track_name'],
                    "artists": row['artists'],
                    "popularity": row['popularity'],
                    "year": year,
                    "decade": (year // 10) * 10
                })
        except Exception as e:
            print(f"[DECADES] Erreur: {e}")
    print(f"[DECADES] {len(results)} titres avec année trouvée")
    return pd.DataFrame(results).to_json() if results else pd.DataFrame().to_json()

def transform(**context):
    ti = context['ti']
    df_tracks = pd.read_json(ti.xcom_pull(task_ids='extract_kaggle'))
    df_tracks = df_tracks.dropna(subset=['track_id','track_name','artists','track_genre'])
    df_tracks['duration_s'] = df_tracks['duration_ms'] / 1000
    df_tracks['explicit'] = df_tracks['explicit'].astype(bool)
    cols = ['track_id','track_name','artists','track_genre','popularity','duration_s',
            'explicit','danceability','energy','valence','tempo']
    df_tracks = df_tracks[cols]

    df_artists = pd.read_json(ti.xcom_pull(task_ids='extract_lastfm_artists'))
    agg = df_tracks.groupby('artists').agg(
        nb_titres=('track_id', 'count'),
        popularite_moy=('popularity', 'mean'),
        duree_moy_s=('duration_s', 'mean'),
        danceability_moy=('danceability', 'mean'),
        energy_moy=('energy', 'mean'),
        valence_moy=('valence', 'mean'),
        tempo_moy=('tempo', 'mean'),
        genres=('track_genre', lambda x: ','.join(x.unique()[:3]))
    ).reset_index()
    agg.columns = ['artist_name','nb_titres','popularite_moy','duree_moy_s',
                   'danceability_moy','energy_moy','valence_moy','tempo_moy','genres']

    fact = agg.merge(df_artists, on='artist_name', how='left')
    fact['listeners'] = fact['listeners'].fillna(0).astype(int)
    fact['playcount'] = fact['playcount'].fillna(0).astype(int)
    fact['lastfm_url'] = fact['lastfm_url'].fillna('')

    print(f"[TRANSFORM] {len(df_tracks)} morceaux, {len(fact)} artistes")
    return {
        "tracks": df_tracks.to_json(),
        "artists": fact.to_json(),
        "tags": ti.xcom_pull(task_ids='extract_lastfm_tags'),
        "decades": ti.xcom_pull(task_ids='extract_lastfm_decades')
    }

def load(**context):
    data = context['ti'].xcom_pull(task_ids='transform')
    df_tracks  = pd.read_json(data['tracks'])
    df_artists = pd.read_json(data['artists'])
    df_tags    = pd.read_json(data['tags'])
    df_decades = pd.read_json(data['decades'])

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dim_tracks (
            track_id TEXT PRIMARY KEY, track_name TEXT, artists TEXT,
            genre TEXT, popularity INT, duration_s FLOAT, explicit BOOL,
            danceability FLOAT, energy FLOAT, valence FLOAT, tempo FLOAT
        )
    """)
    cur.execute("TRUNCATE dim_tracks")
    for _, r in df_tracks.iterrows():
        cur.execute("INSERT INTO dim_tracks VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", tuple(r))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dim_tags (
            tag_name TEXT PRIMARY KEY, reach INT, taggings INT
        )
    """)
    cur.execute("TRUNCATE dim_tags")
    for _, r in df_tags.iterrows():
        cur.execute("INSERT INTO dim_tags VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", tuple(r))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fact_artists (
            artist_name TEXT PRIMARY KEY, nb_titres INT, popularite_moy FLOAT,
            duree_moy_s FLOAT, danceability_moy FLOAT, energy_moy FLOAT,
            valence_moy FLOAT, tempo_moy FLOAT, genres TEXT,
            listeners BIGINT, playcount BIGINT, lastfm_url TEXT
        )
    """)
    cur.execute("TRUNCATE fact_artists")
    for _, r in df_artists.iterrows():
        cur.execute("INSERT INTO fact_artists VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", tuple(r))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dim_decades (
            track_id TEXT PRIMARY KEY, track_name TEXT, artists TEXT,
            popularity INT, year INT, decade INT
        )
    """)
    cur.execute("TRUNCATE dim_decades")
    if not df_decades.empty:
        for _, r in df_decades.iterrows():
            cur.execute("INSERT INTO dim_decades VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", tuple(r))

    conn.commit()
    cur.close(); conn.close()
    print(f"[LOAD] OK — {len(df_tracks)} tracks, {len(df_artists)} artistes, {len(df_decades)} avec décennie")

with DAG(
    dag_id="opensound_etl",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["opensound"]
) as dag:

    t_kaggle  = PythonOperator(task_id="extract_kaggle",          python_callable=extract_kaggle)
    t_artists = PythonOperator(task_id="extract_lastfm_artists",  python_callable=extract_lastfm_artists)
    t_tags    = PythonOperator(task_id="extract_lastfm_tags",     python_callable=extract_lastfm_tags)
    t_decades = PythonOperator(task_id="extract_lastfm_decades",  python_callable=extract_lastfm_decades)
    t_transfo = PythonOperator(task_id="transform",               python_callable=transform)
    t_load    = PythonOperator(task_id="load",                    python_callable=load)

    t_kaggle >> [t_artists, t_decades]
    [t_artists, t_tags, t_decades] >> t_transfo >> t_load