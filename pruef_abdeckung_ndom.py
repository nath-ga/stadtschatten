# pruef_abdeckung_ndom.py
#
# Gleiche Idee wie pruef_abdeckung.py, aber fuer die nDOM-Kacheln
# (Vegetation/Baumschatten) statt LGL-LoD2 (Gebaeude). Prueft die
# tatsaechliche Rasterausdehnung jeder Kachel (rasterio bounds), nicht
# irgendeine abgeleitete Groesse daraus - analog zum Envelope-Fix bei den
# Gebaeude-Kacheln. Noch nicht in vegetation.py eingebaut, weil mir diese
# Datei nicht vorliegt - eigenstaendiger Check, bis das nachgeholt ist.
#
# Aufruf aus dem Projekt-Root (gleicher Ordner wie config.py):
#   python pruef_abdeckung_ndom.py

import glob
import os

import geopandas as gpd
import rasterio
from shapely.geometry import Point, box

from config import ZENTRUM, RADIUS_M, CRS_WGS84, CRS_METRISCH, DATA_DIR, NDOM_KACHEL_UNTERORDNER

NDOM_DIR = os.path.join(DATA_DIR, NDOM_KACHEL_UNTERORDNER)
pfade = sorted(glob.glob(os.path.join(NDOM_DIR, "ndom1_*.tif")))
print(f"{len(pfade)} nDOM-Kacheln gefunden in {NDOM_DIR}")

if not pfade:
    print("Keine nDOM-Kacheln gefunden - Baumschatten sind fuer dieses Gebiet nicht "
          "berechenbar (falls VEG_AKTIV=True, sollte das an anderer Stelle schon "
          "aufgefallen sein).")
else:
    envelopes = []
    for p in pfade:
        with rasterio.open(p) as src:
            b = src.bounds
            envelopes.append(box(b.left, b.bottom, b.right, b.top))

    abdeckung = gpd.GeoSeries(envelopes, crs=CRS_METRISCH).union_all()
    zentrum_metrisch = gpd.GeoSeries(
        [Point(ZENTRUM[1], ZENTRUM[0])], crs=CRS_WGS84
    ).to_crs(CRS_METRISCH).iloc[0]

    for radius in sorted({800, RADIUS_M}):
        kreis = zentrum_metrisch.buffer(radius)
        luecke = kreis.difference(abdeckung)
        anteil = 100 * luecke.area / kreis.area if kreis.area else 0
        print(f"nDOM Radius {radius} m: {luecke.area:.0f} m² unabgedeckt von "
              f"{kreis.area:.0f} m² gesamt ({anteil:.1f} %)")