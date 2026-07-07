# stadtschatten/modules/exposition.py
#
# Flaechige Sonnendosis (Expositionsraster).
#
# Bisher: Sonnenanteil je Fussweg-KANTE (kantenbewertung.py).
# Hier:   Sonnenanteil je FLAECHE - ein Raster ueber das Testgebiet, in jeder
#         Zelle der Anteil der Stunden, in denen sie Sonne hat (0..1).
#
# Logik bewusst identisch zur Kantenbewertung, damit das Ergebnis vergleichbar
# bleibt: pro Stunde ist eine Zelle "im Schatten", wenn ihr Mittelpunkt in einem
# Schattenpolygon liegt; ueber die Stunden gemittelt ergibt das die Sonnendosis.
# (features.rasterize brennt standardmaessig nach Zellmittelpunkt -> entspricht
#  deinem Stuetzpunkt-Ansatz bei den Kanten.)
#
# DAECHER ABZIEHEN: Gebaeude-Footprints (LoD2) werden aus dem Raster gestanzt
#   (Zellen auf Gebaeuden -> NODATA). Begruendung: auf einem Dach haelt sich
#   niemand auf, "Boden unterm Haus ist dauerschattig" ist keine sinnvolle
#   Aussage. Vegetation bleibt drin - Schatten UNTER einem Baum ist genau der
#   gute, kuehle Aufenthaltsort, den wir suchen. Kein Puffer: der schattige
#   Streifen an der Nordwand ist echter Boden, auf dem jemand geht.
#
# Das ist der Baustein, auf dem die ALKIS-Verschneidung spaeter aufsetzt:
# "Sonnendosis je Nutzungsflaeche" = Mittel der GUELTIGEN Zellen in der Flaeche
# (Daecher sind dann schon raus, kein Polygon-Verschnitt noetig).

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import rasterio
from rasterio import features
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import mapping

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, AGG_RASTER_M,
                    AGG_START_STUNDE, AGG_END_STUNDE, ZENTRUM, RADIUS_M, PLACE,
                    get_zeitpunkt_stunde, MAX_ZOOM_KARTE)
from modules.schatten import berechne_schatten
from modules.karte_info import info_box
from modules.kartenbasis import basis_layer

NODATA = -9999.0   # ausserhalb des Suchgebiets ODER auf einem Gebaeude (Dach)


def _raster_gitter(gebiet_25832, aufloesung_m):
    """Leeres Rastergitter ueber die Bounding-Box des Gebiets.
    Rueckgabe: (hoehe, breite, transform) - transform in CRS_METRISCH."""
    minx, miny, maxx, maxy = gebiet_25832.bounds
    breite = int(np.ceil((maxx - minx) / aufloesung_m))
    hoehe = int(np.ceil((maxy - miny) / aufloesung_m))
    transform = rasterio.transform.from_origin(minx, maxy, aufloesung_m, aufloesung_m)
    return hoehe, breite, transform


