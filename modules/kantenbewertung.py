# stadtschatten/modules/kantenbewertung.py
#
# DIE Knackstelle: jeder Wegekante einen Sonnen-/Schattenanteil zuweisen.
#
# Vorgehen (ein Verschnitt fuer ALLE Kanten, nicht Kante fuer Kante):
#   1. Jede Kante in Stuetzpunkte zerlegen (alle SAMPLE_ABSTAND_M Meter)
#   2. ALLE Punkte aller Kanten in EINEM GeoDataFrame sammeln
#   3. EIN sjoin gegen die Schattenflaechen -> welche Punkte liegen im Schatten?
#   4. pro Kante mitteln -> sonnenanteil (0 = ganz Schatten, 1 = ganz Sonne)
#
# AUFGETEILT in drei Bausteine, damit die Zeit-Aggregation ("Sonnendosis")
# nur den teuren Teil (Schatten + Verschnitt) wiederholt:
#   kanten_stuetzpunkte(G)              -> einmal  (reine Geometrie)
#   sonnenanteil_je_kante(pts, edges, schatten) -> pro Stunde
#   schreibe_gewichte(G, edges, son)    -> einmal  (Gewichte in den Graphen)
#
# bewerte_kanten()            ruft die drei fuer EINEN Zeitpunkt (unveraendert).
# bewerte_kanten_aggregiert() ruft Baustein 2 in einer Stundenschleife und
#                             mittelt je Kante -> nur fuer die Expositionskarte.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE,
                    ALPHA_SCHATTIG, ALPHA_SCHNELL, get_zeitpunkt, get_zeitpunkt_stunde)
from modules.karte_info import info_box

# Abstand der Stuetzpunkte entlang jeder Kante. Kleiner = genauer, aber mehr Punkte.
SAMPLE_ABSTAND_M = 5.0


# ----------------------------------------------------------------------
# Baustein 1: Stuetzpunkte (einmal, reine Geometrie)
# ----------------------------------------------------------------------

