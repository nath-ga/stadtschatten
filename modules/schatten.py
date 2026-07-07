# stadtschatten/modules/schatten.py
#
# Schatten-Wrapper um pybdshadow.
# Eingabe : Gebäude mit Höhe (CRS_WGS84, aus loader.lade_gebaeude_mit_hoehe)
# Ausgabe : Schattenpolygone in CRS_METRISCH (bereit für die Kantenbewertung)
#
# Drei pybdshadow-Stolpersteine sind hier gekapselt:
#   1. Gebäude müssen durch bd_preprocess() (setzt building_id).
#   2. Eingabe in WGS84 (lon/lat).
#   3. Der Schatten-Output hat KEIN CRS -> set_crs(WGS84) vor Reprojektion.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd
import pybdshadow

from config import CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE, get_zeitpunkt
from modules.karte_info import info_box
from modules.kartenbasis import basis_layer


def berechne_schatten(gebaeude, zeitpunkt=None):
    """
    Berechnet Gebäudeschatten für einen Zeitpunkt.

    gebaeude : GeoDataFrame in CRS_WGS84 mit Spalte 'height'
    zeitpunkt: tz-bewusster pandas Timestamp; None -> aus config.get_zeitpunkt()

    Rückgabe : GeoDataFrame der Schattenpolygone in CRS_METRISCH
    """
    if zeitpunkt is None:
        zeitpunkt = get_zeitpunkt()

    if gebaeude.crs is None or gebaeude.crs.to_epsg() != CRS_WGS84:
        gebaeude = gebaeude.to_crs(CRS_WGS84)

    print(f"Berechne Schatten für {zeitpunkt} ...")
    b = pybdshadow.bd_preprocess(gebaeude)
    schatten = pybdshadow.bdshadow_sunlight(b, zeitpunkt)

    if schatten is None or len(schatten) == 0:
        # Passiert z.B. wenn die Sonne unter dem Horizont steht (Nacht).
        raise ValueError(
            "Keine Schatten berechnet. Steht die Sonne zu diesem Zeitpunkt über "
            "dem Horizont? Prüfe DATUM/UHRZEIT in config.py."
        )

    # Stolperstein 3: Output hat kein CRS -> erst setzen, dann projizieren.
    schatten = schatten.set_crs(CRS_WGS84, allow_override=True).to_crs(CRS_METRISCH)
    print(f"  {len(schatten)} Schattenpolygone, "
          f"Gesamtfläche {schatten.geometry.area.sum():.0f} m².")
    return schatten


def schatten_union(schatten):
    """Vereinigt alle Schattenpolygone zu einer Geometrie (für schnelle 'liegt im Schatten?'-Tests)."""
    return schatten.geometry.union_all()


def karte_schatten(gebaeude, schatten, pfad=None):
    """
    Zeichnet Gebäude (grau) und Schatten (blau, halbtransparent) auf eine Folium-Karte.
    Das ist der Validierungs-Check: Schatten gegen die Karte prüfen.
    """
    import folium

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "schatten_check.html")

    # Für die Anzeige alles nach WGS84.
    geb_wgs = gebaeude.to_crs(CRS_WGS84)
    sch_wgs = schatten.to_crs(CRS_WGS84)

    mitte = geb_wgs.geometry.union_all().centroid
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=17, tiles=None)
    basis_layer(m)

    folium.GeoJson(
        sch_wgs, name="Schatten",
        style_function=lambda f: {"fillColor": "#2b3a67", "color": "#2b3a67",
                                  "weight": 0, "fillOpacity": 0.45},
    ).add_to(m)
    folium.GeoJson(
        geb_wgs, name="Gebäude",
        style_function=lambda f: {"fillColor": "#888", "color": "#555",
                                  "weight": 1, "fillOpacity": 0.6},
    ).add_to(m)

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
    from modules.loader import lade_gebaeude_mit_hoehe
    gebaeude = lade_gebaeude_mit_hoehe()
    schatten = berechne_schatten(gebaeude)
    karte_schatten(gebaeude, schatten)