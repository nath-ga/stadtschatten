# stadtschatten/modules/lgl_lod2.py
#
# Liest amtliche LoD2-Gebaeudemodelle des LGL Baden-Wuerttemberg
# (CityGML 1.0, AdV-Profil) und liefert pro Gebaeude einen 2D-Footprint
# plus Hoehe -> fertig fuer pybdshadow.
#
# Warum eine eigene kleine Funktion statt einer fertigen Bibliothek
# (an echten LGL-Kacheln geprueft):
#   - GDAL/pyogrio liest die Datei zwar, gibt die Geometrie aber als
#     MultiLineString Z (3D-Kanten des Solids) zurueck, NICHT als Footprint.
#   - Gepflegte Python-Parser zielen auf CityGML 3.0/2.0; die LGL-Kacheln
#     sind das aeltere 1.0-Profil.
#   - citygml-tools/CityJSON braucht eine Java-Laufzeitumgebung.
# Fuer den einen Zweck "AdV-LoD2 1.0 -> Footprint + Hoehe" ist Direktparsen
# robuster und ohne Zusatzabhaengigkeit ausser shapely/geopandas.
#
# Hoehenlogik (an echten Kacheln verifiziert: 100 % Abdeckung):
#   measuredHeight am Gebaeude  ->  sonst max(measuredHeight der BuildingParts).
#   Ein Fuenftel der Gebaeude traegt die Hoehe NUR auf den Teilen - wer nur die
#   Gebaeude-Ebene liest, verliert diese und haelt LoD2 faelschlich fuer lueckig.
# Footprint: Vereinigung aller GroundSurface-Polygone (inkl. der Teile),
#   z-Koordinate verworfen.
#
# Hinweis measuredHeight: das ist die Hoehe bis zum hoechsten Punkt (Firsthoehe).
#   Flache Extrusion bis dahin ueberschaetzt den Schatten bei Steildaechern leicht.
#
# Datenquelle: LGL, www.lgl-bw.de  (Datenlizenz Deutschland - Namensnennung 2.0)
#   -> Dieser Vermerk muss jetzt in README UND in jede Kartenausgabe.

import os
import glob
import xml.etree.ElementTree as ET

import geopandas as gpd
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

CRS_LGL = "EPSG:25832"                       # ETRS89/UTM32 - native Lage der Kacheln
QUELLENVERMERK = "Datenquelle: LGL, www.lgl-bw.de"

_BLDG = "http://www.opengis.net/citygml/building/1.0"
_GML = "http://www.opengis.net/gml"
_B = "{%s}Building" % _BLDG
_BP = "{%s}BuildingPart" % _BLDG
_MH = "{%s}measuredHeight" % _BLDG
_GS = "{%s}GroundSurface" % _BLDG
_POLY = "{%s}Polygon" % _GML
_EXT = "{%s}exterior/{%s}LinearRing/{%s}posList" % (_GML, _GML, _GML)
_INT = "{%s}interior/{%s}LinearRing/{%s}posList" % (_GML, _GML, _GML)


def _ring(text):
    """posList ('x y z x y z ...') -> Liste von (x, y); Hoehe z wird verworfen."""
    v = text.split()
    return [(float(v[i]), float(v[i + 1])) for i in range(0, len(v), 3)]


def _footprint(bldg):
    """Vereinigung aller GroundSurface-Polygone eines Gebaeudes (inkl. Teile)."""
    polys = []
    for gs in bldg.iter(_GS):
        for poly in gs.iter(_POLY):
            e = poly.find(_EXT)
            if e is None or not e.text:
                continue
            holes = [_ring(p.text) for p in poly.findall(_INT) if p.text]
            try:
                pg = Polygon(_ring(e.text), holes)
                if not pg.is_valid:
                    pg = pg.buffer(0)        # repariert selbstschneidende Ringe
                if pg.area > 0:
                    polys.append(pg)
            except Exception:
                pass
    if not polys:
        return None
    return unary_union(polys)


def _hoehe(bldg, min_hoehe):
    """measuredHeight am Gebaeude, sonst groesste der BuildingPart-Hoehen."""
    mh = bldg.find(_MH)
    if mh is not None and mh.text:
        try:
            h = float(mh.text)
            if h > min_hoehe:
                return h
        except ValueError:
            pass
    teil = []
    for part in bldg.iter(_BP):
        p = part.find(_MH)
        if p is not None and p.text:
            try:
                t = float(p.text)
                if t > min_hoehe:
                    teil.append(t)
            except ValueError:
                pass
    return max(teil) if teil else None


