# stadtschatten/modules/aufenthalt.py
#
# AUFENTHALTSORTE x VERSCHATTUNG - die umgedrehte Leserichtung.
#
# Bisher: "wie besonnt ist welche Nutzung" (nutzung.py, ALKIS).
# Hier:   "wo FEHLT Schatten an Orten, wo sich Menschen aufhalten" - die Stelle,
#         an der aus der Beschreibung eine Handlungsempfehlung wird.
#         An einem Aufenthaltsort ist ROT (sonnig) = Verschattungsbedarf.
#
# Quelle: OpenStreetMap (ALKIS-Nutzungsarten sind zu grob; Schulen stecken in
#   "Oeffentliche Zwecke", Haltestellen sind gar keine Flurstuecke). Dieselbe
#   osmnx-Maschinerie wie bei den Gebaeuden, kein neuer Stack.
#
# Erster Durchgang (an Denkendorf-Daten festgelegt):
#   Schulen        amenity=school        (Flaechen)
#   Kindergaerten  amenity=kindergarten  (Flaechen + Punkte)
#   Spielplaetze   leisure=playground    (Flaechen)
#   Bushaltestellen highway=bus_stop UND public_transport=platform (Punkte),
#                  auf BUSHALT_DEDUP_M entdoppelt (beide Tags meinen oft dieselbe
#                  Haltestelle), dann zu einem Wartebereich gepuffert.
#
# Einheitliche Logik: alles wird zu einem kleinen BEREICH (Flaeche direkt;
#   Punkt -> Puffer AUFENTHALT_PUNKT_PUFFER_M), dann Mittel der Dosis-Zellen
#   darin - genau wie bei den Flurstuecken (Daecher sind im Raster schon raus).
#
# EHRLICHE VORBEHALTE (in die README/Kartenlegende):
#   - OSM-Abdeckung ist uneinheitlich: Haltestellen/Schulen meist gut, anderes
#     lueckenhaft. Was OSM nicht kennt, fehlt.
#   - public_transport=platform kann theoretisch Bahn-/Tram-Steige meinen
#     (in Denkendorf vermutlich alles Bus) -> an der Karte gegen Ortswissen pruefen.
#
# Datenquelle Verschattung: LGL, www.lgl-bw.de. Aufenthaltsorte: (c) OpenStreetMap.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
from rasterio import features
from shapely.ops import unary_union
from shapely.geometry import Point

from config import (CRS_METRISCH, CRS_WGS84, OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE, ORT_SLUG,
                    AGG_START_STUNDE, AGG_END_STUNDE,
                    AUFENTHALT_PUNKT_PUFFER_M, BUSHALT_DEDUP_M, MAX_ZOOM_KARTE,
                    AUFENTHALT_GEWICHTUNG, GEWICHT_STANDARD)
from modules.karte_info import info_box, rangliste_box
from modules.nutzung import lade_dosis_tif, NODATA


# ----------------------------------------------------------------------
# OSM -> Aufenthaltsbereiche (Flaechen; Punkte gepuffert)
# ----------------------------------------------------------------------

def _spalte(g, key):
    """Sicherer Spaltenzugriff: leere Series, wenn die Spalte fehlt."""
    if key in g.columns:
        return g[key]
    import pandas as pd
    return pd.Series([None] * len(g), index=g.index)


def _name(row):
    n = row.get("name")
    return n if isinstance(n, str) else ""


def _dedup_priorisiert(kandidaten, abstand):
    """Greedy-Entdopplung mit Vorrang. kandidaten: Liste (punkt, prioritaet, name).
    Liegen zwei Punkte naeher als abstand, bleibt der mit HOEHERER Prioritaet
    (platform=2 > bus_stop=1) - der Wartebereich statt des Fahrbahn-Punkts.
    Rueckgabe: Liste (punkt, name)."""
    behalten = []   # Liste [punkt, prio, name]
    for p, prio, name in kandidaten:
        ersetzt = False
        for i, (q, qprio, _) in enumerate(behalten):
            if p.distance(q) <= abstand:
                if prio > qprio:
                    behalten[i] = (p, prio, name)   # bevorzugten Punkt uebernehmen
                ersetzt = True
                break
        if not ersetzt:
            behalten.append((p, prio, name))
    return [(p, name) for p, _, name in behalten]


