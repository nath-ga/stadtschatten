# stadtschatten/modules/vorlage.py
#
# EIN layoutfertiges PDF fuer die Gemeinderatsvorlage: Karte mit den
# Top-Orten (Dringlichkeit = Sonnendosis * Gewicht, siehe aufenthalt.py)
# nummeriert markiert + Tabelle mit denselben Nummern, je Aufenthaltsart
# gruppiert. Kein Ersatz fuer die interaktive Folium-Karte (aufenthalt.py) -
# das hier ist zum Ausdrucken/Einfuegen in die Vorlage.
#
# Neue Abhaengigkeiten: matplotlib, contextily
# (`pip install matplotlib contextily`).
# contextily liefert den Kartenhintergrund (Strassen/Gebaeude) unter den
# Punkten - ohne ihn sind "Bushaltestelle Esslinger Strasse" o.ae. fuer
# jemanden ohne Ortskenntnis nicht einzuordnen. Kachelquelle: CartoDB
# Positron (dezent gehalten, damit die gruen/gelb/roten Dringlichkeits-
# Punkte lesbar bleiben) statt Esri World Imagery - Esri-Lizenzbedingungen
# fuer Druck/Weitergabe eines offiziellen Gemeinderatsdokuments sind
# unklarer als bei OSM-basierten Kacheln.
# Braucht Internetzugriff beim Export. contextily ist bewusst KEINE harte
# Abhaengigkeit: fehlt das Paket oder schlaegt der Kachel-Download fehl
# (z.B. kein Internet), faellt die Vorlage automatisch auf den bisherigen
# Gebietsumriss + Ortsname zurueck - eine Warnung erscheint auf der Konsole,
# der Export bricht nicht ab.
#
# Aufruf (nach aufenthalt.py, orte_bewertet + ranglisten liegen schon vor):
#   from modules.vorlage import exportiere_vorlage
#   exportiere_vorlage(orte_bewertet, ranglisten)
#
# Strassennamen fuer unbenannte Orte: nutzt den bereits vorhandenen Geh-Graphen
# aus loader.lade_geh_graph() (keine neue Abhaengigkeit, kein zweiter OSM-
# Download) - naechstgelegene Kante per ox.distance.nearest_edges, deren
# 'name'-Attribut. Falls der Aufrufer den Graphen schon geladen hat (z.B.
# fuer die Fusswege-Verschattung), per graph=... durchreichen statt hier
# ein zweites Mal zu laden.
#
# Fallback-Kette fuer den Namen unbenannter Orte (Stand: zwei Stufen):
#   1. naechstgelegene Kante im Geh-Graphen hat ein 'name'-Tag -> Strassenname
#   2. auch die naechste Kante ist unbenannt (oder Suche schlaegt fehl)
#      -> WGS84-Koordinaten (lat, lon), copy-paste-faehig fuer Google Maps
#   Reiner "(ohne Name)" ohne jede weitere Angabe sollte damit nicht mehr
#   vorkommen. Fall real aufgetreten in Denkendorf (eine Sitzbank, deren
#   naechste Kante ein unbenannter Fussweg ist) - Stufe 2 wurde deshalb
#   ergaenzt, siehe _strassennamen_ergaenzen().

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Circle
from matplotlib.lines import Line2D

from config import (OUTPUT_DIR, ZENTRUM, RADIUS_M, PLACE, CRS_METRISCH, CRS_WGS84,
                    AGG_START_STUNDE, AGG_END_STUNDE, DATUM)

# contextily ist optional (siehe Kopfkommentar): fehlt das Paket, laeuft die
# Vorlage ohne Kartenhintergrund weiter statt hart abzubrechen.
try:
    import contextily as cx
    _CONTEXTILY_VERFUEGBAR = True
except ImportError:
    _CONTEXTILY_VERFUEGBAR = False

