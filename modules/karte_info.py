# stadtschatten/modules/karte_info.py
#
# Fuegt einer folium-Karte eine feste Info-Box hinzu:
#   - mit welchen Werten der Lauf lief (Datum/Uhrzeit, Alpha, Gebiet ...)
#   - Quellenangaben (LGL ist Pflicht, sobald LGL-Daten genutzt werden; OSM dazu)
#
# Aufruf direkt vor m.save(...):
#   from modules.karte_info import info_box
#   info_box(m, {"Datum/Uhrzeit": "...", "Gewichtung Alpha": 3, "Radius": "800 m"})

import folium

QUELLE_LGL = "Datenquelle: LGL, www.lgl-bw.de"
QUELLE_OSM = "Kartendaten (c) OpenStreetMap-Mitwirkende"


def info_box(m, parameter, quellen=(QUELLE_LGL, QUELLE_OSM), titel="Stadtschatten"):
    """
    m         : folium.Map
    parameter : dict {Bezeichnung: Wert} - die Werte, mit denen der Lauf lief
    quellen   : Liste von Quellenangaben
    """
    zeilen = "".join(f"<div><b>{k}:</b> {v}</div>" for k, v in parameter.items())
    quellen_html = "".join(f"<div>{q}</div>" for q in quellen)
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