def _entdoppele_verschachtelt(recs):
    """Verschachtelte Dubletten je Kategorie entfernen: liegt der Mittelpunkt
    eines Objekts in einem GROESSEREN Objekt DERSELBEN Kategorie, ist es eine
    Dublette (z.B. Schulgebaeude im Schulgelaende, KiGa-Punkt im KiGa-Gelaende)
    und faellt raus. recs: Liste (geometry, kategorie, name)."""
    behalten = []
    n_vorher = len(recs)
    nach_kat = {}
    for r in recs:
        nach_kat.setdefault(r[1], []).append(r)
    for kat, items in nach_kat.items():
        # groesste zuerst -> kleinere, die darin liegen, fallen weg
        for geom, k, name in sorted(items, key=lambda r: r[0].area, reverse=True):
            if any(geom.centroid.within(bg) for bg, bk, bn in behalten if bk == kat):
                continue
            behalten.append((geom, k, name))
    entfernt = n_vorher - len(behalten)
    if entfernt:
        print(f"  {entfernt} verschachtelte Dublette(n) entfernt (z.B. Gebaeude im Gelaende).")
    return behalten


# Toleranz fuer _cluster_flaechen: ueberbrueckt kleine Luecken zwischen
# Gebaeuden/Teilflaechen, die real zu EINER Einrichtung gehoeren (z.B.
# Hauptgebaeude und Nebentrakt eines Schulcampus, durch einen schmalen Weg
# getrennt). Nicht an echten Daten verifiziert - nach dem ersten Lauf gegen
# die Konsolenausgabe und die Karte pruefen: zu gross fasst benachbarte,
# tatsaechlich getrennte Einrichtungen faelschlich zusammen; zu klein loest
# das Fragmentierungsproblem nicht vollstaendig. Bei Bedarf zusammen mit
# AUFENTHALT_PUNKT_PUFFER_M nach config.py verschieben.
AUFENTHALT_CLUSTER_PUFFER_M = 8.0


