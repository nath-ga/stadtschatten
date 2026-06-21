# stadtschatten/modules/vegetation.py
#
# Baumschatten-Quelle: liest amtliche nDOM1-Kacheln (LGL BW, 1 m Raster,
# normalisiertes Oberflaechenmodell = Hoehe ueber Boden) und liefert
# Vegetation als Polygone-mit-Hoehe -> fertig fuer pybdshadow, genau wie
# die Gebaeude.
#
# Warum ueberhaupt Maskierung (an echten Kacheln verifiziert):
#   Das nDOM kennt nur Hoehe, nicht "Baum" vs. "Haus". ~37 % der Flaeche im
#   Testgebiet liegt ueber 3 m - darin stecken Gebaeude UND Baeume. Die
#   Gebaeude kommen aber schon aus LoD2 in die Schattenrechnung. Also die
#   LoD2-Footprints aus dem nDOM herausmaskieren -> uebrig bleibt Vegetation.
#   Ohne das wuerde jedes Gebaeude DOPPELT Schatten werfen.
#
# Drei Planer-Schalter (in config.py, an echten Daten kalibriert):
#   VEG_MIN_HOEHE     ab welcher Hoehe zaehlt etwas als schattenwerfend (3 m)
#   GEB_PUFFER_M      Gebaeude-Footprints aufpuffern, damit Wand-Pixel an der
#                     Hauskante nicht als Vegetation durchrutschen (1 m)
#   VEG_MIN_FLAECHE_M2 Mindestflaeche je Polygon gegen Pixel-Kruemel (4 m2)
#
# Hoehe je Baumpolygon = MEDIAN der nDOM-Pixel darin ("typische Kronenhoehe").
#   Robust gegen Ausreisserpixel, bewusst konservativ (der hoechste Punkt der
#   Krone wuerfe minimal laengeren Schatten).
#
# EHRLICHER MODELL-VORBEHALT (gehoert in die README):
#   Ein Baum wird wie ein Gebaeude als MASSIVER Block extrudiert. Real ist eine
#   Krone poroes - Licht faellt durch. Der Baumschatten ist damit eine
#   OBERGRENZE, kein exakter Wert. Fuer eine "hier ist Schatten"-Karte
#   vertretbar und klar besser als gar keine Baeume.
#
# Datenquelle: LGL, www.lgl-bw.de  (Datenlizenz Deutschland - Namensnennung 2.0)

import os
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.merge import merge
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape, box, mapping
from shapely.ops import unary_union

from config import (CRS_METRISCH, CRS_WGS84, DATA_DIR,
                    NDOM_KACHEL_UNTERORDNER, VEG_MIN_HOEHE, GEB_PUFFER_M,
                    VEG_MIN_FLAECHE_M2)

# nDOM Pflicht? True -> stoppt laut, wenn Kacheln fehlen oder das Gebiet nicht
# abdecken (analog LGL_ERFORDERLICH). False -> Vegetation wird uebersprungen.
NDOM_ERFORDERLICH = True

NDOM_MUSTER = "ndom1_*.tif"      # Fallback weiter unten auf "*.tif"
QUELLENVERMERK = "Datenquelle: LGL, www.lgl-bw.de"


# ----------------------------------------------------------------------
# Kacheln finden und zu einem Mosaik fuegen
# ----------------------------------------------------------------------

def _finde_kacheln(ordner):
    pfade = sorted(glob.glob(os.path.join(ordner, NDOM_MUSTER)))
    if not pfade:
        pfade = sorted(glob.glob(os.path.join(ordner, "*.tif")))
    return pfade


def _lade_mosaik(pfade):
    """Alle Kacheln zu einem Raster fuegen. Rueckgabe: band, transform, nodata,
    bounds-Liste (je Kachel, fuer die Abdeckungspruefung)."""
    srcs = [rasterio.open(p) for p in pfade]
    mosaic, transform = merge(srcs)
    nodata = srcs[0].nodata
    bounds = [tuple(s.bounds) for s in srcs]
    for s in srcs:
        s.close()
    return mosaic[0], transform, nodata, bounds


def _abdeckung_pruefen(bounds, gebiet_25832, ordner):
    """Stoppt laut, wenn die Kacheln das Suchgebiet nicht voll abdecken.
    nDOM1-Kacheln sind lueckenlose Vollraster -> Kachel-Bounding-Boxen = Abdeckung."""
    kachel_union = unary_union([box(*b) for b in bounds])
    rest = gebiet_25832.difference(kachel_union)
    if rest.area > 1.0 and NDOM_ERFORDERLICH:
        fehl = rest.area
        raise ValueError(
            f"\nnDOM deckt das Suchgebiet nicht voll ab: {fehl:.0f} m2 ohne Kachel.\n"
            f"  Ordner: {ordner}\n"
            f"  -> Fehlende nDOM1-Kacheln nachladen (opengeodata.lgl-bw.de),\n"
            f"     oder NDOM_ERFORDERLICH=False setzen (Vegetation am Rand fehlt dann bewusst)."
        )


# ----------------------------------------------------------------------
# Kernlogik: nDOM -> Vegetationspolygone (pur, testbar)
# ----------------------------------------------------------------------

