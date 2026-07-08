# stadtschatten/modules/karte_info.py
#
# Fuegt einer folium-Karte eine feste Info-Box hinzu:
#   - mit welchen Werten der Lauf lief (Datum/Uhrzeit, Alpha, Gebiet ...)
#   - Quellenangaben (LGL ist Pflicht, sobald LGL-Daten genutzt werden; OSM dazu)
#
# Aufruf direkt vor m.save(...):
#   from modules.karte_info import info_box
#   info_box(m, {"Datum/Uhrzeit": "...", "Gewichtung Alpha": 3, "Radius": "800 m"})

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import folium
import geopandas as gpd

from config import CRS_METRISCH, CRS_WGS84

QUELLE_LGL = "Datenquelle: LGL, www.lgl-bw.de"
QUELLE_OSM = "Kartendaten (c) OpenStreetMap-Mitwirkende"
AUTOR = "© Nathalie Gassert · Stadtschatten · github.com/nath-ga/stadtschatten"


def info_box(m, parameter, quellen=(QUELLE_LGL, QUELLE_OSM), titel="Stadtschatten"):
    """
    m         : folium.Map
    parameter : dict {Bezeichnung: Wert} - die Werte, mit denen der Lauf lief
    quellen   : Liste von Quellenangaben

    Die Namensnennung (AUTOR) wird IMMER angehaengt, unabhaengig davon, was
    fuer `quellen` uebergeben wird - so kann sie nicht versehentlich
    wegfallen, wenn ein Aufruf eine eigene, kuerzere quellen-Liste nutzt.
    """
    zeilen = "".join(f"<div><b>{k}:</b> {v}</div>" for k, v in parameter.items())
    quellen_html = "".join(f"<div>{q}</div>" for q in (*quellen, AUTOR))
    html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: rgba(255,255,255,0.92); padding: 10px 12px;
                border: 1px solid #888; border-radius: 6px;
                font: 12px/1.45 sans-serif; color: #222; max-width: 320px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3);">
      <div style="font-weight:bold; margin-bottom:4px;">{titel}</div>
      {zeilen}
      <div style="margin-top:6px; color:#555; font-size:11px;">{quellen_html}</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(html))
    return m