def _cluster_flaechen(flaechen_recs, puffer_m, isolier_punkte=None):
    """
    Fasst pro Kategorie raeumlich zusammenhaengende Flaechen zu EINEM
    Aufenthaltsort zusammen.

    Grund: grosse Einrichtungen (v.a. Schulcampusse) werden in OSM oft OHNE
    gemeinsames Gelaende-Polygon gemappt - stattdessen traegt jedes einzelne
    Gebaeude/jede Teilflaeche fuer sich dasselbe amenity-Tag, meist nur eines
    davon mit Namen. _entdoppele_verschachtelt() erkennt nur ECHTE
    Containment-Faelle (Punkt LIEGT IN einem groesseren Polygon) - NEBENEINANDER
    liegende Gebaeude derselben Kategorie ohne gemeinsames Huellpolygon sind
    keine Verschachtelung und blieben bislang unentdeckt: ein einzelner
    Schulcampus erschien so als viele einzelne "Schule (ohne Name)"-Eintraege.

    puffer_m       : Toleranz zum Ueberbruecken kleiner Luecken (siehe
                     AUFENTHALT_CLUSTER_PUFFER_M).
    flaechen_recs  : Liste (geometry, kategorie, name), NUR die Flaechen-
                     Kategorien (nicht Punkte/Bushaltestellen - die haben
                     eigene Dedup-Logik).
    isolier_punkte : Liste (x, y, radius) aus der Ausnahmeliste (Eintragstyp
                     "!"). Fragmente, deren Zentroid innerhalb radius liegt,
                     werden NIE gemergt - bleiben als EIGENER, unveraenderter
                     Ort stehen, egal wie nah sie an einem anderen Fragment
                     liegen. Fuer echte, eigenstaendige Einrichtungen, die
                     in OSM keinen Namen tragen und deshalb faelschlich mit
                     einer benachbarten Einrichtung verschmolzen wuerden -
                     im Unterschied zu einer Ausnahme, die das Objekt
                     KOMPLETT entfernt (siehe _lade_ausnahmen): die
                     Einrichtung existiert wirklich und soll in der
                     Rangliste auftauchen, nur eben unter "(ohne Name)" -
                     genau wie eine Sitzbank.

    Rueckgabe: Liste (geometry, kategorie, name) - geometry ist die
    Vereinigung aller Mitglieder eines Clusters (ungepuffert), name der
    erste ECHTE Name im Cluster. AUSNAHME: tragen mehrere Mitglieder eines
    Clusters UNTERSCHIEDLICHE echte Namen, wird NICHT zusammengefasst
    (vermutlich zwei echte Einrichtungen dicht beieinander, nicht Fragmente
    einer einzelnen - siehe Warnung in der Konsole). Das schliesst das
    Risiko in dichter Bebauung NICHT vollstaendig: liegt eine zweite,
    tatsaechlich eigenstaendige Einrichtung derselben Kategorie im Puffer
    UND hat in OSM KEINEN Namen, ist sie von einem echten Fragment nicht
    unterscheidbar - dieser Rest-Fall bleibt ein manuelles Pruef-Thema
    (siehe isolier_punkte oben fuer den Fix, sobald entdeckt).
    """
    isolier_punkte = isolier_punkte or []

    normal, isoliert = [], []
    for geom, kat, name in flaechen_recs:
        z = geom.centroid
        if any(z.distance(Point(x, y)) <= r for x, y, r in isolier_punkte):
            isoliert.append((geom, kat, name))
        else:
            normal.append((geom, kat, name))
    if isoliert:
        print(f"  {len(isoliert)} Flaeche(n) durch Ausnahmeliste vom Zusammenfassen "
             f"ausgenommen (bleiben eigener Ort): "
             f"{', '.join(k + (f' ({n})' if n else ' (ohne Name)') for _, k, n in isoliert)}.")

    ergebnis = list(isoliert)
    nach_kat = {}
    for geom, kat, name in normal:
        nach_kat.setdefault(kat, []).append((geom, name))

    for kat, items in nach_kat.items():
        geome = [g for g, _ in items]
        gepuffert = [g.buffer(puffer_m) for g in geome]
        vereinigt = unary_union(gepuffert)
        cluster_liste = list(vereinigt.geoms) if vereinigt.geom_type == "MultiPolygon" else [vereinigt]

        for cluster in cluster_liste:
            mitglieder = [i for i, g in enumerate(gepuffert) if g.intersects(cluster)]
            original_geome = [geome[i] for i in mitglieder]
            namen = [items[i][1] for i in mitglieder if items[i][1]]
            eindeutige_namen = sorted(set(namen))

            if len(eindeutige_namen) > 1:
                # Mehrere VERSCHIEDENE echte Namen im selben Cluster: eher zwei
                # unterschiedliche Einrichtungen dicht beieinander (z.B. zwei
                # Kitas in dichter Bebauung) als Fragmente EINER Einrichtung.
                # Kein automatischer Merge - ein Algorithmus kann das aus
                # Geometrie+Name allein nicht sicher unterscheiden. Stattdessen
                # laut warnen und jede Flaeche einzeln behalten.
                print(f"  Warnung: {len(mitglieder)} {kat}-Flaechen dicht beieinander mit "
                     f"UNTERSCHIEDLICHEN Namen ({', '.join(eindeutige_namen)}) - "
                     f"NICHT zusammengefasst, bitte manuell pruefen.")
                for i in mitglieder:
                    ergebnis.append((geome[i], kat, items[i][1]))
                continue

            geometrie = unary_union(original_geome) if len(original_geome) > 1 else original_geome[0]
            name = eindeutige_namen[0] if eindeutige_namen else ""
            if len(mitglieder) > 1:
                etikett = f" ({name})" if name else " (ohne Name - bitte pruefen)"
                print(f"  {len(mitglieder)} {kat}-Flaechen zu einem Ort zusammengefasst{etikett}.")

                # Grenzfall-Check: wie gross war die groesste Luecke zwischen
                # zwei direkt verbundenen Fragmenten im Cluster? Nahe 0 =
                # Fragmente beruehren/ueberlappen sich (z.B. angrenzende
                # Gebaeudefluegel) - hohe Merge-Sicherheit, kein Grund zur
                # manuellen Pruefung. Puffer_m*0.5 als Schwelle, weil zwei
                # Fragmente bis zu fast 2*puffer_m auseinanderliegen und
                # trotzdem noch verbinden koennen (beide Seiten puffern nach
                # aussen) - genau der Fall, der beim Kindergarten-Merge
                # (Muehlhalden/Klingenacker) eine andere, eigenstaendige
                # Einrichtung verschluckt hat. Nennt jetzt direkt das
                # schlimmste Paar (Name/Position), damit kein separater
                # Debug-Lauf noetig ist, um es zu identifizieren.
                max_luecke = 0.0
                schlimmstes_paar = None
                for a in range(len(mitglieder)):
                    for b in range(a + 1, len(mitglieder)):
                        i, j = mitglieder[a], mitglieder[b]
                        if gepuffert[i].intersects(gepuffert[j]):
                            luecke = geome[i].distance(geome[j])
                            if luecke > max_luecke:
                                max_luecke = luecke
                                schlimmstes_paar = (i, j)
                if max_luecke > puffer_m * 0.5:
                    i, j = schlimmstes_paar
                    ni = items[i][1] or "(ohne Name)"
                    nj = items[j][1] or "(ohne Name)"
                    ci, cj = geome[i].centroid, geome[j].centroid
                    print(f"    Grenzfall: groesste Luecke im Cluster {max_luecke:.1f} m "
                         f"(Puffer {puffer_m:.0f} m) zwischen '{ni}' ({ci.x:.0f}, {ci.y:.0f}) "
                         f"und '{nj}' ({cj.x:.0f}, {cj.y:.0f}) - naeher an der Puffer-Grenze "
                         f"als an 'eindeutig dieselbe Anlage'. Bitte manuell pruefen.")
            ergebnis.append((geometrie, kat, name))

    return ergebnis