def lade_lgl_lod2(pfad, min_hoehe=0.0, explode=True):
    """
    Eine LoD2-CityGML-Kachel -> GeoDataFrame mit Spalten [geometry, height].

    CRS = EPSG:25832 (nativ, kein Umprojizieren). Speicherschonend per iterparse,
    vertraegt auch die grossen Kacheln (40+ MB).

    min_hoehe : Hoehen <= diesem Wert gelten als ungueltig (die Metadatei warnt
                vor vereinzelten 0.0-Werten aus manueller Nachbearbeitung).
    explode   : True zerlegt mehrteilige Gebaeude in Einzelpolygone (jeweils
                gleiche Hoehe) - sicherer fuer pybdshadow.
    """
    geoms, hoehen = [], []
    for _, elem in ET.iterparse(pfad, events=("end",)):
        if elem.tag == _B:
            g = _footprint(elem)
            h = _hoehe(elem, min_hoehe)
            if g is not None and h is not None:
                geoms.append(g)
                hoehen.append(h)
            elem.clear()

    gdf = gpd.GeoDataFrame({"height": hoehen}, geometry=geoms, crs=CRS_LGL)
    if explode and len(gdf):
        gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    return gdf


def lade_lgl_lod2_ordner(ordner, muster="LoD2_*.gml", **kw):
    """Alle Kacheln in einem Ordner laden und zu einem GeoDataFrame fuegen."""
    import pandas as pd
    pfade = sorted(glob.glob(os.path.join(ordner, muster)))
    if not pfade:
        raise FileNotFoundError(f"Keine Kacheln unter {ordner}/{muster}")
    teile = [lade_lgl_lod2(p, **kw) for p in pfade]
    return gpd.GeoDataFrame(pd.concat(teile, ignore_index=True), crs=CRS_LGL)


_ENVELOPE = "{%s}Envelope" % _GML
_LOWER = "{%s}lowerCorner" % _GML
_UPPER = "{%s}upperCorner" % _GML


def _envelope(pfad):
    """Liest NUR das umschliessende Rechteck (gml:boundedBy/Envelope) einer
    Kachel - die Flaeche, die die Kachel tatsaechlich ABDECKT, unabhaengig
    davon, ob dort zufaellig Gebaeude stehen. Fuer Abdeckungspruefungen:
    ein Vergleich gegen die Gebaeude-Flaeche allein ist dafuer UNGEEIGNET,
    weil die meiste Landflaeche unbebaut ist (Strassen, Gaerten, Felder) -
    das wuerde immer eine grosse, aber bedeutungslose Luecke zeigen, egal
    wie vollstaendig die Kacheln tatsaechlich sind."""
    for _, elem in ET.iterparse(pfad, events=("end",)):
        if elem.tag == _ENVELOPE:
            lower = [float(v) for v in elem.find(_LOWER).text.split()]
            upper = [float(v) for v in elem.find(_UPPER).text.split()]
            return box(lower[0], lower[1], upper[0], upper[1])
    return None


def lade_lgl_lod2_abdeckung(ordner, muster="LoD2_*.gml"):
    """Tatsaechliche Flaechenabdeckung aller Kacheln in einem Ordner - die
    Vereinigung der Kachel-ENVELOPES (nicht der Gebaeude). Fuer
    Abdeckungspruefungen (siehe loader._lade_gebaeude_lgl). None, wenn
    kein Envelope lesbar war (z.B. andere GML-Struktur als erwartet -
    dann lieber laut nichts zurueckgeben als eine falsche Flaeche)."""
    pfade = sorted(glob.glob(os.path.join(ordner, muster)))
    envelopes = [e for e in (_envelope(p) for p in pfade) if e is not None]
    if not envelopes:
        return None
    return gpd.GeoSeries(envelopes, crs=CRS_LGL).union_all()


if __name__ == "__main__":
    import sys
    ziel = sys.argv[1] if len(sys.argv) > 1 else "."
    g = lade_lgl_lod2_ordner(ziel) if os.path.isdir(ziel) else lade_lgl_lod2(ziel)
    print(f"{len(g)} Gebaeude(teile). CRS {g.crs}.")
    print(f"  Hoehe   median {g['height'].median():.1f} m  (min {g['height'].min():.1f} / max {g['height'].max():.1f})")
    print(f"  Flaeche median {g.geometry.area.median():.1f} m2")
    print(f"  {QUELLENVERMERK}")