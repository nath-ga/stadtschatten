# stadtschatten/modules/nutzung.py
#
# DER KATEGORIE-WECHSEL: Sonnendosis je tatsaechlicher NUTZUNG.
#
# Bisher (exposition.py): ein Raster, das je Zelle sagt "wie sonnig ueber den
#   Tag" - aber blind dafuer, WAS dort ist. Daecher sind schon ausgestanzt.
# Hier: das Raster mit den amtlichen ALKIS-Flurstuecken verschneiden. Je
#   Flurstueck der Mittelwert der gueltigen (Freiflaechen-)Zellen, etikettiert
#   mit der tatsaechlichen Nutzung. Aus "wo ist Sonne" wird "wo ist Sonne DA,
#   WO Menschen sich aufhalten".
#
# Trennung der Rechenschritte: der teure Schatten (exposition.py) schreibt ein
#   GeoTIFF, dieses Modul liest es. So kann am Schwellwert gedreht werden, ohne
#   die Schatten neu zu rechnen.
#
# Nutzungs-Etikett: ein Flurstueck kann mehrere Nutzungen tragen (tntxt-Feld,
#   Format "Nutzungsart;Flaeche_m2", mehrere mit | verkettet). Etikettiert wird
#   mit der FLAECHENGROESSTEN (dominanten) Nutzung. Auf Parzellen-Mittel-Ebene
#   konsistent; Mischnutzung verliert dabei Nuance (bewusste Vereinfachung).
#
# Mindest-Freiflaeche (MIN_FREIFLAECHE_M2): ein vollstaendig bebautes Flurstueck
#   hat nach dem Dach-Abzug kaum gueltige Zellen. Ein Mittel ueber 0-2 Zellen
#   waere Rauschen, keine Aussage. Darunter -> "nicht bewertbar" (ehrliche
#   Leerstelle statt erfundener Zahl; zugleich faktisch die vollversiegelten
#   Flurstuecke - selbst eine planungsrelevante Klasse).
#
# Datenquelle ALKIS/LoD2/nDOM: LGL, www.lgl-bw.de (Datenlizenz Deutschland - NN 2.0)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import geopandas as gpd
import rasterio
from rasterio import features
from shapely.geometry import Point, box

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE,
                    AGG_START_STUNDE, AGG_END_STUNDE,
                    ALKIS_FLURSTUECK_PFAD, MIN_FREIFLAECHE_M2, MAX_ZOOM_KARTE)
from modules.karte_info import info_box
from modules.kartenbasis import basis_layer

NODATA = -9999.0   # muss zum Wert in exposition.py passen


# ----------------------------------------------------------------------
# Einlesen
# ----------------------------------------------------------------------

def _dominante_nutzung(tntxt):
    """Flaechengroesste Nutzung aus dem tntxt-Feld ('Art;Flaeche|Art;Flaeche...')."""
    if tntxt is None or str(tntxt) in ("nan", "None", ""):
        return "unbekannt"
    best_art, best_fl = "unbekannt", -1.0
    for seg in str(tntxt).split("|"):
        if ";" in seg:
            art, fl = seg.rsplit(";", 1)
            try:
                fl = float(fl)
            except ValueError:
                fl = 0.0
            if fl > best_fl:
                best_fl, best_art = fl, art.strip()
    return best_art


def lade_flurstuecke(pfad=None):
    """ALKIS-Flurstuecke laden, dominante Nutzung ableiten. CRS_METRISCH.
    Encoding (windows-1252) kommt aus der .cpg-Datei automatisch mit."""
    if pfad is None:
        pfad = ALKIS_FLURSTUECK_PFAD
    fl = gpd.read_file(pfad)
    if fl.crs is None or fl.crs.to_epsg() != CRS_METRISCH:
        fl = fl.to_crs(CRS_METRISCH)
    fl["nutzart"] = fl["tntxt"].apply(_dominante_nutzung)
    return fl


def lade_dosis_tif(pfad=None):
    """Sonnendosis-Raster aus dem GeoTIFF (von exposition.schreibe_geotiff).
    Rueckgabe: (dosis, transform, nodata)."""
    if pfad is None:
        pfad = os.path.join(OUTPUT_DIR, "sonnendosis.tif")
    if not os.path.exists(pfad):
        raise FileNotFoundError(
            f"\nKein Sonnendosis-Raster unter {pfad}.\n"
            f"  -> Erst exposition.py laufen lassen UND dort schreibe_geotiff(...) aufrufen."
        )
    with rasterio.open(pfad) as src:
        dosis = src.read(1)
        transform = src.transform
        nodata = src.nodata if src.nodata is not None else NODATA
    return dosis, transform, nodata