# Kachelquelle + Zoomstufe fuer den Kartenhintergrund. Positron ist dezent
# genug, dass die Dringlichkeits-Punkte (gruen/gelb/rot) gut lesbar bleiben.
# zoom="auto" waehlt die Kachelstufe passend zu Figurgroesse/Kartenausschnitt;
# bei leeren/unscharfen Kacheln hier stattdessen eine feste Zahl eintragen
# (Richtwert fuer RADIUS_M ~100-300m: 17-18).
_BASEMAP_SOURCE = None
_BASEMAP_ZOOM = "auto"
_BASEMAP_ATTRIBUTION = "(c) OpenStreetMap-Mitwirkende, (c) CARTO"
if _CONTEXTILY_VERFUEGBAR:
    _BASEMAP_SOURCE = cx.providers.CartoDB.Positron

# dieselbe Skala wie auf den Folium-Karten (branca LinearColormap gruen->gelb->rot)
_CMAP = LinearSegmentedColormap.from_list("dosis", ["#1a9641", "#ffffbf", "#d7191c"])

# Rang-Labels: Standard-Offset oben rechts vom Punkt. Kandidaten fuer den
# Fall, dass zwei Orte im Datensatz so nah beieinander liegen, dass sich
# Punkt UND Zahl ueberdecken (z.B. zwei Orte an derselben Strasse) -
# _naechster_freier_offset() waehlt dann einen der uebrigen sieben Werte.
_LABEL_OFFSET_STANDARD = (5, 5)
_LABEL_OFFSET_KANDIDATEN = [
    (5, 5), (5, -13), (-14, 5), (-14, -13),
    (16, -4), (-20, -4), (5, 18), (-14, 18),
]
_LABEL_KOLLISIONS_SCHWELLE_PX = 22  # unterhalb dieses Pixelabstands zweier
                                    # Label-Ankerpunkte gilt es als Ueberlappung


def _farbe(dosis):
    """Sonnendosis (0..1) -> RGB-Tupel, dieselbe Skala wie die Folium-Karten."""
    if not np.isfinite(dosis):
        return "#999999"
    r, g, b, _ = _CMAP(float(np.clip(dosis, 0.0, 1.0)))
    return (r, g, b)


def _mittelpunkt_metrisch():
    """ZENTRUM (lat, lon) -> (x, y) in CRS_METRISCH, fuer Gebietskreis/Ausschnitt.
    None, wenn ZENTRUM nicht gesetzt (ganzer Ort - kein sinnvoller Kreis)."""
    from shapely.geometry import Point
    if ZENTRUM is None:
        return None
    lat, lon = ZENTRUM
    p = gpd.GeoSeries([Point(lon, lat)], crs=CRS_WGS84).to_crs(CRS_METRISCH).iloc[0]
    return p.x, p.y


def _skalenbalken(ax, laenge_m):
    """Skalenbalken unten links, in Datenkoordinaten (Meter, CRS_METRISCH)."""
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    x0 = xlim[0] + (xlim[1] - xlim[0]) * 0.05
    y0 = ylim[0] + (ylim[1] - ylim[0]) * 0.05
    hoch = (ylim[1] - ylim[0]) * 0.01
    ax.plot([x0, x0 + laenge_m], [y0, y0], color="#222", linewidth=2, solid_capstyle="butt")
    for x in (x0, x0 + laenge_m):
        ax.plot([x, x], [y0 - hoch, y0 + hoch], color="#222", linewidth=1)
    ax.text(x0 + laenge_m / 2, y0 + hoch * 2.5, f"{laenge_m:.0f} m",
            ha="center", va="bottom", fontsize=8, color="#222")


def _nordpfeil(ax):
    """Nordpfeil oben rechts (Achsen-Koordinaten). UTM-Nord ~ wahrer Norden -
    fuer diesen Massstab (Screening-Ebene) ausreichend genau."""
    ax.annotate("N", xy=(0.95, 0.90), xytext=(0.95, 0.78), xycoords="axes fraction",
               textcoords="axes fraction", ha="center", fontsize=10, fontweight="bold",
               arrowprops=dict(arrowstyle="-|>", color="#222", lw=1.5))


