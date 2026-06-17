import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2

st.set_page_config(page_title="OpenSound Dashboard", layout="wide")
st.title("OpenSound — Aide à la décision artiste")

@st.cache_data
def query(sql):
    conn = psycopg2.connect(host="postgres", dbname="opensound",
                            user="opensound", password="opensound")
    df = pd.read_sql(sql, conn)
    conn.close()
    return df

def safe_query(sql):
    try:
        return query(sql)
    except Exception:
        return None

# KPIs GLOBAUX
st.header("Vue globale")

stats    = query("SELECT COUNT(*) as artistes, SUM(nb_titres) as titres FROM fact_artists")
nb_genre = query("SELECT COUNT(DISTINCT genre) as nb FROM dim_tracks")
pct_exp  = query("""
    SELECT ROUND(100.0 * SUM(CASE WHEN explicit THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
    FROM dim_tracks
""")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Artistes analysés", f"{stats['artistes'][0]:,}")
c2.metric("Titres analysés",   f"{stats['titres'][0]:,}")
c3.metric("Genres couverts",   f"{nb_genre['nb'][0]}")
c4.metric("Titres explicites", f"{pct_exp['pct'][0]} %")

# Q1 — Quels genres et artistes dominent le classement ?
st.divider()
st.header("Q1 — Quels genres et artistes dominent le classement ?")

# — Genres : popularité moyenne + volume de titres
col_g1, col_g2 = st.columns(2)

with col_g1:
    df_genre_pop = query("""
        SELECT genre,
               ROUND(AVG(popularity)::numeric, 1) as popularite_moy,
               COUNT(*) as nb_titres
        FROM dim_tracks
        GROUP BY genre ORDER BY popularite_moy DESC LIMIT 15
    """)
    st.plotly_chart(px.bar(df_genre_pop,
        x="genre", y="popularite_moy", color="popularite_moy",
        color_continuous_scale="Blues",
        hover_data=["nb_titres"],
        title="Popularité moyenne par genre (Top 15)",
        labels={"genre": "Genre", "popularite_moy": "Popularité moyenne"}
    ), use_container_width=True)

with col_g2:
    df_genre_vol = query("""
        SELECT genre, COUNT(*) as nb_titres
        FROM dim_tracks GROUP BY genre ORDER BY nb_titres DESC LIMIT 15
    """)
    st.plotly_chart(px.pie(df_genre_vol,
        names="genre", values="nb_titres",
        title="Répartition du volume de titres par genre",
        color_discrete_sequence=px.colors.sequential.Blues_r,
        hole=0.38
    ), use_container_width=True)

# — Artistes : score composite Spotify + Last.fm
st.subheader("Top artistes — score composite (popularité Spotify × audience Last.fm)")

df_artistes = query("""
    SELECT artist_name, popularite_moy, listeners, nb_titres, genres,
           ROUND((popularite_moy * 0.5 + LEAST(listeners / 1000000.0, 50))::numeric, 1) as score
    FROM fact_artists
    WHERE listeners > 0
    ORDER BY score DESC
    LIMIT 25
""")

col_a1, col_a2 = st.columns([3, 2])
with col_a1:
    st.plotly_chart(px.scatter(df_artistes,
        x="popularite_moy", y="listeners",
        size="nb_titres", color="genres",
        hover_name="artist_name",
        hover_data={"score": True},
        title="Popularité Spotify vs Audience Last.fm (taille = nb titres)",
        labels={"popularite_moy": "Popularité Spotify", "listeners": "Listeners Last.fm"}
    ), use_container_width=True)

with col_a2:
    st.plotly_chart(px.bar(df_artistes.head(10),
        x="score", y="artist_name", orientation="h",
        color="score", color_continuous_scale="Teal",
        title="Top 10 — Score composite",
        labels={"score": "Score", "artist_name": ""}
    ).update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False),
    use_container_width=True)

# Q2 — Comment la durée ou le contenu explicite impacte la popularité ?
st.divider()
st.header("Q2 — Comment la durée ou le contenu explicite impacte la popularité ?")

col_e1, col_e2 = st.columns(2)

with col_e1:
    df_dur = query("""
        SELECT duration_s, popularity, explicit
        FROM dim_tracks
        WHERE popularity > 0 AND duration_s BETWEEN 30 AND 600
        LIMIT 6000
    """)
    st.plotly_chart(px.scatter(df_dur,
        x="duration_s", y="popularity", color="explicit",
        opacity=0.35,
        title="Durée vs Popularité",
        labels={"duration_s": "Durée (secondes)", "popularity": "Popularité"}
    ), use_container_width=True)