# ----------------------------------------------------------------------
# Verschneidung: Sonnendosis je Flurstueck (Zonal-Statistik)
# ----------------------------------------------------------------------

def bewerte_flurstuecke(flurstuecke, dosis, transform, nodata=NODATA,
                        min_freiflaeche_m2=MIN_FREIFLAECHE_M2):
    """Je Flurstueck: Mittel der gueltigen Zellen, Freiflaeche, Bewertbarkeit.

    Vorgehen (ein Verschnitt fuer ALLE Flurstuecke, nicht Stueck fuer Stueck):
      1. Flurstuecke in ein Label-Raster brennen (jedes eine id 1..N).
      2. Nur gueltige Zellen (dosis != nodata) zaehlen -> per bincount je id
         Summe und Anzahl -> Mittel. Schnell, kein Schleifen ueber Polygone.

    Neue Spalten:
      frei_zellen    : Anzahl gueltiger (Freiflaechen-)Zellen
      freiflaeche_m2 : frei_zellen * Zellflaeche
      sonnendosis    : Mittel 0..1 (NaN, wenn keine gueltige Zelle)
      bewertbar      : freiflaeche_m2 >= min_freiflaeche_m2
    """
    hoehe, breite = dosis.shape
    zellflaeche = abs(transform.a) * abs(transform.e)

    fl = flurstuecke.reset_index(drop=True).copy()
    lab = features.rasterize(
        ((geom, i + 1) for i, geom in enumerate(fl.geometry)),
        out_shape=(hoehe, breite), transform=transform, fill=0, dtype="int32"
    )

    valid = dosis != nodata
    N = len(fl)
    summe = np.bincount(lab[valid], weights=dosis[valid], minlength=N + 1)[1:]
    anzahl = np.bincount(lab[valid], minlength=N + 1)[1:]

    mittel = np.full(N, np.nan, dtype=float)
    nz = anzahl > 0
    mittel[nz] = summe[nz] / anzahl[nz]

    fl["frei_zellen"] = anzahl.astype(int)
    fl["freiflaeche_m2"] = anzahl * zellflaeche
    fl["sonnendosis"] = mittel
    fl["bewertbar"] = fl["freiflaeche_m2"] >= min_freiflaeche_m2

    n_b = int(fl["bewertbar"].sum())
    print(f"  {N} Flurstuecke verschnitten: {n_b} bewertbar, "
          f"{N - n_b} unter {min_freiflaeche_m2:.0f} m2 Freiflaeche (nicht bewertbar).")
    return fl


def zusammenfassung(fl_bewertet, min_n=5):
    """Strategischer Ueberblick: flaechengewichtetes Mittel je Nutzungsklasse
    (nur bewertbare Flurstuecke). Das ist die Krueger-Flughoehe -
    'welche Nutzungsart ist im Mittel wie besonnt'."""
    b = fl_bewertet[fl_bewertet["bewertbar"]]
    if b.empty:
        print("  Keine bewertbaren Flurstuecke.")
        return
    zeilen = []
    for art, d in b.groupby("nutzart"):
        if len(d) < min_n:
            continue
        mittel = np.average(d["sonnendosis"].values, weights=d["freiflaeche_m2"].values)
        zeilen.append((mittel, len(d), art))
    zeilen.sort(reverse=True)
    print(f"  Sonnendosis je Nutzung (flaechengewichtet, n>={min_n}):")
    for mittel, n, art in zeilen:
        print(f"    {mittel:.2f}  ({n})  {art}")


# ----------------------------------------------------------------------
# Karte
# ----------------------------------------------------------------------