def _naechster_freier_offset(ax, x_daten, y_daten, bereits_platziert_px):
    """
    Waehlt fuer ein Rang-Label am Punkt (x_daten, y_daten) einen Offset aus
    _LABEL_OFFSET_KANDIDATEN, der nicht mit bereits platzierten Labels
    kollidiert (Pixelabstand < _LABEL_KOLLISIONS_SCHWELLE_PX).

    Grund: liegen zwei Orte im Datensatz nah beieinander (z.B. zwei
    Aufenthaltsorte an derselben Strasse), ueberdecken sich bei einem festen
    Offset sowohl die Punkte als auch ihre Rang-Zahlen. Kollisionspruefung
    in Pixelkoordinaten (ax.transData), nicht in Metern, weil die visuelle
    Ueberlappung vom Massstab der Karte abhaengt, nicht vom Datenabstand.

    Rueckgabe: (dx, dy) in Punkten (fuer xytext) sowie die neue Liste
    bereits_platziert_px (Seiteneffekt: der gewaehlte Ankerpunkt wird
    angehaengt, damit nachfolgende Labels dagegen pruefen).
    """
    x_px, y_px = ax.transData.transform((x_daten, y_daten))

    def _kollidiert(dx, dy):
        lx, ly = x_px + dx, y_px + dy
        return any(((lx - px) ** 2 + (ly - py) ** 2) ** 0.5 < _LABEL_KOLLISIONS_SCHWELLE_PX
                  for px, py in bereits_platziert_px)

    for dx, dy in _LABEL_OFFSET_KANDIDATEN:
        if not _kollidiert(dx, dy):
            bereits_platziert_px.append((x_px + dx, y_px + dy))
            return dx, dy

    # Alle Kandidaten kollidieren (sehr dichter Cluster, >8 Orte an
    # praktisch derselben Stelle) - den nehmen, der am weitesten von allen
    # bereits platzierten Labels entfernt ist, statt stur beim Standard zu
    # bleiben.
    dx, dy = max(
        _LABEL_OFFSET_KANDIDATEN,
        key=lambda o: min(((x_px + o[0] - px) ** 2 + (y_px + o[1] - py) ** 2) ** 0.5
                          for px, py in bereits_platziert_px))
    bereits_platziert_px.append((x_px + dx, y_px + dy))
    return dx, dy


def _karte(ax, orte_bewertet, top_flach):
    """Hintergrund: Kartenkacheln (falls verfuegbar) + alle erfassten Orte
    grau (Kontext). Vordergrund: Top-Orte farbig nach Sonnendosis +
    Rangnummer (dieselbe Nummer wie in der Tabelle).

    Rueckgabe: True, wenn der Kartenhintergrund geladen werden konnte -
    steuert, ob die Kachel-Attribution in der Fusszeile erscheint."""
    orte_bewertet.geometry.centroid.plot(ax=ax, color="#bbbbbb", markersize=10, zorder=1)

    mp = _mittelpunkt_metrisch()
    if mp is not None:
        kreis = Circle(mp, RADIUS_M, fill=False, edgecolor="#999999",
                       linestyle="--", linewidth=1, zorder=1)
        ax.add_patch(kreis)
        ax.set_xlim(mp[0] - RADIUS_M * 1.1, mp[0] + RADIUS_M * 1.1)
        ax.set_ylim(mp[1] - RADIUS_M * 1.1, mp[1] + RADIUS_M * 1.1)

    label_positionen_px = []  # bereits vergebene Label-Ankerpunkte in Pixeln,
                              # fuer die Kollisionspruefung nachfolgender Labels
    for _, r in top_flach.iterrows():
        c = r.geometry.centroid
        ax.scatter([c.x], [c.y], s=90, color=_farbe(r["sonnendosis"]),
                  edgecolor="#222", linewidth=0.8, zorder=3)
        offset = _naechster_freier_offset(ax, c.x, c.y, label_positionen_px)
        ax.annotate(str(int(r["rang"])), (c.x, c.y), textcoords="offset points",
                   xytext=offset, fontsize=8, fontweight="bold", color="#111", zorder=4)

    # Basiskarte NACH allen datengetriebenen xlim/ylim-Aenderungen einfuegen,
    # sonst rechnet contextily die Achsen von den Punkten aus neu statt vom
    # oben gesetzten Kartenausschnitt (bei mp is None: vom Autoscale ueber
    # alle geplotteten Orte). zorder=0, damit die Kachel unter allem liegt.
    basemap_ok = False
    if _CONTEXTILY_VERFUEGBAR:
        try:
            cx.add_basemap(ax, crs=CRS_METRISCH, source=_BASEMAP_SOURCE,
                           zoom=_BASEMAP_ZOOM, attribution=False, zorder=0)
            basemap_ok = True
        except Exception as e:
            print(f"  Warnung: Kartenhintergrund nicht geladen ({e}). "
                 f"Vorlage wird ohne Basiskarte erstellt (z.B. kein Internetzugriff).")
    else:
        print("  Hinweis: contextily nicht installiert (pip install contextily) - "
             "Vorlage wird ohne Kartenhintergrund erstellt.")

    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    _nordpfeil(ax)
    nett = 100 if RADIUS_M <= 1000 else 500
    _skalenbalken(ax, nett)

    legende = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#1a9641",
              markeredgecolor="#222", markersize=9, label="schattig (Dosis niedrig)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#d7191c",
              markeredgecolor="#222", markersize=9, label="sonnig (Dosis hoch)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#bbbbbb",
              markeredgecolor="#bbbbbb", markersize=6, label="alle erfassten Orte"),
    ]
    ax.legend(handles=legende, loc="lower right", fontsize=7, framealpha=0.9)
    return basemap_ok