AUSNAHMEN_ORDNER = "ausnahmen"
# Bewusst NICHT in DATA_DIR: DATA_DIR ist Cache (gitignored, siehe config.py).
# Eine Ausnahmeliste ist handgepflegtes Wissen ueber einen konkreten Ort -
# gehoert versioniert ins Repo, sonst ist sie beim naechsten Cache-Aufraeumen
# ersatzlos weg.


def _lade_ausnahmen():
    """
    Pro Ort gepflegte Ausnahmeliste fuer OSM-Fehler. Datei:
    ausnahmen/<ORT_SLUG>.txt - eine Zeile pro Eintrag, '#' fuer Kommentare/
    Begruendung. Drei Eintragsarten, klar unterschiedliche Wirkung:

      Name (exaktes Match)
          Objekt existiert in dieser Kategorie zurecht NICHT - falsche
          Kategorie/Fehl-Tagging (z.B. ein Jugendzentrum mit amenity=
          school). Wird KOMPLETT entfernt, taucht nirgends mehr auf.

      "@x,y[,radius]"  (Ausschluss, Koordinate)
          Dasselbe wie oben, aber fuer UNBENANNTE Fehl-Taggings ohne
          Namen zum Matchen. x,y in CRS_METRISCH (Meter), radius optional
          (Default 5 m, bewusst eng). Schliesst jedes Objekt aus, dessen
          Zentroid innerhalb radius liegt. KOMPLETT entfernt.

      "!x,y[,radius]"  (Isolieren, Koordinate)
          Das Objekt existiert zurecht und in der richtigen Kategorie -
          es wurde nur faelschlich mit einem NACHBARN zusammengefasst,
          weil es in OSM keinen Namen traegt und deshalb der Namens-
          Konflikt-Schutz in _cluster_flaechen() nicht greift. Wird NICHT
          geloescht, sondern nur vom Merge ausgenommen - bleibt als
          eigener Ort "(ohne Name)" in der Rangliste, wie eine Sitzbank.
          NICHT verwechseln mit "@": "@" loescht eine Einrichtung, die es
          in dieser Kategorie nicht geben sollte; "!" behaelt eine
          Einrichtung, die es geben sollte, trennt sie nur vom Nachbarn.

    Koordinaten aus dem DEBUG-Print in _cluster_flaechen() oder einer
    eigenen Pruefung uebernehmen. Datei ist optional; fehlt sie, wird
    nichts ausgeschlossen/isoliert.

    Rueckgabe: (namen: set[str], ausschluss_punkte: list[(x,y,r)],
                isolier_punkte: list[(x,y,r)])
    """
    pfad = os.path.join(AUSNAHMEN_ORDNER, f"{ORT_SLUG}.txt")
    if not os.path.exists(pfad):
        return set(), [], []

    namen = set()
    ausschluss_punkte = []
    isolier_punkte = []
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            z = zeile.strip()
            if not z or z.startswith("#"):
                continue
            if z.startswith("@") or z.startswith("!"):
                teile = z[1:].split(",")
                x, y = float(teile[0]), float(teile[1])
                radius = float(teile[2]) if len(teile) > 2 else 5.0
                (ausschluss_punkte if z.startswith("@") else isolier_punkte).append((x, y, radius))
            else:
                namen.add(z)

    if namen or ausschluss_punkte or isolier_punkte:
        print(f"  Ausnahmeliste ({pfad}): {len(namen)} Name(n), "
             f"{len(ausschluss_punkte)} Ausschluss-, {len(isolier_punkte)} "
             f"Isolier-Koordinate(n) hinterlegt.")
    return namen, ausschluss_punkte, isolier_punkte


