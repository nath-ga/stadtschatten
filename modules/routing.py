# stadtschatten/modules/routing.py
#
# Der Kernzweck: Start + Ziel -> gewichteter kürzester Pfad.
# Umschalter über die in kantenbewertung.py vorberechneten Gewichte:
#   w_schnell  (ALPHA = 0)    -> kürzeste Strecke, Schatten egal
#   w_schattig (ALPHA hoch)   -> schattigster Weg, Umwege erlaubt
#
# Start/Ziel kommen aus config.START / config.ZIEL als (lat, lon).
# Sind sie None, werden zwei diagonale Demo-Punkte automatisch gewählt.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
import geopandas as gpd
import osmnx as ox
from shapely.geometry import LineString, Point

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, START, ZIEL,
                    ZENTRUM, RADIUS_M, PLACE, ALPHA_SCHATTIG, get_zeitpunkt)
from modules.karte_info import info_box
from modules.kartenbasis import basis_layer


def _latlon_zu_metrisch(latlon):
    """(lat, lon) -> (x, y) im metrischen CRS."""
    p = gpd.GeoSeries([Point(latlon[1], latlon[0])], crs=CRS_WGS84).to_crs(CRS_METRISCH).iloc[0]
    return p.x, p.y


def _knoten_latlon(G, node):
    """Knoten-Koordinaten (metrisch) -> (lat, lon) für Marker."""
    p = gpd.GeoSeries([Point(G.nodes[node]["x"], G.nodes[node]["y"])],
                      crs=CRS_METRISCH).to_crs(CRS_WGS84).iloc[0]
    return p.y, p.x


def start_ziel_knoten(G):
    """Liefert (orig, dest) Graph-Knoten. Aus config oder als Demo-Diagonale."""
    if START and ZIEL:
        ox_, oy = _latlon_zu_metrisch(START)
        zx, zy = _latlon_zu_metrisch(ZIEL)
        orig = ox.distance.nearest_nodes(G, X=ox_, Y=oy)
        dest = ox.distance.nearest_nodes(G, X=zx, Y=zy)
        return orig, dest

    # Demo: Knoten nahe Südwest- und Nordost-Ecke (diagonal quer durchs Gebiet)
    print("  START/ZIEL nicht gesetzt -> verwende Demo-Diagonale.")
    knoten = list(G.nodes(data=True))
    orig = min(knoten, key=lambda n: n[1]["x"] + n[1]["y"])[0]
    dest = max(knoten, key=lambda n: n[1]["x"] + n[1]["y"])[0]
    return orig, dest


def _route_kanten(G, route, weight):
    """Die tatsächlich benutzten Kanten-Datensätze entlang der Route (Multigraph-sicher)."""
    for u, v in zip(route[:-1], route[1:]):
        yield min(G[u][v].values(), key=lambda d: d[weight])


def finde_route(G, orig, dest, weight):
    """Gewichteter kürzester Pfad. Rückgabe: (knotenliste, laenge_m, sonnenanteil_mittel)."""
    nodes = nx.shortest_path(G, orig, dest, weight=weight)
    kanten = list(_route_kanten(G, nodes, weight))
    laenge = sum(k["laenge"] for k in kanten)
    son = sum(k["sonnenanteil"] * k["laenge"] for k in kanten) / laenge if laenge else 0
    return nodes, laenge, son


def _route_linie(G, route, weight):
    """Route als LineString (metrisch) für die Karte – nutzt Kantengeometrie, wo vorhanden."""
    coords = []
    for u, v in zip(route[:-1], route[1:]):
        d = min(G[u][v].values(), key=lambda d: d[weight])
        geom = d.get("geometry")
        if geom is None:
            geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]),
                               (G.nodes[v]["x"], G.nodes[v]["y"])])
        coords.extend(list(geom.coords))
    return LineString(coords)


def _route_segmente(G, route, weight):
    """Pro Kante: (kanten-daten, LineString metrisch) – für segmentweise Einfärbung."""
    for u, v in zip(route[:-1], route[1:]):
        d = min(G[u][v].values(), key=lambda d: d[weight])
        geom = d.get("geometry")
        if geom is None:
            geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]),
                               (G.nodes[v]["x"], G.nodes[v]["y"])])
        yield d, geom


