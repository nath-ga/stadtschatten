# stadtschatten/modules/loader.py
#
# Lädt die gemeinsame Datengrundlage:
#   - einen Fußweg-Graphen (networkx, projiziert auf CRS_METRISCH)
#   - Gebäude-Footprints mit Höhe (für pybdshadow, in CRS_WGS84)
#
# Zwei Lade-Modi (gesteuert über config.ZENTRUM):
#   - Punkt-Modus: Kreis um ZENTRUM mit RADIUS_M  (schnell, zum Entwickeln)
#   - Orts-Modus:  ganzer Ort PLACE              (wenn ZENTRUM = None)
#
# Höhenquelle: Bevorzugt werden amtliche LGL-LoD2-Höhen. Stimmt etwas an der
# LGL-Konfiguration nicht (Ordner fehlt, Mittelpunkt nicht abgedeckt), stoppt
# das Tool mit klarer Meldung – statt still auf OSM auszuweichen.

import os
import sys
import hashlib
import unicodedata

# Projektwurzel auf den Pfad, damit "from config import ..." auch beim
# direkten Ausführen (python modules/loader.py) funktioniert.
PROJEKT_WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJEKT_WURZEL)

import osmnx as ox
import geopandas as gpd
from shapely.geometry import Point

from config import CRS_METRISCH, CRS_WGS84, DATA_DIR, PLACE, ZENTRUM, RADIUS_M, LGL_KACHEL_UNTERORDNER, VEG_AKTIV

# Ordner mit den LGL-LoD2-Kacheln des aktiven Ortes: data/<AKTIVER_ORT>/
LGL_KACHEL_DIR = os.path.join(PROJEKT_WURZEL, DATA_DIR, LGL_KACHEL_UNTERORDNER)

# LGL Pflicht?  True  -> stoppt laut, wenn LGL-Daten erwartet, aber nicht nutzbar
#                        sind (der Normalfall in Baden-Württemberg).
#               False -> weicht still auf OSM aus (nur für Gebiete OHNE LGL-Daten,
#                        z. B. außerhalb BW).
LGL_ERFORDERLICH = True

# LGL-Lader. Der try/except deckt beide Startarten ab: direkt
# (python modules/loader.py) und Import über run.py.
try:
    from modules.lgl_lod2 import lade_lgl_lod2_ordner, lade_lgl_lod2_abdeckung, QUELLENVERMERK
except ImportError:
    from lgl_lod2 import lade_lgl_lod2_ordner, lade_lgl_lod2_abdeckung, QUELLENVERMERK

# --- Modell-Feintuning: Fallback-Annahmen für fehlende Höhen (nur OSM-Weg) ---
GESCHOSSHOEHE_M = 3.0
HOEHE_DEFAULT_M = 6.0   # Annahme: 2 Geschosse, wenn gar nichts bekannt ist


def ort_hash(text):
    """Eindeutiger Hash für Dateibenennung. Entfernt Umlaute (geborgt aus Stadtgrün)."""
    text_ascii = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return hashlib.md5(text_ascii.encode("utf-8")).hexdigest()[:8]


def _gebiet_id():
    """
    Cache-Kennung für das aktuelle Gebiet. Punkt- und Orts-Modus bekommen
    getrennte IDs -> ihre Cache-Dateien kollidieren nicht.
    """
    if ZENTRUM:
        return ort_hash(f"point_{ZENTRUM[0]:.5f}_{ZENTRUM[1]:.5f}_r{RADIUS_M}")
    return ort_hash(PLACE)


# ----------------------------------------------------------------------
# Höhenquelle für den OSM-Weg (gekapselt – Fallback-Kette bleibt)
# ----------------------------------------------------------------------