def lade_aufenthaltsorte():
    """OSM-Aufenthaltsorte im Testgebiet als GeoDataFrame[geometry, kategorie, name]
    in CRS_METRISCH. Flaechen direkt, Punkte zu Wartebereich gepuffert."""
    tags = {"amenity": ["school", "kindergarten", "social_facility", "bench"],
            "leisure": ["playground"],
            "highway": ["bus_stop"],
            "public_transport": ["platform"]}

    if ZENTRUM:
        print(f"Lade Aufenthaltsorte von OSM (Punkt-Modus, {RADIUS_M} m) ...")
        g = ox.features_from_point(ZENTRUM, tags=tags, dist=RADIUS_M)
    else:
        print(f"Lade Aufenthaltsorte von OSM (Orts-Modus, {PLACE}) ...")
        g = ox.features_from_place(PLACE, tags=tags)

    g = g.to_crs(CRS_METRISCH)

    ausnahme_namen, ausschluss_punkte, isolier_punkte = _lade_ausnahmen()
    if ausnahme_namen or ausschluss_punkte:
        namen_in_g = g.apply(_name, axis=1)
        maske_name = namen_in_g.isin(ausnahme_namen) if ausnahme_namen else pd.Series(False, index=g.index)

        zentroide = g.geometry.centroid
        maske_punkt = pd.Series(False, index=g.index)
        for x, y, radius in ausschluss_punkte:
            maske_punkt |= (zentroide.distance(Point(x, y)) <= radius)

        maske = maske_name | maske_punkt
        treffer_namen = set(namen_in_g[maske_name])

        if treffer_namen:
            print(f"  {len(treffer_namen)} OSM-Objekt(e) durch Namens-Ausnahme entfernt: "
                 f"{', '.join(sorted(treffer_namen))}")
        if maske_punkt.sum():
            print(f"  {int(maske_punkt.sum())} OSM-Objekt(e) durch Koordinaten-Ausschluss entfernt.")

        unbenutzt = ausnahme_namen - treffer_namen
        if unbenutzt:
            print(f"  Warnung: {len(unbenutzt)} Namens-Eintrag/Eintraege in der Ausnahmeliste "
                 f"ohne Treffer in diesem Lauf (Tippfehler? OSM-Objekt umbenannt/entfernt?): "
                 f"{', '.join(sorted(unbenutzt))}")

        g = g[~maske].copy()

    amenity = _spalte(g, "amenity")
    leisure = _spalte(g, "leisure")
    highway = _spalte(g, "highway")
    optnv = _spalte(g, "public_transport")
    ist_flaeche = g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ist_punkt = g.geometry.geom_type == "Point"

    recs = []   # (geometry_25832, kategorie, name)

    # --- Flaechen-Kategorien (Polygone direkt) ---
    flaechen_def = [
        (amenity == "school", "Schule"),
        (amenity == "kindergarten", "Kindergarten"),
        (amenity == "social_facility", "Soziale Einrichtung"),
        (leisure == "playground", "Spielplatz"),
    ]
    flaechen_recs = []
    for maske, kat in flaechen_def:
        for _, row in g[maske & ist_flaeche].iterrows():
            flaechen_recs.append((row.geometry, kat, _name(row)))

    # Campus-Faelle zusammenfassen (siehe _cluster_flaechen) - VOR dem
    # Zusammenfuehren mit Punkten/Bushaltestellen, damit deren Puffer die
    # Cluster-Erkennung nicht verfaelschen.
    recs = _cluster_flaechen(flaechen_recs, AUFENTHALT_CLUSTER_PUFFER_M, isolier_punkte)

    # --- Punkt-Kategorien (zu Wartebereich gepuffert; Dublette in Flaeche faellt unten weg) ---
    punkt_def = [
        (amenity == "kindergarten", "Kindergarten"),
        (amenity == "social_facility", "Soziale Einrichtung"),
        (amenity == "bench", "Sitzbank"),
    ]
    for maske, kat in punkt_def:
        for _, row in g[maske & ist_punkt].iterrows():
            recs.append((row.geometry.buffer(AUFENTHALT_PUNKT_PUFFER_M), kat, _name(row)))

    # --- Bushaltestellen: bus_stop UND platform, priorisiert entdoppelt, dann gepuffert ---
    # platform (Wartebereich) hat Vorrang vor bus_stop (sitzt teils auf der Fahrbahn).
    kandidaten = []
    for _, row in g[highway == "bus_stop"].iterrows():
        geom = row.geometry
        kandidaten.append((geom if geom.geom_type == "Point" else geom.centroid, 1, _name(row)))
    for _, row in g[optnv == "platform"].iterrows():
        geom = row.geometry
        kandidaten.append((geom if geom.geom_type == "Point" else geom.centroid, 2, _name(row)))
    for p, name in _dedup_priorisiert(kandidaten, BUSHALT_DEDUP_M):
        recs.append((p.buffer(AUFENTHALT_PUNKT_PUFFER_M), "Bushaltestelle", name))

    # verschachtelte Dubletten uebergreifend entfernen (z.B. gepufferter Punkt
    # innerhalb einer bereits zusammengefassten Flaeche)
    recs = _entdoppele_verschachtelt(recs)

    orte = gpd.GeoDataFrame(
        {"kategorie": [r[1] for r in recs], "name": [r[2] for r in recs]},
        geometry=[r[0] for r in recs], crs=CRS_METRISCH)
    n_pro = orte["kategorie"].value_counts().to_dict()
    print(f"  {len(orte)} Aufenthaltsorte: " +
          ", ".join(f"{k} {v}" for k, v in n_pro.items()))
    return orte