def karte_nutzung(fl_bewertet, gebiet_25832=None, pfad=None, zeit_label=None,
                  einzeln=True):
    """Choroplethe je Flurstueck nach Sonnendosis (gruen=schattig, rot=sonnig).
    Nicht bewertbare (vollversiegelte) Flurstuecke grau.

    einzeln=True: zusaetzlich je Nutzungsklasse eine eigene, abschaltbare Ebene
    (Layer-Control). Default ist nur "Alle Flurstuecke" an; einzelne Klassen
    schaltest du dazu, um z.B. alle Gruenanlagen schnell zu finden."""
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "nutzung_sonnendosis.html")

    # nur Flurstuecke im Testgebiet zeigen (sonst der ganze Kreis-Auszug)
    fl = fl_bewertet
    if gebiet_25832 is not None:
        fl = fl[fl.intersects(gebiet_25832)].copy()

    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Sonnendosis je Flurstueck (0 = schattig, 1 = sonnig; grau = nicht bewertbar)"

    fl_wgs = fl.to_crs(CRS_WGS84).copy()
    fl_wgs["dosis_txt"] = fl_wgs["sonnendosis"].map(
        lambda x: f"{x:.2f}" if np.isfinite(x) else "-")
    fl_wgs["frei_txt"] = fl_wgs["freiflaeche_m2"].map(lambda x: f"{x:.0f} m2")
    # Farbe je Flurstueck vorab festlegen (bewertbar -> Skala, sonst grau)
    fl_wgs["farbe"] = [
        cmap(d) if b else "#999999"
        for d, b in zip(fl_wgs["sonnendosis"], fl_wgs["bewertbar"])
    ]
    # NaN aus dem GeoJSON nehmen (sonst ungueltiges JSON)
    fl_wgs["sonnendosis"] = fl_wgs["sonnendosis"].fillna(-1.0)

    spalten = ["geometry", "farbe", "nutzart", "dosis_txt", "frei_txt"]

    def stil(feat):
        return {"fillColor": feat["properties"]["farbe"], "color": "#555",
                "weight": 0.3, "fillOpacity": 0.7}

    def tooltip():
        # je GeoJson eine eigene Tooltip-Instanz (nicht wiederverwenden)
        return folium.GeoJsonTooltip(
            fields=["nutzart", "dosis_txt", "frei_txt"],
            aliases=["Nutzung", "Sonnendosis", "Freiflaeche"])

    mitte = fl_wgs.geometry.union_all().centroid
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=16, tiles=None, max_zoom=MAX_ZOOM_KARTE)
    basis_layer(m, max_zoom=MAX_ZOOM_KARTE)

    # Default-Ebene: alle Flurstuecke zusammen
    alle = folium.FeatureGroup(name="Alle Flurstuecke", show=True)
    folium.GeoJson(fl_wgs[spalten], style_function=stil, tooltip=tooltip()).add_to(alle)
    alle.add_to(m)

    # je Nutzungsklasse eine eigene, anfangs ausgeschaltete Ebene
    if einzeln:
        for klasse in sorted(fl_wgs["nutzart"].unique()):
            teil = fl_wgs[fl_wgs["nutzart"] == klasse]
            fg = folium.FeatureGroup(name=f"{klasse} ({len(teil)})", show=False)
            folium.GeoJson(teil[spalten], style_function=stil, tooltip=tooltip()).add_to(fg)
            fg.add_to(m)

    cmap.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    # Klick auf die Karte zeigt die Koordinate (lat, lon) - zum Ablesen fuer
    # die Detail-Lupe (DETAIL_PUNKT_LATLON in config.py).
    folium.LatLngPopup().add_to(m)

    if zeit_label is None:
        zeit_label = f"{AGG_START_STUNDE:02d}-{AGG_END_STUNDE:02d} Uhr (Tagesmittel)"
    gebiet_txt = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {"Zeitfenster": zeit_label, "Gebiet": gebiet_txt,
                 "Schwelle Freiflaeche": f"{MIN_FREIFLAECHE_M2:.0f} m2"})

    m.save(pfad)
    print(f"  Karte gespeichert: {pfad}")
    return pfad