def _parse_meter(wert):
    """Robust eine Meterzahl aus einem OSM-Tag lesen ('12', '12.5 m', '12m', '12,5')."""
    if wert is None:
        return None
    try:
        s = str(wert).strip().replace(",", ".")
        zahl = ""
        for ch in s:
            if ch.isdigit() or ch == ".":
                zahl += ch
            else:
                break
        return float(zahl) if zahl else None
    except (ValueError, TypeError):
        return None


def gebaeude_hoehe(row, default=HOEHE_DEFAULT_M, geschosshoehe=GESCHOSSHOEHE_M):
    """
    Höhe eines Gebäudes aus OSM. Fallback-Kette:
        OSM height -> OSM building:levels × Geschosshöhe -> default
    (Die amtliche LGL-Höhe kommt nicht hier rein, sondern direkt aus den
     LoD2-Kacheln – siehe _lade_gebaeude_lgl unten.)
    """
    h = _parse_meter(row.get("height"))
    if h and h > 0:
        return h

    levels = _parse_meter(row.get("building:levels"))
    if levels and levels > 0:
        return levels * geschosshoehe

    return default


# ----------------------------------------------------------------------
# Geh-Graph
# ----------------------------------------------------------------------

def lade_geh_graph():
    """Fußweg-Graph, projiziert auf CRS_METRISCH, mit Cache."""
    os.makedirs(DATA_DIR, exist_ok=True)
    pfad = os.path.join(DATA_DIR, f"graph_{_gebiet_id()}.graphml")

    if os.path.exists(pfad):
        print("Lade Geh-Graph aus Cache ...")
        G = ox.load_graphml(pfad)
    else:
        if ZENTRUM:
            print(f"Lade Geh-Graph von OSM (Punkt-Modus, {RADIUS_M} m) ...")
            G = ox.graph_from_point(ZENTRUM, dist=RADIUS_M, network_type="walk")
        else:
            print("Lade Geh-Graph von OSM (Orts-Modus) ...")
            G = ox.graph_from_place(PLACE, network_type="walk")
        ox.save_graphml(G, pfad)

    return ox.project_graph(G, to_crs=CRS_METRISCH)


# ----------------------------------------------------------------------
# Suchgebiet (für den Zuschnitt der LGL-Gebäude)
# ----------------------------------------------------------------------

def _analyse_gebiet_25832():
    """
    Das aktuelle Suchgebiet als Geometrie in CRS_METRISCH.
        Punkt-Modus: Kreis mit RADIUS_M um ZENTRUM.
        Orts-Modus:  Umriss des Ortes PLACE.
    Damit schneiden wir die LGL-Kacheln auf genau das Gebiet zu, das du
    auch sonst betrachtest.
    """
    if ZENTRUM:
        # ZENTRUM ist (lat, lon) wie bei osmnx -> Point braucht (lon, lat)
        punkt = gpd.GeoSeries([Point(ZENTRUM[1], ZENTRUM[0])], crs=CRS_WGS84)
        return punkt.to_crs(CRS_METRISCH).iloc[0].buffer(RADIUS_M)
    return ox.geocode_to_gdf(PLACE).to_crs(CRS_METRISCH).geometry.iloc[0]


# ----------------------------------------------------------------------
# Gebäude mit Höhe: erst LGL-LoD2, sonst OSM-Fallback
# ----------------------------------------------------------------------