with col_e2:
    # Durée découpée en tranches → popularité moyenne par tranche
    df_dur2 = query("""
        SELECT
            CASE
                WHEN duration_s < 120  THEN '< 2 min'
                WHEN duration_s < 180  THEN '2–3 min'
                WHEN duration_s < 240  THEN '3–4 min'
                WHEN duration_s < 300  THEN '4–5 min'
                WHEN duration_s < 420  THEN '5–7 min'
                ELSE '> 7 min'
            END as tranche,
            ROUND(AVG(popularity)::numeric, 1) as popularite_moy,
            COUNT(*) as nb
        FROM dim_tracks
        WHERE popularity > 0 AND duration_s BETWEEN 30 AND 900
        GROUP BY tranche
        ORDER BY MIN(duration_s)
    """)
    st.plotly_chart(px.bar(df_dur2,
        x="tranche", y="popularite_moy",
        color="popularite_moy", color_continuous_scale="Oranges",
        text="popularite_moy",
        title="Popularité moyenne par tranche de durée",
        hover_data=["nb"],
        labels={"tranche": "Durée", "popularite_moy": "Popularité moy"}
    ).update_traces(textposition="outside"), use_container_width=True)

# Impact contenu explicite
col_ex1, col_ex2 = st.columns(2)

with col_ex1:
    df_exp = query("""
        SELECT
            CASE WHEN explicit THEN 'Explicite ✓' ELSE 'Non explicite' END as type_contenu,
            ROUND(AVG(popularity)::numeric, 2) as popularite_moy,
            COUNT(*) as nb_titres
        FROM dim_tracks WHERE popularity > 0
        GROUP BY explicit
    """)
    fig_exp = px.bar(df_exp,
        x="type_contenu", y="popularite_moy",
        color="type_contenu",
        color_discrete_map={"Explicite ✓": "#e05c5c", "Non explicite": "#5c8de0"},
        text="popularite_moy",
        title="Popularité moyenne : explicite vs non",
        hover_data=["nb_titres"],
        labels={"popularite_moy": "Popularité moyenne", "type_contenu": ""}
    )
    fig_exp.update_traces(textposition="outside")
    fig_exp.update_layout(showlegend=False)
    st.plotly_chart(fig_exp, use_container_width=True)

with col_ex2:
    df_hist = query("SELECT popularity, explicit FROM dim_tracks WHERE popularity > 0")
    st.plotly_chart(px.histogram(df_hist,
        x="popularity", color="explicit",
        nbins=40, barmode="overlay", opacity=0.65,
        title="Distribution de popularité (explicite vs non)",
        labels={"popularity": "Popularité", "count": "Nb titres"}
    ), use_container_width=True)

st.divider()
st.header("Q3 — Quels genres contiennent le plus de titres ?")

df3 = query("""
    SELECT genre, COUNT(*) as nb_titres
    FROM dim_tracks
    WHERE genre IS NOT NULL
    GROUP BY genre
    ORDER BY nb_titres DESC
    LIMIT 15
""")

st.plotly_chart(px.bar(
    df3,
    x="genre",
    y="nb_titres",
    color="nb_titres",
    title="Nombre de titres par genre",
    labels={"genre": "Genre", "nb_titres": "Nombre de titres"},
    color_continuous_scale="Teal"
), use_container_width=True)

# Q4 — Autres questions pertinentes
st.divider()
st.header("Q4 — Autres questions pertinentes")

# — 4a : Tags Last.fm — tendances culturelles
st.subheader("4a · Quels tags culturels dominent sur Last.fm ?")
df_tags = query("SELECT tag_name, reach, taggings FROM dim_tags ORDER BY taggings DESC LIMIT 15")
st.plotly_chart(px.bar(df_tags,
    x="tag_name", y="taggings", color="reach",
    color_continuous_scale="Teal",
    title="Top 15 tags Last.fm (taggings = popularité, reach = audience unique)",
    labels={"tag_name": "Tag", "taggings": "Taggings", "reach": "Reach"}
), use_container_width=True)

# — 4b : Artistes les plus productifs vs populaires
st.subheader("4b · Les artistes au large catalogue sont-ils plus populaires ?")

df_prod = query("""
    SELECT artist_name, nb_titres, popularite_moy, genres, listeners
    FROM fact_artists WHERE nb_titres >= 3
    ORDER BY nb_titres DESC LIMIT 40
""")

col_p1, col_p2 = st.columns([3, 2])
with col_p1:
    st.plotly_chart(px.scatter(df_prod,
        x="nb_titres", y="popularite_moy",
        size="nb_titres", color="popularite_moy",
        color_continuous_scale="Viridis",
        hover_name="artist_name",
        hover_data=["genres", "listeners"],
        title="Catalogue vs Popularité (Top 40 artistes prolific)",
        labels={"nb_titres": "Nombre de titres", "popularite_moy": "Popularité moy"}
    ), use_container_width=True)

with col_p2:
    st.plotly_chart(px.bar(df_prod.head(15),
        x="nb_titres", y="artist_name", orientation="h",
        color="popularite_moy", color_continuous_scale="Blues",
        title="Top 15 — Artistes par volume de catalogue",
        labels={"nb_titres": "Titres", "artist_name": "", "popularite_moy": "Popularité moy"}
    ).update_layout(yaxis={"categoryorder": "total ascending"}),
    use_container_width=True)


# TABLE COMPLÈTE ARTISTES
st.divider()
st.header("Table complète artistes")

search = st.text_input("Rechercher un artiste")
df_table = query("SELECT * FROM fact_artists ORDER BY popularite_moy DESC LIMIT 200")
if search:
    df_table = df_table[df_table["artist_name"].str.contains(search, case=False, na=False)]
st.dataframe(df_table, use_container_width=True)