def sonnendosis_raster(hindernisse, gebiet_25832, stunden,
                       gebaeude=None, aufloesung_m=AGG_RASTER_M):
    """Flaechige Sonnendosis je Zelle, Daecher ausgestanzt.

    hindernisse  : Gebaeude (+ Vegetation) mit Hoehe in CRS_WGS84
                   (aus loader.lade_hindernisse) - wirft den Schatten.
    gebiet_25832 : Suchgebiet als shapely-Geometrie in CRS_METRISCH
                   (aus loader._analyse_gebiet_25832).
    stunden      : iterierbar mit ganzen Stunden, z.B. range(11, 19).
    gebaeude     : NUR die Gebaeude-Footprints (aus loader.lade_gebaeude_mit_hoehe),
                   zum Ausstanzen der Daecher. None -> nicht ausstanzen.
    aufloesung_m : Zellgroesse in Metern.

    Rueckgabe: (dosis, transform)
      dosis     : 2D float32, je Zelle Sonnenanteil 0..1; ausserhalb Gebiet
                  ODER auf einem Gebaeude NODATA.
      transform : rasterio-Affine (CRS_METRISCH) - fuer GeoTIFF und Zonal-Stats.
    """
    stunden = list(stunden)
    if not stunden:
        raise ValueError(
            "Leeres Zeitfenster: AGG_END_STUNDE < AGG_START_STUNDE in config.py? "
            "Ohne Stunden gibt es nichts zu mitteln."
        )

    hoehe, breite, transform = _raster_gitter(gebiet_25832, aufloesung_m)
    form = (hoehe, breite)

    # Suchgebiet als Maske (nur diese Zellen zaehlen)
    gebiet_maske = features.rasterize(
        [(mapping(gebiet_25832), 1)], out_shape=form, transform=transform, fill=0
    ).astype(bool)

    sonne_summe = np.zeros(form, dtype=np.int32)   # je Zelle: in wie vielen Stunden Sonne

    for stunde in stunden:
        zeitpunkt = get_zeitpunkt_stunde(stunde)
        print(f"  Stunde {stunde:02d}:00 ...")
        schatten = berechne_schatten(hindernisse, zeitpunkt)   # CRS_METRISCH

        schatten_maske = features.rasterize(
            ((geom, 1) for geom in schatten.geometry),
            out_shape=form, transform=transform, fill=0
        ).astype(bool)

        sonne = gebiet_maske & (~schatten_maske)
        sonne_summe += sonne.astype(np.int32)

    dosis = np.full(form, NODATA, dtype=np.float32)
    dosis[gebiet_maske] = sonne_summe[gebiet_maske] / len(stunden)

    # Daecher ausstanzen: Gebaeude-Footprints -> NODATA (nur Gebaeude, keine Vegetation)
    if gebaeude is not None and len(gebaeude):
        geb_25832 = gebaeude.to_crs(CRS_METRISCH)
        geb_maske = features.rasterize(
            ((g, 1) for g in geb_25832.geometry),
            out_shape=form, transform=transform, fill=0
        ).astype(bool)
        entfernt = int((geb_maske & (dosis != NODATA)).sum())
        dosis[geb_maske] = NODATA
        print(f"  Daecher abgezogen: {entfernt} Zellen auf Gebaeuden entfernt.")

    gueltig = dosis[dosis != NODATA]
    print(f"  Raster {breite}x{hoehe} @ {aufloesung_m:.0f} m, "
          f"{len(stunden)} Stunden ({stunden[0]:02d}-{stunden[-1]:02d} Uhr).")
    print(f"  Sonnendosis (ohne Daecher): Mittel {gueltig.mean():.2f} "
          f"({(1-gueltig.mean())*100:.0f} % beschattet), "
          f"Median {np.median(gueltig):.2f}.")
    return dosis, transform


def schreibe_geotiff(dosis, transform, pfad=None):
    """Sonnendosis-Raster als GeoTIFF (EPSG:25832) - falls du es spaeter doch
    in einem GIS brauchst."""
    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "sonnendosis.tif")

    hoehe, breite = dosis.shape
    with rasterio.open(
        pfad, "w", driver="GTiff", height=hoehe, width=breite, count=1,
        dtype="float32", crs=f"EPSG:{CRS_METRISCH}", transform=transform,
        nodata=NODATA,
    ) as dst:
        dst.write(dosis, 1)
    print(f"  GeoTIFF gespeichert: {pfad}")
    return pfad


# ----------------------------------------------------------------------
# Karte (folium) - dein Pruef-Werkzeug, wie schatten_check.html
# ----------------------------------------------------------------------

def _dosis_nach_wgs84(dosis, transform):
    """Raster von CRS_METRISCH nach WGS84 umprojizieren (fuer folium-Overlay).
    Rueckgabe: (dosis_wgs, (west, sued, ost, nord)). Nearest, damit 0..1 und
    NODATA nicht verschliffen werden."""
    hoehe, breite = dosis.shape
    src = f"EPSG:{CRS_METRISCH}"
    dst = f"EPSG:{CRS_WGS84}"
    links, unten, rechts, oben = rasterio.transform.array_bounds(hoehe, breite, transform)
    dst_transform, dw, dh = calculate_default_transform(
        src, dst, breite, hoehe, links, unten, rechts, oben
    )
    out = np.full((dh, dw), NODATA, dtype=np.float32)
    reproject(
        dosis, out, src_transform=transform, src_crs=src,
        dst_transform=dst_transform, dst_crs=dst,
        src_nodata=NODATA, dst_nodata=NODATA, resampling=Resampling.nearest,
    )
    west, sued, ost, nord = rasterio.transform.array_bounds(dh, dw, dst_transform)
    return out, (west, sued, ost, nord)