def _lade_gebaeude_lgl():
    """
    Gebäude aus LGL-LoD2-Kacheln, zugeschnitten auf das Suchgebiet.
    Rückgabe in CRS_WGS84 mit Spalten geometry, height.

    Bei LGL_ERFORDERLICH=True wird mit klarer Meldung gestoppt, wenn der
    Kachelordner fehlt/leer ist oder die Kacheln den Mittelpunkt nicht abdecken.
    Nur bei LGL_ERFORDERLICH=False wird None zurückgegeben -> OSM-Fallback.
    """
    # Fall 1: Kachelordner fehlt
    if not os.path.isdir(LGL_KACHEL_DIR):
        if LGL_ERFORDERLICH:
            raise FileNotFoundError(
                f"\nKachelordner fehlt: {LGL_KACHEL_DIR}\n"
                f"  -> Lege die LGL-Kacheln (LoD2_*.gml) für '{LGL_KACHEL_UNTERORDNER}' dort ab,\n"
                f"     oder prüfe AKTIVER_ORT in config.py."
            )
        return None

    # Fall 2: Ordner da, aber keine LoD2_*.gml darin
    try:
        g = lade_lgl_lod2_ordner(LGL_KACHEL_DIR)        # EPSG:25832
    except FileNotFoundError:
        if LGL_ERFORDERLICH:
            raise FileNotFoundError(
                f"\nKeine LoD2_*.gml in {LGL_KACHEL_DIR}.\n"
                f"  -> Liegen die Kacheln wirklich in diesem Unterordner (nicht direkt in data/)?"
            )
        return None

    # Fall 3: Kacheln da, decken aber das Gebiet nicht (vollstaendig) ab.
    # WICHTIG: nicht nur pruefen, ob IRGENDEIN Gebaeude im Suchkreis liegt
    # (treffer.empty) - das faengt nur Totalausfall ab. Bei TEILabdeckung
    # (z.B. Kacheln nur fuer die Haelfte des Kreises vorhanden) waere
    # treffer trotzdem nicht leer, und die fehlende Haelfte wuerde still
    # als "keine Gebaeude -> voll sonnig" durchgehen - ein Datenloch, das
    # wie ein Messergebnis aussieht. Deshalb: Flaechen-Differenz gebiet
    # minus Kachel-Abdeckung, nicht nur ein Treffer-Check.
    #
    # WICHTIG #2 (Korrektur): die Abdeckung muss aus den Kachel-ENVELOPES
    # kommen (gml:Envelope, lade_lgl_lod2_abdeckung), NICHT aus der
    # Vereinigung der Gebaeude-Flaechen. Gebaeude decken nie annaehernd
    # die ganze Landflaeche ab (Strassen, Gaerten, Felder sind unbebaut) -
    # ein Vergleich dagegen wuerde IMMER eine grosse, aber bedeutungslose
    # Luecke zeigen, egal wie vollstaendig die Kacheln tatsaechlich sind.
    gebiet = _analyse_gebiet_25832()
    abdeckung = lade_lgl_lod2_abdeckung(LGL_KACHEL_DIR)
    if abdeckung is None:
        anteil_luecke = 1.0   # kein Envelope lesbar -> Abdeckung unbekannt, lieber stoppen
    else:
        luecke = gebiet.difference(abdeckung)
        anteil_luecke = luecke.area / gebiet.area if gebiet.area else 0

    treffer = g[g.intersects(gebiet)].copy()
    if treffer.empty or anteil_luecke > 0.01:   # >1% unabgedeckt = nicht mehr "vollstaendig"
        if LGL_ERFORDERLICH:
            b = g.to_crs(CRS_WGS84).total_bounds
            wo = (f"  Dein ZENTRUM (lon, lat):     {ZENTRUM[1]:.4f}, {ZENTRUM[0]:.4f}\n"
                  if ZENTRUM else f"  Ort (PLACE): {PLACE}\n")
            raise ValueError(
                f"\nDie Kacheln in {LGL_KACHEL_DIR} decken dein Gebiet nicht VOLLSTAENDIG ab "
                f"({100*anteil_luecke:.1f}% der Flaeche fehlen).\n"
                f"  Gebaeude-Bounding-Box (lon/lat): {b[0]:.4f}..{b[2]:.4f} / {b[1]:.4f}..{b[3]:.4f}\n"
                f"{wo}"
                f"  -> Fehlende Kachel(n) nachladen. Teilabdeckung wuerde sonst in der Luecke\n"
                f"     als 'keine Gebaeude -> voll sonnig' durchgehen, nicht als echtes Ergebnis."
            )
        return None

    print(f"Gebäude aus LGL-LoD2: {len(treffer)} im Suchgebiet, alle mit gemessener Höhe.")
    print(f"  {QUELLENVERMERK}")
    return treffer[["geometry", "height"]].to_crs(CRS_WGS84).reset_index(drop=True)


