# stadtschatten/config.py
#
# Zentrale Parameter — hier änderst du, WAS gerechnet wird:
# Ort, Zeitpunkt des Schattenwurfs, Routing-Verhalten.
# Modell-Feintuning (Höhenannahmen) liegt bewusst in den Modulen, nicht hier.

import os 

# ------------------------------------------------------------------
# Ort (OpenStreetMap-kompatibel)
# ------------------------------------------------------------------
# PLACE    = "Stuttgart-West, Stuttgart, Deutschland"
# PLACE    = "Esslingen, Esslingen, Deutschland"
# PLACE    = "Maichingen, Sindelfingen, Deutschland"
PLACE    = "Denkendorf, Denkendorf, Deutschland"

LGL_KACHEL_UNTERORDNER = "denkendorf"   # Unterordner in data/ mit den LGL-Kacheln dieses Laufs
ORT_SLUG   = "denkendorf"                       # Kurzname des aktiven Orts
OUTPUT_DIR = os.path.join("output", ORT_SLUG)   # output/<ort>/ – Karten je Ort getrennt

# ------------------------------------------------------------------
# Testgebiet-Zuschnitt (optional)
# ------------------------------------------------------------------
# ZENTRUM gesetzt -> es wird NUR ein Kreis um diesen Punkt geladen.
#   Schnell, dicht, ideal zum Entwickeln. Umgeht auch das Grenz-/
#   Geocoding-Problem von Stadtteilen ("Altstadt" findet OSM nicht).
# ZENTRUM = None -> der ganze Ort (PLACE) wird geladen.
#
# Mittelpunkt als (lat, lon). Hier: Esslinger Altstadt (ungefähr).
# Feineinstellung: in OpenStreetMap.org den Punkt rechtsklicken ->
# die Koordinaten stehen dann oben in der URL.
# ZENTRUM  = (48.7758, 9.1550) # Stuttgart west
# RADIUS_M = 600

# ZENTRUM = (48.7440, 9.2998)   # (Breite, Länge) mitte Esslingen
# RADIUS_M = 800
# ZENTRUM = None

ZENTRUM = (48.69806, 9.31750)     # (lat, lon)
RADIUS_M = 800

# ------------------------------------------------------------------
# Zeitpunkt des Schattenwurfs
# ------------------------------------------------------------------
# WICHTIG: Der Schatten gilt NUR für diesen Moment. "Schattigster Weg
# um 14 Uhr" ist um 16 Uhr ein anderer. Eigenschaft des Modells,
# kein Fehler — muss dem Nutzer klar kommuniziert werden.
DATUM    = "2026-06-18"      # ISO, YYYY-MM-DD
UHRZEIT = "15:00"           # HH:MM, Ortszeit
ZEITZONE = "Europe/Berlin"

# ------------------------------------------------------------------
# Zeit-Aggregation ("Sonnendosis") – nur für die Expositionskarte
# ------------------------------------------------------------------
# True  -> kanten_sonnenanteil mittelt über das Fenster unten (stündlich).
#          UHRZEIT oben gilt dann NUR noch für schatten_check.html.
# False -> Einzelmoment wie bisher (UHRZEIT).
AGG_AKTIV       = True
AGG_START_STUNDE = 11    # erste Stunde (einschließlich)
AGG_END_STUNDE   = 18    # letzte Stunde – siehe Frage unten
AGG_RASTER_M = 2.0

# ------------------------------------------------------------------
# Vegetation / Baumschatten (nDOM1)
# ------------------------------------------------------------------
NDOM_KACHEL_UNTERORDNER = "denkendorf"   # Unterordner in data/ mit den nDOM-Kacheln
VEG_MIN_HOEHE      = 3.0    # ab dieser Höhe schattenrelevant (m)
GEB_PUFFER_M       = 1.0    # Gebäude-Footprints aufpuffern (Wandkranz wegputzen)
VEG_MIN_FLAECHE_M2 = 4.0    # Mindestfläche je Vegetationspolygon (Krümel raus)

VEG_AKTIV = True    # False -> nur Gebäudeschatten (zum Vergleich/außerhalb BW) / True mit Bäumen

# ------------------------------------------------------------------
# Routing
# ------------------------------------------------------------------
# Start/Ziel als (lat, lon). Für v1 hier eintragen.
START = None
# START = 48.72530274948598, 8.96341614534037
ZIEL  = None
# ZIEL  = 48.719097997569925, 8.971230842805964

# Umschalter schattigster vs. schnellster Weg über die Kantengewichtung:
#   w = laenge * (1 + ALPHA * sonnenanteil)
#   ALPHA = 0   -> schnellster Weg (Schatten egal)
#   ALPHA hoch  -> schattigster Weg (Umwege werden in Kauf genommen)
ALPHA_SCHATTIG = 15.0
ALPHA_SCHNELL  = 0.0