# ----------------------------------------------------------------------
# Verschattung je Aufenthaltsort (Zonal, wie bei den Flurstuecken)
# ----------------------------------------------------------------------

def bewerte_orte(orte, dosis, transform, nodata=NODATA):
    """Mittel der gueltigen Dosis-Zellen je Aufenthaltsbereich.
    Neue Spalten: frei_zellen, sonnendosis (NaN = keine gueltige Zelle)."""
    hoehe, breite = dosis.shape
    orte = orte.reset_index(drop=True).copy()
    lab = features.rasterize(
        ((geom, i + 1) for i, geom in enumerate(orte.geometry)),
        out_shape=(hoehe, breite), transform=transform, fill=0, dtype="int32")

    valid = dosis != nodata
    N = len(orte)
    summe = np.bincount(lab[valid], weights=dosis[valid], minlength=N + 1)[1:]
    anzahl = np.bincount(lab[valid], minlength=N + 1)[1:]
    mittel = np.full(N, np.nan)
    nz = anzahl > 0
    mittel[nz] = summe[nz] / anzahl[nz]

    orte["frei_zellen"] = anzahl.astype(int)
    orte["sonnendosis"] = mittel

    # Dringlichkeit = Sonnendosis * Gewicht (AUFENTHALT_GEWICHTUNG in config.py).
    # Physische Messung (sonnendosis) und fachliche Priorisierung
    # (dringlichkeit) bewusst getrennte Spalten - die Karteneinfaerbung
    # (rot/gruen) bleibt bei der reinen Sonnendosis, die Rangliste unten
    # nutzt die Dringlichkeit.
    orte["gewicht"] = orte["kategorie"].map(AUFENTHALT_GEWICHTUNG).fillna(GEWICHT_STANDARD)
    orte["dringlichkeit"] = orte["sonnendosis"] * orte["gewicht"]

    print(f"  {int(nz.sum())} von {N} Aufenthaltsorten haben gueltige Zellen.")
    return orte


