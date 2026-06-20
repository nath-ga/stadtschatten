# stadtschatten/run.py
#
# Einstiegspunkt: verkettet alle Module zu einem Durchlauf.
# Aufruf aus dem Projektordner:  python run.py
#
# Was eingestellt wird, steht zentral in config.py
# (Ort/Gebiet, Datum, Uhrzeit, Start/Ziel, ALPHA).

import warnings
# Kosmetische Warnungen aus pybdshadow/pyproj unterdrücken (kein Fehler, nur Rauschen).
# Beim Entwickeln einzelner Module erscheinen sie weiterhin.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from config import PLACE, ZENTRUM, RADIUS_M, get_zeitpunkt
from modules.loader import lade_geh_graph, lade_gebaeude_mit_hoehe
from modules.schatten import berechne_schatten, karte_schatten
from modules.kantenbewertung import bewerte_kanten, karte_kanten
from modules.routing import vergleiche_routen, karte_route

# Schalter für die A->B-Route (schnellster vs. schattigster Weg).
# Für die Hitzeexpositions-Auswertung NICHT nötig -> standardmäßig aus.
# Auf True setzen, wenn du zusätzlich route.html erzeugen willst. ggf start/ziel in config eintragen
ROUTE_BERECHNEN = False


def main():
    gebiet = f"{RADIUS_M} m um {ZENTRUM}" if ZENTRUM else PLACE
    print(f"Stadtschatten\n  Gebiet:    {gebiet}\n  Zeitpunkt: {get_zeitpunkt()}\n")

    print("1/3  Daten laden ...")
    G = lade_geh_graph()
    gebaeude = lade_gebaeude_mit_hoehe()

    print("2/3  Schatten berechnen ...")
    schatten = berechne_schatten(gebaeude)

    print("3/3  Kanten bewerten ...")
    G, edges = bewerte_kanten(G, schatten)

    print("\nKarten schreiben ...")
    karte_schatten(gebaeude, schatten)
    karte_kanten(edges, schatten)

    if ROUTE_BERECHNEN:
        print("\nOptional: Route (schnellster vs. schattigster Weg) ...")
        routen = vergleiche_routen(G)
        karte_route(G, routen)

    print("\nFertig. Ergebnisse im Ordner 'output/':")
    print("  schatten_check.html        – Gebäude + Schatten (Validierung)")
    print("  kanten_sonnenanteil.html   – Wegenetz nach Sonnenanteil (die Auswertung)")
    if ROUTE_BERECHNEN:
        print("  route.html                 – schnellster vs. schattigster Weg")


if __name__ == "__main__":
    main()