def lade_gebaeude_mit_hoehe():
    """
    Gebäude-Footprints mit Höhe. Rückgabe in CRS_WGS84 (pybdshadow erwartet lon/lat).
    Bevorzugt amtliche LGL-LoD2-Höhen; fällt auf OSM zurück, wo keine vorliegen.
    Spalten: geometry, height.
    """
    g = _lade_gebaeude_lgl()
    if g is not None:
        return g
    print("Keine LGL-Daten für dieses Gebiet – nutze OSM mit Höhen-Fallback.")
    return _lade_gebaeude_osm()

def lade_hindernisse():
    """Schattenwerfende Objekte: Gebäude (LoD2) + optional Vegetation (nDOM).
    Rückgabe: GeoDataFrame[geometry, height] in CRS_WGS84 – fertig für berechne_schatten."""
    import pandas as pd
    gebaeude = lade_gebaeude_mit_hoehe()
    if not VEG_AKTIV:
        return gebaeude

    from modules.vegetation import lade_vegetation
    gebiet = _analyse_gebiet_25832()
    vegetation = lade_vegetation(gebaeude, gebiet)
    if len(vegetation) == 0:
        return gebaeude

    hindernisse = gpd.GeoDataFrame(
        pd.concat([gebaeude, vegetation], ignore_index=True), crs=CRS_WGS84
    )
    print(f"Hindernisse gesamt: {len(gebaeude)} Gebäude + {len(vegetation)} Vegetation "
          f"= {len(hindernisse)}.")
    return hindernisse

def _lade_gebaeude_osm():
    """
    OSM-Weg (unverändert gegenüber v1): Footprints aus OSM, Höhe über die
    Fallback-Kette in gebaeude_hoehe(). Mit Cache und Abdeckungs-Bericht.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    pfad = os.path.join(DATA_DIR, f"gebaeude_hoehe_{_gebiet_id()}.geojson")

    if os.path.exists(pfad):
        print("Lade Gebäude mit Höhe aus Cache ...")
        return gpd.read_file(pfad)

    if ZENTRUM:
        print(f"Lade Gebäude von OSM (Punkt-Modus, {RADIUS_M} m) ...")
        g = ox.features_from_point(ZENTRUM, tags={"building": True}, dist=RADIUS_M)
    else:
        print("Lade Gebäude von OSM (Orts-Modus) ...")
        g = ox.features_from_place(PLACE, tags={"building": True})

    g = g[g.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()

    def _hoehe(row):
        return gebaeude_hoehe({
            "height": row.get("height") if "height" in g.columns else None,
            "building:levels": row.get("building:levels") if "building:levels" in g.columns else None,
        })
    g["height"] = g.apply(_hoehe, axis=1)

    g = g[["geometry", "height"]].to_crs(CRS_WGS84).reset_index(drop=True)
    g.to_file(pfad, driver="GeoJSON")

    # Höhen-Abdeckung berichten: wie viele Gebäude sind auf den Default gefallen?
    ohne = int((g["height"] == HOEHE_DEFAULT_M).sum())
    anteil = 100 * ohne / len(g) if len(g) else 0
    print(f"  {len(g)} Gebäude. Ohne OSM-Höhe (Default {HOEHE_DEFAULT_M:.0f} m): "
          f"{ohne} ({anteil:.0f} %). Median {g['height'].median():.1f} m.")
    return g


if __name__ == "__main__":
    G = lade_geh_graph()
    geb = lade_gebaeude_mit_hoehe()
    print(f"Graph: {G.number_of_nodes()} Knoten, {G.number_of_edges()} Kanten.")
    print(f"Gebäude: {len(geb)}.")