def ndom_zu_vegetation(band, transform, nodata, gebiet_25832, gebaeude_25832,
                       min_hoehe=VEG_MIN_HOEHE, geb_puffer=GEB_PUFFER_M,
                       min_flaeche=VEG_MIN_FLAECHE_M2):
    """nDOM-Raster -> GeoDataFrame[geometry, height] in CRS_METRISCH.

    band         : nDOM-Hoehen (2D-Array, ueber Boden)
    transform    : rasterio-Affine des Mosaiks
    nodata       : nodata-Wert des nDOM
    gebiet_25832 : Suchgebiet als shapely-Geometrie (Kreis oder Ortsumriss)
    gebaeude_25832 : Gebaeude-Footprints (GeoDataFrame, CRS_METRISCH) zum Maskieren

    Reihenfolge (wichtig): erst Gebaeude maskieren, dann schwellen,
    dann Komponenten bilden, dann Flaechenfilter.
    """
    # Suchgebiet als Rastermaske
    gebiet_maske = features.rasterize(
        [(mapping(gebiet_25832), 1)], out_shape=band.shape,
        transform=transform, fill=0
    ).astype(bool)

    # Gebaeude (gepuffert) als Rastermaske -> diese Pixel abschalten
    if gebaeude_25832 is not None and len(gebaeude_25832):
        formen = [(mapping(g.buffer(geb_puffer)), 1) for g in gebaeude_25832.geometry]
        geb_maske = features.rasterize(
            formen, out_shape=band.shape, transform=transform, fill=0
        ).astype(bool)
    else:
        geb_maske = np.zeros(band.shape, dtype=bool)

    # Vegetation: hoch genug, gueltig, im Gebiet, NICHT Gebaeude
    veg = (band >= min_hoehe) & (band != nodata) & gebiet_maske & (~geb_maske)

    labels, nlab = ndimage.label(veg)
    if nlab == 0:
        return gpd.GeoDataFrame({"height": []}, geometry=[], crs=CRS_METRISCH)

    # Hoehe je Komponente = Median der nDOM-Pixel darin
    med = ndimage.median(band, labels, index=np.arange(1, nlab + 1))

    polys, hoehen = [], []
    for geom, lab in features.shapes(labels.astype(np.int32), mask=veg, transform=transform):
        p = shape(geom)
        if p.area >= min_flaeche:
            polys.append(p)
            hoehen.append(float(med[int(lab) - 1]))

    return gpd.GeoDataFrame({"height": hoehen}, geometry=polys, crs=CRS_METRISCH)


# ----------------------------------------------------------------------
# Loader-Wrapper: liest Kacheln aus config, prueft Abdeckung, gibt WGS84 zurueck
# ----------------------------------------------------------------------

def lade_vegetation(gebaeude, gebiet_25832, ordner=None):
    """Vegetation als Polygone-mit-Hoehe, fertig fuer pybdshadow.

    gebaeude     : Gebaeude-Footprints (GeoDataFrame, beliebiges CRS mit height)
                   -> werden zum Maskieren genutzt.
    gebiet_25832 : Suchgebiet als shapely-Geometrie in CRS_METRISCH.

    Rueckgabe : GeoDataFrame[geometry, height] in CRS_WGS84 (wie die Gebaeude),
                bereit zum concat mit den Gebaeuden vor berechne_schatten.
    """
    if ordner is None:
        ordner = os.path.join(DATA_DIR, NDOM_KACHEL_UNTERORDNER)

    pfade = _finde_kacheln(ordner)
    if not pfade:
        if NDOM_ERFORDERLICH:
            raise FileNotFoundError(
                f"\nKeine nDOM-Kacheln in {ordner} (Muster {NDOM_MUSTER} oder *.tif).\n"
                f"  -> nDOM1-Kacheln dort ablegen oder NDOM_ERFORDERLICH=False setzen."
            )
        print("Keine nDOM-Kacheln - Vegetation wird uebersprungen.")
        return gpd.GeoDataFrame({"height": []}, geometry=[], crs=CRS_WGS84)

    band, transform, nodata, bounds = _lade_mosaik(pfade)
    _abdeckung_pruefen(bounds, gebiet_25832, ordner)

    geb_25832 = None
    if gebaeude is not None and len(gebaeude):
        geb_25832 = gebaeude.to_crs(CRS_METRISCH)

    veg = ndom_zu_vegetation(band, transform, nodata, gebiet_25832, geb_25832)

    print(f"Vegetation aus nDOM: {len(veg)} Polygone "
          f"(>= {VEG_MIN_HOEHE:.0f} m, >= {VEG_MIN_FLAECHE_M2:.0f} m2), "
          f"Hoehe median {veg['height'].median():.1f} m." if len(veg)
          else "Vegetation aus nDOM: 0 Polygone.")
    print(f"  {QUELLENVERMERK}")
    return veg.to_crs(CRS_WGS84).reset_index(drop=True)


if __name__ == "__main__":
    # Direkttest braucht ein Suchgebiet + Gebaeude aus dem Loader.
    from modules.loader import lade_gebaeude_mit_hoehe, _analyse_gebiet_25832
    gebiet = _analyse_gebiet_25832()
    gebaeude = lade_gebaeude_mit_hoehe()
    veg = lade_vegetation(gebaeude, gebiet)
    print(f"{len(veg)} Vegetationspolygone. CRS {veg.crs}.")