def _dosis_rgba(dosis_wgs):
    """Sonnendosis 0..1 -> RGBA-Bild. Gleiche Skala wie die Kantenkarte:
    gruen = schattig (0), gelb = mittel, rot = sonnig (1). NODATA = transparent
    (also auch die ausgestanzten Daecher -> Gebaeude erscheinen durchsichtig)."""
    valid = dosis_wgs != NODATA
    v = np.clip(dosis_wgs, 0.0, 1.0)
    stops = [0.0, 0.5, 1.0]
    R = [26, 255, 215]; G = [150, 255, 25]; B = [65, 191, 28]
    img = np.zeros(dosis_wgs.shape + (4,), dtype=np.uint8)
    img[..., 0] = np.interp(v, stops, R)
    img[..., 1] = np.interp(v, stops, G)
    img[..., 2] = np.interp(v, stops, B)
    img[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return img


def karte_dosis(dosis, transform, pfad=None, zeit_label=None):
    """Zeichnet das Sonnendosis-Raster halbtransparent ueber die Karte.

    Frueher zusaetzlich mit Esri-World-Imagery-Luftbild als Validierungs-
    Check (Muster gegen das Orthofoto pruefen). Der Esri-Layer ist aus
    Lizenzgruenden entfernt (siehe ablauf.md) und NICHT ersetzt - der
    visuelle Foto-Abgleich faellt bis auf Weiteres weg. Ausstehend: Ersatz
    durch das offene LGL-ATKIS-Orthophoto (WMS/WMTS, Datenlizenz
    Deutschland - Namensnennung 2.0, ausdruecklich auch kommerziell nutzbar),
    sobald die konkrete Dienst-URL aus opengeodata.lgl-bw.de vorliegt.
    Ausgestanzte Gebaeude erscheinen weiterhin transparent."""
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "sonnendosis.html")

    dosis_wgs, (west, sued, ost, nord) = _dosis_nach_wgs84(dosis, transform)
    img = _dosis_rgba(dosis_wgs)

    m = folium.Map(location=[(sued + nord) / 2, (west + ost) / 2],
                   zoom_start=17, tiles=None, max_zoom=MAX_ZOOM_KARTE)
    basis_layer(m, max_zoom=MAX_ZOOM_KARTE)

    folium.raster_layers.ImageOverlay(
        image=img, bounds=[[sued, west], [nord, ost]],
        opacity=0.6, name="Sonnendosis",
    ).add_to(m)

    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Sonnendosis (0 = ganztags schattig, 1 = ganztags sonnig)"
    cmap.add_to(m)
    folium.LayerControl().add_to(m)

    if zeit_label is None:
        zeit_label = f"{AGG_START_STUNDE:02d}-{AGG_END_STUNDE:02d} Uhr (Tagesmittel)"
    gebiet = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {"Zeitfenster": zeit_label, "Gebiet": gebiet})

    m.save(pfad)
    print(f"  Karte gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    from modules.loader import (lade_hindernisse, lade_gebaeude_mit_hoehe,
                                _analyse_gebiet_25832)

    hindernisse = lade_hindernisse()          # Gebaeude + Vegetation -> Schatten
    gebaeude = lade_gebaeude_mit_hoehe()       # nur Gebaeude -> Daecher ausstanzen
    gebiet = _analyse_gebiet_25832()
    stunden = range(AGG_START_STUNDE, AGG_END_STUNDE + 1)

    dosis, transform = sonnendosis_raster(hindernisse, gebiet, stunden, gebaeude=gebaeude)
    schreibe_geotiff(dosis, transform) 
    karte_dosis(dosis, transform)