# ------------------------------------------------------------------
# Koordinatensysteme
# ------------------------------------------------------------------
CRS_METRISCH = 25832   # ETRS89/UTM32N — BW, identisch mit LGL-Daten
CRS_WGS84    = 4326    # pybdshadow erwartet lon/lat

# ------------------------------------------------------------------
# Pfade
# ------------------------------------------------------------------
DATA_DIR   = "data"      # Cache: OSM-Downloads, Graphen (gitignored)

# ------------------------------------------------------------------
# ALKIS-Flurstücke (tatsächliche Nutzung)
# ------------------------------------------------------------------
ALKIS_FLURSTUECK_PFAD = "data/denkendorf/flurstueck.shp"  
MIN_FREIFLAECHE_M2 = 20.0   # Flurstück nur bewertbar, wenn nach Dach-Abzug so viel frei

# ------------------------------------------------------------------
# Detail-Lupe eines Flurstücks: (lat, lon) im Flurstück, sonst None
# ------------------------------------------------------------------
DETAIL_PUNKT_LATLON = None
# DETAIL_PUNKT_LATLON = (48.694808, 9.314938) # Beispiel Denkendorf Weingartstr. 1/1

# ------------------------------------------------------------------
# Karten-Rendering (folium)
# ------------------------------------------------------------------
# Gemeinsamer Zoom-Deckel fuer alle drei Auswertungskarten (exposition,
# nutzung, aufenthalt). Zweck: Nutzer nicht weiter reinzoomen lassen, als
# tatsaechlich Bildinformation da ist - sonst wird es nur eine haesslich
# hochskalierte Kachel (Esri World Imagery) bzw. sichtbar klotzige
# Rasterzellen (die 2m-Sonnendosis, ab ~19 blockig).
# Handempirisch pruefen: im Browser auf die Satellit-Ebene stellen, in
# Denkendorf so weit reinzoomen bis Kacheln nicht mehr schaerfer werden
# (DevTools -> Network: gleiche Kachel wird nur noch hochskaliert) -
# das ist die Zahl hier. Wert gilt je Ort; bei anderer Stadt (dichter
# LGL/Esri-Abdeckung) ggf. hochsetzen.
MAX_ZOOM_KARTE = 19

# ------------------------------------------------------------------
# Aufenthaltsorte (OSM)
# ------------------------------------------------------------------
AUFENTHALT_PUNKT_PUFFER_M = 5.0   # Punkt (z.B. Haltestelle) -> Wartebereich-Radius
BUSHALT_DEDUP_M = 10.0            # Haltestellen näher als dies = eine (bus_stop+platform)

# ------------------------------------------------------------------
# Gewichtung Aufenthaltsarten (Dringlichkeit = Sonnendosis * Gewicht)
# ------------------------------------------------------------------
# Nicht jeder Aufenthaltsort ist gleich dringlich, wenn dort Schatten fehlt.
# Zwei Kriterien fuer die Gewichte unten: (1) koennen sich die Betroffenen
# der Sonne selbst entziehen (Standortwahl), (2) sind es besonders
# hitzevulnerable Gruppen (kleine Kinder, Pflege/Senioren). Fachliche
# Einschaetzung, keine Norm — im Gemeinderat ggf. offenlegen und begruenden.
AUFENTHALT_GEWICHTUNG = {
    "Kindergarten":        1.5,  # kleine Kinder, ganztags draussen, keine Standortwahl
    "Schule":              1.4,  # viele Kinder, Pausen im Freien, kaum Standortwahl
    "Soziale Einrichtung": 1.4,  # oft Pflege/Senioren, Hitze schlechter regulierbar
    "Spielplatz":          1.2,  # Kinder, aber freiwillige/zeitlich flexible Nutzung
    "Bushaltestelle":      1.1,  # alle Altersgruppen, aber KEINE Standortwahl (Wartepflicht)
    "Sitzbank":            0.8,  # freiwillige Nutzung, Standort meist selbst waehlbar
}
GEWICHT_STANDARD = 1.0   # Fallback fuer nicht gelistete Kategorien (z.B. neue OSM-Tags)

def get_zeitpunkt():
    """DATUM + UHRZEIT + ZEITZONE als tz-bewussten Timestamp (für pybdshadow)."""
    import pandas as pd
    return pd.Timestamp(f"{DATUM} {UHRZEIT}", tz=ZEITZONE)

def get_zeitpunkt_stunde(stunde):
    """DATUM + volle Stunde + ZEITZONE als tz-bewussten Timestamp (für die Aggregation).
    stunde : ganze Zahl, z.B. 11 -> 11:00 am DATUM. Minuten sind hier immer 00."""
    import pandas as pd
    return pd.Timestamp(f"{DATUM} {stunde:02d}:00", tz=ZEITZONE)