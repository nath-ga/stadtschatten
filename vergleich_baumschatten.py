import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from modules.loader import lade_geh_graph, lade_gebaeude_mit_hoehe, lade_hindernisse
from modules.kantenbewertung import bewerte_kanten_aggregiert, karte_kanten

stunden = range(config.AGG_START_STUNDE, config.AGG_END_STUNDE + 1)

# ohne Baumschatten: nur Gebaeude, Vegetation gar nicht erst laden
G = lade_geh_graph()
gebaeude = lade_gebaeude_mit_hoehe()
G, edges_ohne = bewerte_kanten_aggregiert(G, gebaeude, stunden)
karte_kanten(edges_ohne, pfad="output/denkendorf/ohnebaumschatten.html")

# mit Baumschatten: Gebaeude + Vegetation (VEG_AKTIV ist bereits True in config.py)
G2 = lade_geh_graph()
hindernisse = lade_hindernisse()
G2, edges_mit = bewerte_kanten_aggregiert(G2, hindernisse, stunden)
karte_kanten(edges_mit, pfad="output/denkendorf/mitbaumschatten.html")