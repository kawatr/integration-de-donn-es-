CREATE TABLE IF NOT EXISTS raw_tracks (
    track_id      TEXT PRIMARY KEY,
    track_name    TEXT,
    artists       TEXT,
    album_name    TEXT,
    track_genre   TEXT,
    popularity    INTEGER,
    duration_ms   INTEGER,
    explicit      BOOLEAN,
    release_date  TEXT
);

CREATE TABLE IF NOT EXISTS dim_genre AS SELECT DISTINCT track_genre FROM raw_tracks WHERE FALSE;
ALTER TABLE dim_genre ADD COLUMN genre_id SERIAL PRIMARY KEY;

CREATE TABLE IF NOT EXISTS fact_tracks (
    track_id    TEXT PRIMARY KEY,
    track_name  TEXT,
    artists     TEXT,
    genre       TEXT,
    popularity  INTEGER,
    duration_s  FLOAT,
    explicit    BOOLEAN,
    decade      INTEGER
);