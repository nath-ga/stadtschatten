# stadtschatten/modules/kantenbewertung.py
#
# DIE Knackstelle: jeder Wegekante einen Sonnen-/Schattenanteil zuweisen.
#
# Vorgehen (ein Verschnitt für ALLE Kanten, nicht Kante für Kante):
#   1. Jede Kante in Stützpunkte zerlegen (alle SAMPLE_ABSTAND_M Meter)
#   2. ALLE Punkte aller Kanten in EINEM GeoDataFrame sammeln
#   3. EIN sjoin gegen die Schattenflächen -> welche Punkte liegen im Schatten?
#   4. pro Kante mitteln -> sonnenanteil (0 = ganz Schatten, 1 = ganz Sonne)
#
# Ergebnis wird als Kanten-Attribut in den Graphen geschrieben:
#   sonnenanteil, w_schattig, w_schnell  -> bereit fürs Routing.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import geopandas as gpd
import osmnx as ox

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE,
                    ALPHA_SCHATTIG, ALPHA_SCHNELL, get_zeitpunkt)
from modules.karte_info import info_box

# Abstand der Stützpunkte entlang jeder Kante. Kleiner = genauer, aber mehr Punkte.
SAMPLE_ABSTAND_M = 5.0


def bewerte_kanten(G, schatten):
    """
    Weist jeder Kante einen sonnenanteil zu und schreibt Gewichte in den Graphen.

    G        : projizierter Geh-Graph (CRS_METRISCH)
    schatten : Schattenpolygone (CRS_METRISCH)

    Rückgabe : (G mit neuen Kanten-Attributen, edges-GeoDataFrame zur Visualisierung)
    """
    edges = ox.graph_to_gdfs(G, nodes=False).reset_index()  # Spalten u, v, key, geometry
    edges["edge_id"] = edges.index
    edges["laenge"] = edges.geometry.length

    # 1+2: Stützpunkte aller Kanten in EINEM GeoDataFrame
    recs = []
    for eid, geom in zip(edges["edge_id"], edges.geometry):
        laenge = geom.length
        n = max(int(laenge // SAMPLE_ABSTAND_M), 1)
        for d in np.linspace(0, laenge, n + 1):
            recs.append((eid, geom.interpolate(d)))
    pts = gpd.GeoDataFrame(recs, columns=["edge_id", "geometry"], crs=CRS_METRISCH)
    print(f"  {len(edges)} Kanten -> {len(pts)} Stützpunkte.")

    # 3: EIN Verschnitt gegen die Schatten
    joined = gpd.sjoin(pts, schatten[["geometry"]], how="left", predicate="intersects")
    pts["im_schatten"] = (
        joined["index_right"].notna().groupby(level=0).max().reindex(pts.index).values
    )

    # 4: pro Kante mitteln
    anteil_schatten = pts.groupby("edge_id")["im_schatten"].mean()
    edges["sonnenanteil"] = (1 - edges["edge_id"].map(anteil_schatten)).fillna(1.0)

    # Gewichte: w = laenge * (1 + ALPHA * sonnenanteil)
    edges["w_schattig"] = edges["laenge"] * (1 + ALPHA_SCHATTIG * edges["sonnenanteil"])
    edges["w_schnell"]  = edges["laenge"] * (1 + ALPHA_SCHNELL  * edges["sonnenanteil"])

    # Attribute zurück in den Graphen schreiben (fürs networkx-Routing)
    for u, v, k, son, ws, wf, ln in zip(
        edges["u"], edges["v"], edges["key"],
        edges["sonnenanteil"], edges["w_schattig"], edges["w_schnell"], edges["laenge"]
    ):
        G[u][v][k]["sonnenanteil"] = float(son)
        G[u][v][k]["w_schattig"]   = float(ws)
        G[u][v][k]["w_schnell"]    = float(wf)
        G[u][v][k]["laenge"]       = float(ln)

    mittel = edges["sonnenanteil"].mean()
    print(f"  Mittlerer Sonnenanteil im Netz: {mittel:.2f} "
          f"({(1-mittel)*100:.0f} % beschattet).")
    return G, edges


def karte_kanten(edges, schatten=None, pfad=None):
    """Färbt die Kanten nach Sonnenanteil (grün = schattig, rot = sonnig) auf einer Folium-Karte.
    schatten (optional): wird als abschaltbare Unterlage mitgezeichnet."""
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "kanten_sonnenanteil.html")

    e = edges[["geometry", "sonnenanteil"]].to_crs(CRS_WGS84)
    mitte = e.geometry.union_all().centroid
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=17, tiles=None)

    # Zwei Grundkarten zum Umschalten (oben rechts):
    folium.TileLayer("CartoDB positron", name="Karte").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellit",
    ).add_to(m)

    # Schattenflächen als (abschaltbare) Unterlage – zeigt, WARUM ein Weg grün ist.
    if schatten is not None:
        folium.GeoJson(
            schatten.to_crs(CRS_WGS84), name="Schatten (Boden)",
            style_function=lambda f: {"fillColor": "#2b3a67", "color": "#2b3a67",
                                      "weight": 0, "fillOpacity": 0.35},
        ).add_to(m)

    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Sonnenanteil (0 = schattig, 1 = sonnig)"

    folium.GeoJson(
        e, name="Wege (Sonnenanteil)",
        style_function=lambda f: {
            "color": cmap(f["properties"]["sonnenanteil"]),
            "weight": 4, "opacity": 0.9,
        },
    ).add_to(m)
    cmap.add_to(m)
    folium.LayerControl().add_to(m)

    # Lauf-Parameter + Quellenangaben sichtbar auf die Karte (Alpha hier ohne Wirkung)
    gebiet = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {
        "Datum/Uhrzeit": get_zeitpunkt().strftime("%d.%m.%Y %H:%M"),
        "Gebiet":        gebiet,
    })

    m.save(pfad)
    print(f"  Karte gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    from modules.loader import lade_geh_graph, lade_gebaeude_mit_hoehe
    from modules.schatten import berechne_schatten

    G = lade_geh_graph()
    gebaeude = lade_gebaeude_mit_hoehe()
    schatten = berechne_schatten(gebaeude)
    G, edges = bewerte_kanten(G, schatten)
    karte_kanten(edges, schatten)