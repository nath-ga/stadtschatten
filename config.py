# stadtschatten/config.py
#
# Zentrale Parameter — hier änderst du, WAS gerechnet wird:
# Ort, Zeitpunkt des Schattenwurfs, Routing-Verhalten.
# Modell-Feintuning (Höhenannahmen) liegt bewusst in den Modulen, nicht hier.

# ------------------------------------------------------------------
# Ort (OpenStreetMap-kompatibel)
# ------------------------------------------------------------------
# PLACE    = "Stuttgart-West, Stuttgart, Deutschland"
# PLACE    = "Esslingen, Esslingen, Deutschland"
# PLACE    = "Maichingen, Sindelfingen, Deutschland"
PLACE    = "Denkendorf, Denkendorf, Deutschland"

LGL_KACHEL_UNTERORDNER = "denkendorf"   # Unterordner in data/ mit den LGL-Kacheln dieses Laufs

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
OUTPUT_DIR = "output"    # Ergebnisse: Karten, GPX (gitignored)


def get_zeitpunkt():
    """DATUM + UHRZEIT + ZEITZONE als tz-bewussten Timestamp (für pybdshadow)."""
    import pandas as pd
    return pd.Timestamp(f"{DATUM} {UHRZEIT}", tz=ZEITZONE)

def get_zeitpunkt_stunde(stunde):
    """DATUM + volle Stunde + ZEITZONE als tz-bewussten Timestamp (für die Aggregation).
    stunde : ganze Zahl, z.B. 11 -> 11:00 am DATUM. Minuten sind hier immer 00."""
    import pandas as pd
    return pd.Timestamp(f"{DATUM} {stunde:02d}:00", tz=ZEITZONE)