def rangliste(orte_bewertet, n=5):
    """Dringlichkeit (Sonnendosis * Gewicht), getrennt je Kategorie.

    Die Kategorien sind fachlich nicht direkt vergleichbar - die Gewichtung
    ordnet nur EINE Kategorie insgesamt hoeher/niedriger ein (z.B. Kita vor
    Sitzbank). Innerhalb einer Kategorie bestimmt weiterhin allein die
    Sonnendosis die Reihenfolge, die Gewichtung ist dort konstant.

    Rueckgabe: dict {kategorie: DataFrame Top-n, absteigend sortiert} -
    direkt verwertbar fuer rangliste_box() auf der Karte bzw. den Export
    fuer die Gemeinderatsvorlage."""
    b = orte_bewertet[orte_bewertet["dringlichkeit"].notna()].copy()
    print(f"  Dringlichkeit (Sonnendosis x Gewicht), Top {n} je Kategorie:")
    ranglisten = {}
    for kat in sorted(b["kategorie"].unique()):
        teil = b[b["kategorie"] == kat].sort_values("dringlichkeit", ascending=False)
        top = teil.head(n)
        ranglisten[kat] = top
        print(f"\n  {kat} (Gewicht {top['gewicht'].iloc[0]:.1f}):")
        for _, r in top.iterrows():
            name = f" '{r['name']}'" if r["name"] else ""
            print(f"    {r['dringlichkeit']:.2f}  (Dosis {r['sonnendosis']:.2f}){name}")
    return ranglisten


# ----------------------------------------------------------------------
# Karte
# ----------------------------------------------------------------------