def _koordinaten_text(punkte_metrisch):
    """GeoSeries von Punkten in CRS_METRISCH -> dict {index: "lat, lon"-Text}
    in WGS84, gerundet auf 5 Nachkommastellen (~1 m Genauigkeit) - copy-paste-
    faehig fuer Google Maps o.ae."""
    punkte_wgs84 = gpd.GeoSeries(punkte_metrisch, crs=CRS_METRISCH).to_crs(CRS_WGS84)
    return {i: f"{p.y:.5f}, {p.x:.5f}" for i, p in zip(punkte_metrisch.index, punkte_wgs84)}


def _strassennamen_ergaenzen(top_flach, graph=None):
    """
    Fuer Orte ohne Namen: naechstgelegene Kante im Geh-Graphen (loader.py)
    nachschlagen und deren Strassenname als zweite Zeile im Namensfeld
    anzeigen. Ergaenzt top_flach um die Spalte "anzeige_name".

    Zwei-stufiger Fallback:
      1. naechste Kante hat ein 'name'-Tag -> Strassenname
      2. naechste Kante ist selbst unbenannt (z.B. unbenannter Fussweg/
         Parkplatzweg) ODER die Kantensuche schlaegt insgesamt fehl
         -> WGS84-Koordinaten statt gar nichts. Reines "(ohne Name)" ohne
         jede weitere Angabe ist damit kein Endzustand mehr, sondern nur
         ein Zwischenschritt, falls beide Stufen leer bleiben (sollte nicht
         vorkommen, da Stufe 2 keine externen Abhaengigkeiten hat).

    graph : bereits geladener, auf CRS_METRISCH projizierter Geh-Graph
            (loader.lade_geh_graph()). None -> wird nur bei Bedarf selbst
            geladen (Cache-Hit ist schnell, aber unnoetig, wenn ohnehin alle
            Orte einen Namen haben).
    """
    top_flach = top_flach.reset_index(drop=True)
    fehlend_idx = [i for i, n in enumerate(top_flach["name"]) if not n]

    # Stufe 1: Strassenname der naechstgelegenen Kante im Geh-Graphen
    strassen = {}
    if fehlend_idx:
        if graph is None:
            from modules.loader import lade_geh_graph
            graph = lade_geh_graph()
        import osmnx as ox

        punkte = top_flach.loc[fehlend_idx].geometry.centroid
        try:
            kanten = ox.distance.nearest_edges(graph, punkte.x.values, punkte.y.values)
            for i, (u, v, k) in zip(fehlend_idx, kanten):
                daten = graph.get_edge_data(u, v, k) or {}
                name = daten.get("name")
                if isinstance(name, list):          # OSM: mehrere Namen auf einer Kante
                    name = name[0] if name else None
                if name:
                    strassen[i] = name
            print(f"  Strassennamen fuer unbenannte Orte: {len(strassen)} von "
                 f"{len(fehlend_idx)} gefunden (naechstgelegene Kante im Geh-Graphen).")
        except Exception as e:
            print(f"  Warnung: Strassennamen konnten nicht ermittelt werden ({e}). "
                 f"Tabelle zeigt fuer unbenannte Orte Koordinaten statt Strassennamen.")

    # Stufe 2: Koordinaten fuer alle, die nach Stufe 1 immer noch keinen
    # Namen haben (unbenannte naechste Kante ODER Kantensuche fehlgeschlagen)
    koord_noetig = [i for i in fehlend_idx if i not in strassen]
    koordinaten = {}
    if koord_noetig:
        punkte = top_flach.loc[koord_noetig].geometry.centroid
        koordinaten = _koordinaten_text(punkte)
        anzahl_ueber_stufe2 = len(koordinaten)
        if anzahl_ueber_stufe2:
            print(f"  Koordinaten-Fallback (Stufe 2) fuer {anzahl_ueber_stufe2} Ort(e) "
                 f"ohne Strassenname noch in Reichweite verwendet.")

    anzeige = []
    for i, r in top_flach.iterrows():
        if r["name"]:
            anzeige.append(r["name"])
        elif i in strassen:
            anzeige.append(f"(ohne Name)\n{strassen[i]}")
        elif i in koordinaten:
            anzeige.append(f"(ohne Name)\n{koordinaten[i]}")
        else:
            anzeige.append("(ohne Name)")
    top_flach["anzeige_name"] = anzeige
    return top_flach


