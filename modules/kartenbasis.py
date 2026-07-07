# stadtschatten/modules/kartenbasis.py
#
# Zentrale Stelle fuer den Karten-Hintergrund aller Folium-Ausgaben.
#
# Ersetzt den frueher in sechs Modulen einzeln kopierten Esri-World-Imagery-
# Satelliten-Layer (aufenthalt.py, exposition.py, kantenbewertung.py,
# nutzung.py x2, schatten.py). Grund fuer die Entfernung: Esri erlaubt die
# kostenlose Nutzung von World Imagery nur fuer "Noncommercial Use" (keine
# Einnahmen, kein "commercial advantage"). Da die Karten oeffentlich ueber
# GitHub Pages gehostet werden und Teil eines Akquise-Portfolios sind, ist
# nicht eindeutig geklaert, ob das noch darunter faellt -- siehe ablauf.md.
#
# Ab jetzt: EINE Stelle fuer den Kartenhintergrund. Aendert sich die
# Entscheidung nochmal (z.B. eigene Esri-Lizenz), reicht eine Aenderung hier.

import folium


def basis_layer(m, max_zoom=19):
    """Fuegt den Standard-Kartenhintergrund hinzu (CartoDB Positron).

    Bisher wurde in jedem Modul zusaetzlich ein zweiter, abschaltbarer
    Esri-World-Imagery-Layer eingebunden ("Satellit"). Der faellt hier
    ersatzlos weg -- kein Ersatz-Layer, da CartoDB/OSM bereits das ist,
    was in vorlage.py schon bewusst als lizenzrechtlich unproblematisch
    gewaehlt wurde.

    Parameter
    ---------
    m : folium.Map
        Die Karte, der der Layer hinzugefuegt wird.
    max_zoom : int
        Vorher pro Modul unterschiedlich gesetzt (19 bis 22). Beim Einbau
        in ein bestehendes Modul: nachschauen, welchen max_zoom die alte
        CartoDB-Zeile dort hatte (falls gesetzt) und hier uebergeben, damit
        sich am Zoom-Verhalten nichts aendert. Ohne Angabe: 19 (Folium-
        Standard fuer CartoDB Positron).

    Rueckgabe
    ---------
    m : folium.Map
        Dieselbe Karte, fuer Verkettung (m = basis_layer(m)) nicht noetig,
        aber praktisch falls gewuenscht.
    """
    folium.TileLayer("CartoDB positron", name="Karte", max_zoom=max_zoom).add_to(m)
    return m