def karte_aufenthalt(orte_bewertet, gebiet_25832=None, pfad=None, zeit_label=None,
                     ranglisten=None):
    """Aufenthaltsorte nach Verschattungsbedarf (rot = sonnig = Bedarf).
    Je Kategorie eine abschaltbare Ebene; Bereich als Polygon + sichtbarer Punkt.

    ranglisten : optional, Rueckgabe von rangliste() - wenn gesetzt, zeigt
                 die Karte zusaetzlich das Dringlichkeits-Textkaestchen
                 oben rechts (rangliste_box)."""
    import folium
    from branca.colormap import LinearColormap

    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "aufenthalt_bedarf.html")

    orte = orte_bewertet
    if gebiet_25832 is not None:
        orte = orte[orte.intersects(gebiet_25832)].copy()

    cmap = LinearColormap(["#1a9641", "#ffffbf", "#d7191c"], vmin=0, vmax=1)
    cmap.caption = "Verschattungsbedarf am Aufenthaltsort (gruen = schattig/ok, rot = sonnig/Bedarf)"

    o = orte.to_crs(CRS_WGS84).copy()

    def bedarf(x):
        if not np.isfinite(x):
            return "Standort bekannt, Flaeche nicht bewertbar"
        return "hoch" if x >= 0.66 else ("mittel" if x >= 0.33 else "gering")

    o["farbe"] = [cmap(x) if np.isfinite(x) else "#999999" for x in o["sonnendosis"]]
    o["dosis_txt"] = o["sonnendosis"].map(lambda x: f"{x:.2f}" if np.isfinite(x) else "-")
    o["bedarf"] = o["sonnendosis"].map(bedarf)

    def _name_txt(r):
        # Fuer unbenannte Orte Koordinaten statt "(ohne Name)" ohne jede
        # weitere Angabe - sonst im Popup ohne Ortskenntnis nicht
        # identifizierbar (analog zum Strassennamen-Fallback in vorlage.py,
        # hier ohne Geh-Graph: reicht fuer die interaktive Karte, o ist
        # bereits WGS84, also keine Reprojektion noetig).
        if r["name"]:
            return r["name"]
        c = r.geometry.centroid
        return f"(ohne Name) {c.y:.5f}, {c.x:.5f}"

    o["name_txt"] = o.apply(_name_txt, axis=1)

    mitte = o.geometry.union_all().centroid
    m = folium.Map(location=[mitte.y, mitte.x], zoom_start=15, tiles=None, max_zoom=MAX_ZOOM_KARTE)
    folium.TileLayer("CartoDB positron", name="Karte", max_zoom=MAX_ZOOM_KARTE).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellit", max_zoom=MAX_ZOOM_KARTE).add_to(m)

    def stil(feat):
        return {"fillColor": feat["properties"]["farbe"], "color": "#333",
                "weight": 0.8, "fillOpacity": 0.55}

    for kat in sorted(o["kategorie"].unique()):
        teil = o[o["kategorie"] == kat]
        fg = folium.FeatureGroup(name=f"{kat} ({len(teil)})", show=True)
        # Flaechen/Wartebereiche als Polygon
        folium.GeoJson(
            teil[["geometry", "farbe", "kategorie", "name_txt", "dosis_txt", "bedarf"]],
            style_function=stil,
            tooltip=folium.GeoJsonTooltip(
                fields=["kategorie", "name_txt", "dosis_txt", "bedarf"],
                aliases=["Art", "Name", "Sonnendosis", "Bedarf"])).add_to(fg)
        # zusaetzlich ein sichtbarer Punkt (auch wenn weit rausgezoomt)
        for _, r in teil.iterrows():
            c = r.geometry.centroid
            folium.CircleMarker(
                [c.y, c.x], radius=6, color="#333", weight=1,
                fill=True, fill_color=r["farbe"], fill_opacity=0.9,
                tooltip=f"{r['kategorie']} {r['name_txt']}: {r['dosis_txt']} ({r['bedarf']})"
            ).add_to(fg)
        fg.add_to(m)

    cmap.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    if zeit_label is None:
        zeit_label = f"{AGG_START_STUNDE:02d}-{AGG_END_STUNDE:02d} Uhr (Tagesmittel)"
    gebiet_txt = f"{ZENTRUM[0]:.4f}, {ZENTRUM[1]:.4f} (r {RADIUS_M} m)" if ZENTRUM else PLACE
    info_box(m, {"Zeitfenster": zeit_label, "Gebiet": gebiet_txt,
                 "Lesart": "rot = sonnig = Verschattungsbedarf"},
             titel="Stadtschatten (Nathalie Gassert)",
             quellen=("Datenquelle Verschattung: LGL, www.lgl-bw.de",
                      "Aufenthaltsorte: (c) OpenStreetMap-Mitwirkende",
                      "OSM kennt fuer manche Orte keinen Namen; Koordinaten "
                      "dienen der Identifikation vor Ort."))

    if ranglisten:
        rangliste_box(m, ranglisten)

    m.save(pfad)
    print(f"  Karte gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    from modules.loader import _analyse_gebiet_25832

    dosis, transform, nodata = lade_dosis_tif()
    gebiet = _analyse_gebiet_25832()

    orte = lade_aufenthaltsorte()
    orte_bewertet = bewerte_orte(orte, dosis, transform, nodata)
    ranglisten = rangliste(orte_bewertet)
    karte_aufenthalt(orte_bewertet, gebiet, ranglisten=ranglisten)