def karte_flurstueck_detail(flurstuecke, dosis, transform, punkt_latlon,
                            nodata=NODATA, pfad=None):
    """Lupe auf EIN Flurstueck: jede Rasterzelle einzeln eingefaerbt, Dach-Zellen
    grau, Flurstuecksgrenze als Umriss, Mittelwert beschriftet. Macht den
    Zwischenschritt 'Zellen -> Mittel je Flurstueck' sichtbar - das Werkzeug,
    um z.B. 'warum ist mein Haus schattig' transparent zu erklaeren.

    Frueher zusaetzlich mit Esri-World-Imagery-Luftbild, damit man beim
    Erklaeren einzelne Zellen gegen "das ist das Dach"/"das ist der Baum" im
    echten Foto abgleichen konnte. Der Esri-Layer ist aus Lizenzgruenden
    entfernt (siehe ablauf.md) und NICHT ersetzt - Ersatz durch das offene
    LGL-ATKIS-Orthophoto ist vorgesehen, sobald die WMS/WMTS-URL aus
    opengeodata.lgl-bw.de vorliegt.

    punkt_latlon : (lat, lon) irgendwo im gewuenschten Flurstueck
                   (auf der Uebersichtskarte anklicken, Koordinate ablesen).
    """
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "flurstueck_detail.html")

    lat, lon = punkt_latlon
    p = gpd.GeoSeries([Point(lon, lat)], crs=CRS_WGS84).to_crs(CRS_METRISCH).iloc[0]
    treffer = flurstuecke[flurstuecke.contains(p)]
    if treffer.empty:
        treffer = flurstuecke[flurstuecke.intersects(p.buffer(1.0))]
    if treffer.empty:
        raise ValueError(
            f"Kein Flurstueck am Punkt {punkt_latlon}. Liegt er im Testgebiet?")
    parz = treffer.iloc[0]

    # Zellen des Flurstuecks aus dem Raster holen (Mittelpunkt im Flurstueck)
    mask = features.rasterize([(parz.geometry, 1)], out_shape=dosis.shape,
                              transform=transform, fill=0).astype(bool)
    rows, cols = np.where(mask)
    px = transform.a   # Zellbreite (= Aufloesung); transform.e ist -Aufloesung
    recs = []
    for r, c in zip(rows, cols):
        west = transform.c + c * px
        north = transform.f + r * transform.e
        recs.append({"geometry": box(west, north + transform.e, west + px, north),
                     "wert": float(dosis[r, c])})
    if not recs:
        raise ValueError("Flurstueck deckt keine Rasterzelle ab (zu klein?).")
    zellen = gpd.GeoDataFrame(recs, crs=CRS_METRISCH)
    zellen["typ"] = np.where(zellen["wert"] == nodata, "dach", "frei")

    frei = zellen[zellen["typ"] == "frei"]
    res_m = abs(px)
    mittel = float(frei["wert"].mean()) if len(frei) else float("nan")
    freiflaeche = len(frei) * res_m * res_m
    nutz = parz.get("nutzart", "?")

    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Sonnendosis je Zelle (0 = schattig, 1 = sonnig)"

    z_wgs = zellen.to_crs(CRS_WGS84).copy()
    z_wgs["farbe"] = [cmap(w) if t == "frei" else "#777777"
                      for w, t in zip(z_wgs["wert"], z_wgs["typ"])]
    z_wgs["label"] = [f"{w:.2f}" if t == "frei" else "Dach (rausgerechnet)"
                      for w, t in zip(z_wgs["wert"], z_wgs["typ"])]

    mitte = gpd.GeoSeries([parz.geometry.centroid], crs=CRS_METRISCH).to_crs(CRS_WGS84).iloc[0]
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=20, max_zoom=22, tiles=None)
    basis_layer(m, max_zoom=22)

    folium.GeoJson(
        z_wgs[["geometry", "farbe", "label"]], name="Zellen",
        style_function=lambda f: {"fillColor": f["properties"]["farbe"],
                                  "color": "#333", "weight": 0.5, "fillOpacity": 0.75},
        tooltip=folium.GeoJsonTooltip(fields=["label"], aliases=["Zelle"]),
    ).add_to(m)

    grenze = gpd.GeoSeries([parz.geometry], crs=CRS_METRISCH).to_crs(CRS_WGS84)
    folium.GeoJson(grenze, name="Flurstueck",
                   style_function=lambda f: {"fillOpacity": 0, "color": "#111",
                                             "weight": 2.5}).add_to(m)

    cmap.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    info_box(m, {
        "Nutzung": nutz,
        "Mittel (Freiflaeche)": f"{mittel:.2f}",
        "Freiflaeche": f"{freiflaeche:.0f} m2 ({len(frei)} Zellen)",
        "Dach-Zellen (raus)": f"{len(zellen) - len(frei)}",
    })

    m.save(pfad)
    print(f"  Detail: {nutz}, Mittel {mittel:.2f}, "
          f"{len(frei)} frei / {len(zellen)-len(frei)} Dach. Gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    from modules.loader import _analyse_gebiet_25832
    try:
        from config import DETAIL_PUNKT_LATLON
    except ImportError:
        DETAIL_PUNKT_LATLON = None

    dosis, transform, nodata = lade_dosis_tif()
    gebiet = _analyse_gebiet_25832()

    flurstuecke = lade_flurstuecke()
    flurstuecke = flurstuecke[flurstuecke.intersects(gebiet)].reset_index(drop=True)

    fl_bewertet = bewerte_flurstuecke(flurstuecke, dosis, transform, nodata)
    zusammenfassung(fl_bewertet)
    karte_nutzung(fl_bewertet, gebiet)

    # Optional: Lupe auf ein einzelnes Flurstueck (Koordinate aus config)
    if DETAIL_PUNKT_LATLON:
        karte_flurstueck_detail(flurstuecke, dosis, transform, DETAIL_PUNKT_LATLON, nodata)