def vergleiche_routen(G, orig=None, dest=None):
    """Berechnet beide Routen (schnell + schattig), gibt den Vergleich aus."""
    if orig is None or dest is None:
        orig, dest = start_ziel_knoten(G)

    n_s, len_s, son_s = finde_route(G, orig, dest, "w_schnell")
    n_h, len_h, son_h = finde_route(G, orig, dest, "w_schattig")

    print(f"  Schnellster Weg:  {len_s:5.0f} m, {son_s*100:3.0f} % Sonne")
    print(f"  Schattigster Weg: {len_h:5.0f} m, {son_h*100:3.0f} % Sonne")
    print(f"  -> {len_h-len_s:+.0f} m Umweg für {(son_s-son_h)*100:+.0f} Prozentpunkte weniger Sonne")

    return {
        "orig": orig, "dest": dest,
        "schnell": {"nodes": n_s, "laenge": len_s, "sonne": son_s,
                    "linie": _route_linie(G, n_s, "w_schnell")},
        "schattig": {"nodes": n_h, "laenge": len_h, "sonne": son_h,
                     "linie": _route_linie(G, n_h, "w_schattig")},
    }


def karte_route(G, routen, pfad=None):
    """Zeichnet beide Routen (rot = schnellster, grün = schattigster) + Start/Ziel."""
    import folium

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "route.html")

    start_ll = _knoten_latlon(G, routen["orig"])
    ziel_ll = _knoten_latlon(G, routen["dest"])
    mitte = ((start_ll[0] + ziel_ll[0]) / 2, (start_ll[1] + ziel_ll[1]) / 2)

    m = folium.Map(location=mitte, zoom_start=16, tiles=None)
    basis_layer(m)

    def linie_latlon(linie):
        s = gpd.GeoSeries([linie], crs=CRS_METRISCH).to_crs(CRS_WGS84).iloc[0]
        return [(y, x) for x, y in s.coords]

    folium.PolyLine(linie_latlon(routen["schnell"]["linie"]), color="#d7191c", weight=5,
                    opacity=0.8, tooltip=f"Schnellster: {routen['schnell']['laenge']:.0f} m, "
                    f"{routen['schnell']['sonne']*100:.0f}% Sonne").add_to(m)
    folium.PolyLine(linie_latlon(routen["schattig"]["linie"]), color="#1a9641", weight=5,
                    opacity=0.8, tooltip=f"Schattigster: {routen['schattig']['laenge']:.0f} m, "
                    f"{routen['schattig']['sonne']*100:.0f}% Sonne").add_to(m)

    folium.Marker(start_ll, tooltip="Start",
                  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker(ziel_ll, tooltip="Ziel",
                  icon=folium.Icon(color="red", icon="stop")).add_to(m)

    # Abschaltbarer Layer: schattigste Route segmentweise nach echtem Sonnenanteil.
    # Zeigt, WO entlang der grünen Route Sonne/Schatten liegt.
    from branca.colormap import LinearColormap
    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Sonnenanteil entlang Route (0 = Schatten, 1 = Sonne)"
    fg = folium.FeatureGroup(name="Sonne entlang schattigster Route", show=False)
    for d, linie in _route_segmente(G, routen["schattig"]["nodes"], "w_schattig"):
        folium.PolyLine(linie_latlon(linie), color=cmap(d["sonnenanteil"]),
                        weight=6, opacity=0.95).add_to(fg)
    fg.add_to(m)
    cmap.add_to(m)

    folium.LayerControl().add_to(m)

    # Lauf-Parameter + Quellenangaben sichtbar auf die Karte
    gebiet = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {
        "Datum/Uhrzeit":    get_zeitpunkt().strftime("%d.%m.%Y %H:%M"),
        "Gewichtung Alpha": ALPHA_SCHATTIG,
        "Gebiet":           gebiet,
    })

    m.save(pfad)
    print(f"  Karte gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    from modules.loader import lade_geh_graph, lade_gebaeude_mit_hoehe
    from modules.schatten import berechne_schatten
    from modules.kantenbewertung import bewerte_kanten

    G = lade_geh_graph()
    gebaeude = lade_gebaeude_mit_hoehe()
    schatten = berechne_schatten(gebaeude)
    G, edges = bewerte_kanten(G, schatten)
    routen = vergleiche_routen(G)
    karte_route(G, routen)