def _tabelle(ax, top_flach):
    """Tabelle rechts: Rang, Aufenthaltsart, Name, Dosis, Gewicht, Dringlichkeit -
    dieselbe Reihenfolge/Nummerierung wie auf der Karte. Name-Spalte nutzt
    "anzeige_name" (ggf. zweizeilig: "(ohne Name)" + Strasse/Koordinaten
    darunter, siehe _strassennamen_ergaenzen)."""
    ax.axis("off")
    spalten = ["Nr.", "Aufenthaltsart", "Name", "Dosis", "Gewicht", "Dringlichkeit"]
    zeilen = []
    for _, r in top_flach.iterrows():
        zeilen.append([
            str(int(r["rang"])), r["kategorie"], r["anzeige_name"],
            f"{r['sonnendosis']:.2f}", f"{r['gewicht']:.1f}", f"{r['dringlichkeit']:.2f}",
        ])
    tab = ax.table(cellText=zeilen, colLabels=spalten, loc="upper left", cellLoc="left")
    tab.auto_set_font_size(False)
    tab.set_fontsize(8)
    tab.auto_set_column_width(col=list(range(len(spalten))))
    tab.scale(1, 1.35)
    for (row, _col), cell in tab.get_celld().items():
        if row == 0:
            cell.set_text_props(fontweight="bold")
            cell.set_facecolor("#e8e8e8")
        elif "\n" in zeilen[row - 1][2]:
            # zweizeiliger Name (ohne Name) + Strasse/Koordinaten: Zeile
            # hoeher, sonst ueberlappt die zweite Zeile die naechste
            # Tabellenzeile
            cell.set_height(cell.get_height() * 1.8)