def kanten_stuetzpunkte(G):
    """Baut das edges-GeoDataFrame und alle Stuetzpunkte. Reine Geometrie,
    ueber die Stunden konstant -> bei der Aggregation nur EINMAL gerufen.

    Rueckgabe: (edges, pts)
      edges : GeoDataFrame mit u, v, key, geometry, edge_id, laenge
      pts   : GeoDataFrame aller Stuetzpunkte mit Spalte edge_id (CRS_METRISCH)
    """
    edges = ox.graph_to_gdfs(G, nodes=False).reset_index()  # Spalten u, v, key, geometry
    edges["edge_id"] = edges.index
    edges["laenge"] = edges.geometry.length

    recs = []
    for eid, geom in zip(edges["edge_id"], edges.geometry):
        laenge = geom.length
        n = max(int(laenge // SAMPLE_ABSTAND_M), 1)
        for d in np.linspace(0, laenge, n + 1):
            recs.append((eid, geom.interpolate(d)))
    pts = gpd.GeoDataFrame(recs, columns=["edge_id", "geometry"], crs=CRS_METRISCH)
    print(f"  {len(edges)} Kanten -> {len(pts)} Stuetzpunkte.")
    return edges, pts


# ----------------------------------------------------------------------
# Baustein 2: Sonnenanteil je Kante fuer EINEN Zeitpunkt (pro Stunde)
# ----------------------------------------------------------------------

def sonnenanteil_je_kante(pts, edges, schatten):
    """Verschneidet die Stuetzpunkte mit den Schattenflaechen EINES Zeitpunkts
    und mittelt je Kante. Das ist der einzige Teil, der sich stuendlich aendert.
    Mutiert pts NICHT (wichtig, weil pts in der Schleife wiederverwendet wird).

    Rueckgabe: Series sonnenanteil, indexiert ueber edge_id
               (0 = ganz Schatten, 1 = ganz Sonne).
    """
    joined = gpd.sjoin(pts, schatten[["geometry"]], how="left", predicate="intersects")
    im_schatten = (
        joined["index_right"].notna().groupby(level=0).max().reindex(pts.index).values
    )
    df = pts[["edge_id"]].copy()
    df["im_schatten"] = im_schatten
    anteil_schatten = df.groupby("edge_id")["im_schatten"].mean()

    # auf alle Kanten ausrichten; Kanten ohne Treffer -> volle Sonne (1.0)
    son = (1 - edges["edge_id"].map(anteil_schatten)).fillna(1.0)
    son.index = edges["edge_id"].values   # eindeutig ueber edge_id indexiert
    return son


# ----------------------------------------------------------------------
# Baustein 3: Gewichte schreiben (einmal, am Ende)
# ----------------------------------------------------------------------

def schreibe_gewichte(G, edges, sonnenanteil):
    """Rechnet aus dem (ggf. gemittelten) sonnenanteil die Gewichte und schreibt
    sonnenanteil, w_schattig, w_schnell, laenge in den Graphen. Ergaenzt
    sonnenanteil auch als Spalte in edges (fuer die Karte).

    sonnenanteil : Series indexiert ueber edge_id
    Rueckgabe    : (G mit Attributen, edges-GeoDataFrame)
    """
    edges = edges.copy()
    edges["sonnenanteil"] = edges["edge_id"].map(sonnenanteil)

    edges["w_schattig"] = edges["laenge"] * (1 + ALPHA_SCHATTIG * edges["sonnenanteil"])
    edges["w_schnell"]  = edges["laenge"] * (1 + ALPHA_SCHNELL  * edges["sonnenanteil"])

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


# ----------------------------------------------------------------------
# Einzelmoment (unveraendert im Verhalten) – duenner Wrapper
# ----------------------------------------------------------------------

def bewerte_kanten(G, schatten):
    """Einzelmoment: Stuetzpunkte -> ein Verschnitt -> Gewichte.
    Verhaelt sich exakt wie die fruehere Funktion, nur intern aufgeteilt.

    Rueckgabe: (G mit neuen Kanten-Attributen, edges-GeoDataFrame)
    """
    edges, pts = kanten_stuetzpunkte(G)
    son = sonnenanteil_je_kante(pts, edges, schatten)
    return schreibe_gewichte(G, edges, son)


# ----------------------------------------------------------------------
# Zeit-Aggregation ("Sonnendosis") – nur fuer die Expositionskarte
# ----------------------------------------------------------------------

def bewerte_kanten_aggregiert(G, gebaeude, stunden):
    """Mittelt den Sonnenanteil je Kante ueber mehrere Stunden.
    Stuetzpunkte EINMAL, Schatten je Stunde, Sonnenanteil je Kante mitteln,
    dann Gewichte schreiben.

    G        : projizierter Geh-Graph (CRS_METRISCH)
    gebaeude : Gebaeude mit Hoehe (CRS_WGS84) fuer berechne_schatten
    stunden  : iterierbar mit ganzen Stunden, z.B. range(11, 19)

    Rueckgabe: (G mit Attributen, edges-GeoDataFrame)
    """
    # Import hier (nicht oben), sonst Zirkel: schatten.py importiert nichts aus
    # kantenbewertung.py, aber wir halten die Abhaengigkeit lokal und sichtbar.
    from modules.schatten import berechne_schatten

    stunden = list(stunden)
    if not stunden:
        raise ValueError(
            "Leeres Zeitfenster: ist AGG_END_STUNDE < AGG_START_STUNDE in config.py? "
            "Ohne Stunden gibt es nichts zu mitteln."
        )

    edges, pts = kanten_stuetzpunkte(G)   # einmal

    anteile = []
    for stunde in stunden:
        zeitpunkt = get_zeitpunkt_stunde(stunde)
        print(f"  Stunde {stunde:02d}:00 ...")
        schatten = berechne_schatten(gebaeude, zeitpunkt)
        anteile.append(sonnenanteil_je_kante(pts, edges, schatten))

    # je Kante ueber die Stunden mitteln (alle Series identisch ueber edge_id
    # indexiert -> concat richtet sich garantiert korrekt aus)
    son_mittel = pd.concat(anteile, axis=1).mean(axis=1)

    print(f"  {len(stunden)} Stunden gemittelt "
          f"({stunden[0]:02d}:00-{stunden[-1]:02d}:00).")
    return schreibe_gewichte(G, edges, son_mittel)


# ----------------------------------------------------------------------
# Karte
# ----------------------------------------------------------------------

def karte_kanten(edges, schatten=None, pfad=None, zeit_label=None):
    """Faerbt die Kanten nach Sonnenanteil (gruen = schattig, rot = sonnig).

    schatten   (optional): abschaltbare Unterlage. Im Aggregat-Modus NICHT
               uebergeben - kein einzelner Schatten passt zum Mittelwert.
    zeit_label (optional): Text fuer die Info-Box. None -> Einzeluhrzeit aus
               get_zeitpunkt(). Im Aggregat-Modus z.B. '18.06.2026 11-18 Uhr (Mittel)'.
    """
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "kanten_sonnenanteil.html")

    e = edges[["geometry", "sonnenanteil"]].to_crs(CRS_WGS84)
    mitte = e.geometry.union_all().centroid
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=17, tiles=None)

    folium.TileLayer("CartoDB positron", name="Karte").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellit",
    ).add_to(m)

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

    if zeit_label is None:
        zeit_label = get_zeitpunkt().strftime("%d.%m.%Y %H:%M")

    gebiet = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {
        "Datum/Uhrzeit": zeit_label,
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