# pruef_abdeckung.py
#
# Einmaliges Diagnoseskript, KEIN Teil der Pipeline: prueft, ob die
# vorhandenen LGL-LoD2-Kacheln einen Kreis um ZENTRUM VOLLSTAENDIG abdecken -
# ueber die Kachel-Envelopes (gml:Envelope), nicht ueber Gebaeude-Flaeche.
# Nutzt jetzt dieselbe Funktion (lade_lgl_lod2_abdeckung), die auch
# loader.py fuer den eingebauten Abdeckungs-Check verwendet - keine
# doppelt gepflegte Logik mehr.
#
# Aufruf aus dem Projekt-Root (gleicher Ordner wie config.py):
#   python pruef_abdeckung.py

import geopandas as gpd
from shapely.geometry import Point

from config import ZENTRUM, RADIUS_M, CRS_WGS84, CRS_METRISCH
from modules.loader import LGL_KACHEL_DIR
from modules.lgl_lod2 import lade_lgl_lod2_abdeckung

abdeckung = lade_lgl_lod2_abdeckung(LGL_KACHEL_DIR)
if abdeckung is None:
    print("ACHTUNG: keine lesbare Envelope in den Kacheln gefunden - "
          "Ergebnis unten nicht aussagekraeftig, gml:Envelope-Struktur "
          "ggf. anders als angenommen. Nicht blind vertrauen.")
    abdeckung = gpd.GeoSeries([], crs=CRS_METRISCH).union_all()

zentrum_metrisch = gpd.GeoSeries(
    [Point(ZENTRUM[1], ZENTRUM[0])], crs=CRS_WGS84
).to_crs(CRS_METRISCH).iloc[0]

for radius in sorted({800, RADIUS_M}):
    kreis = zentrum_metrisch.buffer(radius)
    luecke = kreis.difference(abdeckung)
    anteil = 100 * luecke.area / kreis.area if kreis.area else 0
    print(f"Radius {radius} m: {luecke.area:.0f} m² unabgedeckt von "
          f"{kreis.area:.0f} m² gesamt ({anteil:.1f} %)")

# Die eigentlich entscheidende Frage: liegt IRGENDEIN tatsaechlicher
# Aufenthaltsort (der schon in der Rangliste war) in dieser Luecke? Die
# Prozentzahl allein sagt nichts darueber, ob deine bisherigen Ergebnisse
# betroffen sind - das hier schon.
kreis_800 = zentrum_metrisch.buffer(800)
luecke_800 = kreis_800.difference(abdeckung)

if luecke_800.area > 0:
    from modules.aufenthalt import lade_aufenthaltsorte
    orte = lade_aufenthaltsorte()
    orte_im_alten_kreis = orte[orte.geometry.within(kreis_800)]
    betroffen = orte_im_alten_kreis[orte_im_alten_kreis.geometry.intersects(luecke_800)]

    print(f"\n{len(orte_im_alten_kreis)} Aufenthaltsorte lagen im alten 800-m-Kreis.")
    if len(betroffen):
        print(f"DAVON {len(betroffen)} in der Datenluecke - Kontaminationsgrad je Ort "
              f"(Anteil der EIGENEN Flaeche, der in der Luecke liegt, nicht Anteil der Luecke):")
        zeilen = []
        for _, r in betroffen.iterrows():
            anteil_kontam = 100 * r.geometry.intersection(luecke_800).area / r.geometry.area
            zeilen.append((anteil_kontam, r["kategorie"], r["name"] or "(ohne Name)"))
        for anteil_kontam, kat, name in sorted(zeilen, reverse=True):
            schwere = "SCHWER" if anteil_kontam > 50 else ("mittel" if anteil_kontam > 10 else "gering")
            print(f"  {anteil_kontam:5.1f}% [{schwere:6s}]  {kat}: '{name}'")
    else:
        print("Keiner davon liegt in der Luecke - bisherige Rangliste ist trotz der "
              "Luecke unbetroffen, weil die Luecke ausserhalb der bebauten/genutzten "
              "Bereiche liegt.")

    minx, miny, maxx, maxy = luecke_800.bounds
    sw = gpd.GeoSeries([Point(minx, miny)], crs=CRS_METRISCH).to_crs(CRS_WGS84).iloc[0]
    no = gpd.GeoSeries([Point(maxx, maxy)], crs=CRS_METRISCH).to_crs(CRS_WGS84).iloc[0]
    print(f"\nFehlende Abdeckung, EPSG:25832: x {minx:.0f}..{maxx:.0f}, y {miny:.0f}..{maxy:.0f}")
    print(f"Fehlende Abdeckung, lon/lat:    {sw.x:.4f},{sw.y:.4f} bis {no.x:.4f},{no.y:.4f}")
    print("-> Mit diesen Koordinaten auf opengeodata.lgl-bw.de die fehlende(n) "
          "Kachel(n) suchen und nachladen.")
else:
    print("\n0 m² Luecke im 800-m-Kreis - vollstaendig abgedeckt.")