def exportiere_vorlage(orte_bewertet, ranglisten, pfad=None, top_je_kategorie=3, graph=None):
    """
    EIN layoutfertiges PDF (A4 quer): Karte mit nummerierten Top-Orten links,
    Tabelle rechts (dieselben Nummern) - fuer die Gemeinderatsvorlage.

    orte_bewertet    : GeoDataFrame aus bewerte_orte() (Kartenhintergrund,
                       alle Orte grau)
    ranglisten       : dict {kategorie: DataFrame} aus rangliste()
    top_je_kategorie : wie viele Orte je Kategorie auf Karte + Tabelle landen
                       (kann kleiner sein als in ranglisten enthalten, um die
                       Seite nicht zu ueberfuellen - bei 6 Kategorien ergeben
                       3 schon bis zu 18 Zeilen)
    graph            : optional bereits geladener Geh-Graph (loader.
                       lade_geh_graph()) fuer die Strassennamen unbenannter
                       Orte. None -> wird nur bei Bedarf selbst geladen.
    """
    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "vorlage_top_orte.pdf")

    # Eine flache Tabelle ueber alle Kategorien, mit durchgehender Rangnummer -
    # dieselbe Nummer auf der Karte und in der Tabelle.
    teile = [ranglisten[kat].head(top_je_kategorie) for kat in sorted(ranglisten.keys())]
    top_flach = pd.concat(teile, ignore_index=True) if teile else orte_bewertet.iloc[0:0]
    top_flach["rang"] = top_flach.index + 1
    top_flach = _strassennamen_ergaenzen(top_flach, graph=graph)

    fig = plt.figure(figsize=(11.69, 8.27))  # A4 quer
    gs = fig.add_gridspec(2, 2, width_ratios=[1.15, 1], height_ratios=[0.12, 1],
                          hspace=0.05, wspace=0.03)

    ax_titel = fig.add_subplot(gs[0, :])
    ax_titel.axis("off")
    zeitfenster = f"{DATUM}, {AGG_START_STUNDE:02d}-{AGG_END_STUNDE:02d} Uhr (Tagesmittel)"
    ax_titel.text(0, 0.8, "Stadtschatten - Verschattungsbedarf: Top-Orte je Aufenthaltsart",
                 fontsize=15, fontweight="bold", va="top")
    ax_titel.text(0, 0.45, "(Nathalie Gassert)",
                 fontsize=9, color="#444", va="top")
    ax_titel.text(0, 0.15,
                 f"{PLACE}  |  Zeitfenster: {zeitfenster}  |  Dringlichkeit = Sonnendosis "
                 f"x Gewicht je Aufenthaltsart (fachliche Gewichtung, siehe Anlage)  |  "
                 f"erstellt {datetime.now():%d.%m.%Y}",
                 fontsize=9, color="#444", va="top")

    ax_karte = fig.add_subplot(gs[1, 0])
    basemap_ok = _karte(ax_karte, orte_bewertet, top_flach)

    ax_tab = fig.add_subplot(gs[1, 1])
    _tabelle(ax_tab, top_flach)

    attribution_teile = [
        "Datenquelle Verschattung: LGL, www.lgl-bw.de",
        "Aufenthaltsorte: (c) OpenStreetMap-Mitwirkende",
    ]
    if basemap_ok:
        attribution_teile.append(f"Kartenhintergrund: {_BASEMAP_ATTRIBUTION}")
    attribution_teile.append(
        "OSM kennt fuer manche Orte keinen Namen; Koordinaten dienen der "
        "Identifikation vor Ort."
    )
    attribution_teile.append(
        "Screening-Ebene: Momentaufnahme fuer das genannte Zeitfenster, "
        "kein Ersatz fuer eine Einzelfallpruefung."
    )
    fig.text(0.01, 0.01, "  |  ".join(attribution_teile), fontsize=7, color="#666")

    fig.savefig(pfad, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Vorlage gespeichert: {pfad}  ({len(top_flach)} Orte)")
    return pfad


if __name__ == "__main__":
    from modules.loader import _analyse_gebiet_25832, lade_geh_graph
    from modules.nutzung import lade_dosis_tif
    from modules.aufenthalt import lade_aufenthaltsorte, bewerte_orte, rangliste

    dosis, transform, nodata = lade_dosis_tif()
    orte = lade_aufenthaltsorte()
    orte_bewertet = bewerte_orte(orte, dosis, transform, nodata)
    ranglisten = rangliste(orte_bewertet)
    graph = lade_geh_graph()
    exportiere_vorlage(orte_bewertet, ranglisten, graph=graph)