def rangliste_box(m, ranglisten, titel="Dringlichkeit je Aufenthaltsart"):
    """
    Ein-/ausklappbares Kaestchen mit der gewichteten Rangliste
    (Dringlichkeit = Sonnendosis * Gewicht), ein Abschnitt je Kategorie.

    Technisch ein ECHTES Leaflet-Control (wie folium.LayerControl), keine
    freischwebende position:fixed-Box mehr - dadurch reiht es sich in
    dieselbe Ecke (oben rechts) UNTER der Ebenen-Auswahl ein, statt sie zu
    verdecken. Klappt man die Ebenen-Auswahl auf, wird diese Box automatisch
    mit nach unten verschoben (Leaflet stapelt Controls in derselben Ecke
    von selbst). Startet eingeklappt (nur Titelzeile), Klick klappt auf/zu.

    WICHTIG: erst NACH folium.LayerControl(...).add_to(m) aufrufen, sonst
    landet es ueber statt unter der Ebenen-Auswahl.

    m          : folium.Map
    ranglisten : dict {kategorie: DataFrame[name, sonnendosis, gewicht,
                 dringlichkeit]} — Rueckgabe von modules.aufenthalt.rangliste()
    """
    abschnitte = []
    for kat, df in ranglisten.items():
        if df.empty:
            continue

        # Fuer unbenannte Orte Koordinaten statt "(ohne Name)" ohne jede
        # weitere Angabe - sonst ist die Zeile in der Rangliste nicht vom
        # Popup auf der Karte auffindbar (gleicher Fallback wie in
        # aufenthalt.py karte_aufenthalt() und vorlage.py, hier auf Basis
        # der Geometrie in df, die noch in CRS_METRISCH vorliegt).
        fehlt = df["name"].isna() | (df["name"] == "")
        koordinaten = {}
        if fehlt.any():
            punkte_wgs84 = gpd.GeoSeries(
                df.loc[fehlt].geometry.centroid, crs=CRS_METRISCH).to_crs(CRS_WGS84)
            koordinaten = {i: f"{p.y:.5f}, {p.x:.5f}"
                          for i, p in zip(df.loc[fehlt].index, punkte_wgs84)}

        def _anzeige(idx, r):
            if r["name"]:
                return r["name"]
            return f"(ohne Name) {koordinaten.get(idx, '')}"

        zeilen = "".join(
            f"<div>{i + 1}. {_anzeige(idx, r)} "
            f"<span style='color:#555'>({r['dringlichkeit']:.2f})</span></div>"
            for i, (idx, r) in enumerate(df.iterrows())
        )
        gewicht = df["gewicht"].iloc[0]
        abschnitte.append(
            f"<div style='margin-top:8px'><b>{kat}</b> "
            f"<span style='color:#555; font-size:11px;'>(Gewicht {gewicht:.1f})</span>"
            f"{zeilen}</div>")
    inhalt_html = "".join(abschnitte)

    # json.dumps() statt f-string-Interpolation fuer die JS-Strings: Ortsnamen
    # aus OSM koennen Anfuehrungszeichen o.ae. enthalten, json.dumps escaped
    # das korrekt (sicherer als selbst Quotes zaehlen).
    inhalt_js = json.dumps(inhalt_html)
    titel_zu_js = json.dumps("▸ " + titel)      # ▸ eingeklappt
    titel_auf_js = json.dumps("▾ " + titel)     # ▾ aufgeklappt

    # WICHTIG: window.addEventListener('load', ...) statt direkt ausfuehren.
    # Dieses <script>-Tag landet im HTML-Teil der Seite, VOR dem Skript, das
    # die eigentliche Karte erzeugt (var map_xxx = L.map(...) steht weiter
    # unten in einem separaten <script>-Block). Ohne den Umweg ueber 'load'
    # wuerde map_xxx beim Ausfuehren noch gar nicht existieren
    # (ReferenceError, Box bliebe unsichtbar - nicht nur falsch platziert).
    script = f"""
    <script>
    window.addEventListener('load', function() {{
        var box = document.createElement('div');
        box.className = 'leaflet-control rangliste-box';
        box.style.background = 'rgba(255,255,255,0.95)';
        box.style.border = '1px solid #888';
        box.style.borderRadius = '6px';
        box.style.font = '12px/1.4 sans-serif';
        box.style.color = '#222';
        box.style.maxWidth = '280px';
        box.style.boxShadow = '0 1px 4px rgba(0,0,0,0.3)';
        box.style.marginTop = '10px';
        box.style.marginRight = '10px';

        var kopf = document.createElement('div');
        kopf.style.padding = '6px 10px';
        kopf.style.cursor = 'pointer';
        kopf.style.fontWeight = 'bold';
        kopf.textContent = {titel_zu_js};

        var inhalt = document.createElement('div');
        inhalt.style.padding = '0 10px 8px 10px';
        inhalt.style.maxHeight = '60vh';
        inhalt.style.overflowY = 'auto';
        inhalt.style.display = 'none';
        inhalt.innerHTML = {inhalt_js};

        var offen = false;
        kopf.onclick = function() {{
            offen = !offen;
            inhalt.style.display = offen ? 'block' : 'none';
            kopf.textContent = offen ? {titel_auf_js} : {titel_zu_js};
        }};

        box.appendChild(kopf);
        box.appendChild(inhalt);

        var eck = {m.get_name()}._controlCorners['topright'];
        eck.appendChild(box);

        // Klicks/Scrollen im Kaestchen nicht an die Karte weiterreichen
        // (sonst zoomt/verschiebt sie sich beim Klicken in die Liste).
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(script))
    return m