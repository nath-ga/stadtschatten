# Stadtschatten

Das Modul berechnet **Schatten von Gebäuden und Bäumen** und bestimmt daraus, welcher Anteil
des städtischen Fußwegenetzes in der Sonne bzw. im Schatten liegt – wahlweise zu einem einzelnen
Zeitpunkt oder **gemittelt über ein Stundenfenster** („Sonnendosis", z. B. 11–18 Uhr).

Daraus ergeben sich zwei Anwendungen:

- **Schattiger Fußweg:** der schattigste statt des schnellsten Weges zwischen zwei Punkten
  (gewichtetes Routing mit stufenlosem Umschalter).
- **Hitzeexpositions-Layer:** sichtbar machen, *wo entlang realer Laufwege* die Sonnenbelastung
  am höchsten ist – also wo Beschattung für Fußgänger am dringendsten gebraucht wird.

Stadtschatten teilt die OpenStreetMap-Datengrundlage mit dem Schwestermodul **Stadtgrün**,
ist aber eigenständig.

Seit v4 kommt eine dritte, planerisch zentrale Auswertung hinzu: die flächige
Verschattung verknüpft mit der tatsächlichen Nutzung (ALKIS-Kataster) und mit
Aufenthaltsorten (Schulen, Kindergärten, Spielplätze, Bushaltestellen aus OSM) – um zu
zeigen, wo Schatten dort fehlt, wo sich Menschen tatsächlich aufhalten.

---

## Funktionsweise

```
1. Laden        Geh-Graph (osmnx) + Hindernisse mit Höhe              → modules/loader.py
                Gebäude (LGL-LoD2, OSM-Fallback) + Vegetation (nDOM)
2. Schatten     Schatten für einen Zeitpunkt (pybdshadow);            → modules/schatten.py
                optional über ein Stundenfenster gemittelt            → modules/kantenbewertung.py
3. Bewertung    Schatten den Wegekanten zuordnen, Sonnenanteil je     → modules/kantenbewertung.py
                Kante (einzeln oder gemittelt), Kantengewichtung
4. Routing      gewichteter kürzester Pfad, schnellster vs. schattigster → modules/routing.py
5. Ausgabe      Folium-Karten (Schatten-Check, Sonnenanteil, Route)
                jeweils mit Lauf-Parametern und Quellenangabe
```

Die Kantenbewertung tastet jede Wegekante in Stützpunkten ab und prüft mit *einem*
räumlichen Verschnitt gegen die vereinigte Schattenfläche, welcher Anteil jeder Kante
beschattet ist. Ergebnis pro Kante: `sonnenanteil` (0 = ganz im Schatten, 1 = volle Sonne)
sowie zwei Gewichte fürs Routing.

---

## Gebäudehöhen (Kern von v2)

Verlässliche Höhen sind die Voraussetzung für belastbare Schattenwerte. Die Höhe wird in
`modules/loader.py` als Fallback-Kette bestimmt:

```
1. LGL-LoD2 (amtlich, gemessen)   ← bevorzugt, innerhalb Baden-Württembergs
2. OSM height
3. OSM building:levels × 3 m
4. Default 6 m (2 Geschosse)
```

Liegen für das Suchgebiet LGL-LoD2-Kacheln vor, werden deren amtliche Footprints und
`measuredHeight` direkt verwendet (Modul `modules/lgl_lod2.py`); andernfalls greift der
OSM-Weg. Die LGL-Kacheln werden als CityGML-Dateien (`LoD2_*.gml`) im Ordner `data/`
erwartet und auf das aktuelle Suchgebiet zugeschnitten.

**Verifiziert am Testgebiet Esslingen (vier 1-km-Kacheln, 3.885 Gebäude):**
100 % Höhenabdeckung. Etwa 81 % tragen die Höhe am Gebäude selbst, die übrigen ~19 % auf
ihren Gebäudeteilen (`BuildingPart`) – beide werden ausgelesen. Zum Vergleich: über OSM
allein lagen für dasselbe Gebiet nur ~13–32 % echte Höhen vor, der Rest war geschätzt.

**Wichtige Einordnung:** `measuredHeight` ist die Höhe bis zum höchsten Punkt (Firsthöhe).
pybdshadow extrudiert flach bis dahin, wodurch der Schatten bei Steildächern leicht
überschätzt wird. Für die *relative* Routenwahl (schattig vs. sonnig) hebt sich das
weitgehend auf; nur der absolute Sonnenanteil ist minimal überschätzt.

---

## Zeit-Aggregation: Sonnendosis (v3)

Statt eines einzelnen Moments lässt sich der Sonnenanteil über ein Stundenfenster mitteln –
die „Sonnendosis" über den heißen Nachmittag. Pro Stunde wird der Schatten neu gerechnet,
je Kante der Sonnenanteil bestimmt und anschließend über die Stunden gemittelt
(`bewerte_kanten_aggregiert` in `modules/kantenbewertung.py`).

- Geschaltet über `AGG_AKTIV` in `config.py`; Fenster über `AGG_START_STUNDE`/`AGG_END_STUNDE`
  (beide Ränder **einschließlich**, stündlich, Standard 11–18 Uhr).
- Gilt **nur für den Hitzeexpositions-Layer**, nicht fürs Routing – ein „schattigster Weg
  über einen gemittelten Tag" wäre nicht sinnvoll.
- Die Info-Box der Karte zeigt das Fenster („11–18 Uhr (Mittel)") statt einer Einzeluhrzeit.
- `schatten_check.html` wird im Mittel-Modus **bewusst nicht** erzeugt: kein einzelnes
  Stundenbild repräsentiert den Durchschnitt ehrlich.

**Ehrliche Einordnung:** Das Fenster ist eine *Planer-Entscheidung*, kein Physik-Wert –
das Modell kennt nur den Sonnenstand, nicht die Lufttemperatur. Die Kosten sind ehrlich:
der Schatten wird N-mal gerechnet (acht Stunden = achtfacher Aufwand); bei kleinen
Gebieten unkritisch.

---

## Vegetation / Baumschatten (v3)

Gebäudeschatten allein unterschätzt die Beschattung systematisch – gerade entlang von
Grünzügen, Bachläufen und Alleen. Stadtschatten ergänzt deshalb **Baumschatten aus dem
amtlichen nDOM1** (normalisiertes Oberflächenmodell, 1-m-Raster, Höhe über Boden) des
LGL Baden-Württemberg (`modules/vegetation.py`).

Da das nDOM nur Höhe kennt, nicht „Baum" vs. „Haus", entsteht Vegetation durch
**Maskierung mit den LoD2-Gebäuden**:

```
1. nDOM-Kacheln laden und zum Mosaik fügen          (data/<ort>/, ndom1_*.tif)
2. LGL-LoD2-Footprints (gepuffert) im nDOM abschalten → Gebäude raus
3. Schwelle: Pixel ≥ VEG_MIN_HOEHE gelten als Vegetation
4. zusammenhängende Flächen → Polygone, Höhe = Median der nDOM-Pixel darin
5. Flächenfilter gegen Pixel-Krümel (Laternen, Autos, Kanten)
```

Das Ergebnis ist ein `GeoDataFrame[geometry, height]` – **gleiches Format wie die Gebäude**.
Beide werden zusammengeführt und durch dieselbe Schatten- und Aggregationskette geschickt.
Die Baumschatten wandern damit automatisch mit der Sonne durch das Stundenfenster.

Drei an echten Daten kalibrierte Schalter (`config.py`):

| Parameter | Bedeutung | Standard |
|---|---|---|
| `VEG_MIN_HOEHE` | ab welcher Höhe etwas als schattenwerfend zählt | `3.0` m |
| `GEB_PUFFER_M` | Gebäude-Footprints aufpuffern, damit Wand-Pixel an der Hauskante nicht als Vegetation durchrutschen | `1.0` m |
| `VEG_MIN_FLAECHE_M2` | Mindestfläche je Vegetationspolygon (Rauschfilter) | `4.0` m² |

Die Vegetation ist über `VEG_AKTIV` abschaltbar (Vergleich Gebäude-nur vs. mit Bäumen,
oder Gebiete außerhalb BW). Eine **laute Abdeckungsprüfung** (`NDOM_ERFORDERLICH = True`)
stoppt mit klarer Meldung, falls die Kacheln das Suchgebiet nicht vollständig abdecken –
analog zu `LGL_ERFORDERLICH`, damit keine halb-abgedeckte Karte unbemerkt entsteht.

**Wichtiger Modell-Vorbehalt:** Ein Baum wird – wie ein Gebäude – als **massiver Block**
extrudiert. Reale Kronen sind porös, Licht fällt durch. Der Baumschatten ist damit eine
**Obergrenze**, kein exakter Wert. Für eine „hier ist Schatten"-Karte ist das vertretbar
und deutlich näher an der Realität als gar keine Bäume; die physikalisch rigorose
Behandlung (Transmissivität der Krone) bleibt UMEP/SOLWEIG vorbehalten (siehe *Grenzen*).

---

Von der Wegekante zur Nutzung: flächige Sonnendosis, Kataster, Aufenthaltsorte (v4)

Bis v3 beantwortet Stadtschatten die Frage entlang der Wege: wie sonnig ist diese
Fußweg-Kante. v4 löst die Bewertung von der Kante und legt sie auf Flächen – und
verknüpft sie mit der tatsächlichen Nutzung. Damit verschiebt sich die Aussage vom
reinen Screening („wo ist Schatten") Richtung Entscheidungsrelevanz („wo fehlt Schatten
dort, wo sich Menschen aufhalten").

Der teure Schattenteil wird einmal gerechnet und als GeoTIFF abgelegt; die
nachgelagerten Schritte lesen es – schnelles Iterieren ohne Neuberechnung.

1. Flächige Sonnendosis (modules/exposition.py)

Statt Stützpunkten entlang der Kanten wird ein Raster (Zellgröße AGG_RASTER_M,
Standard 2 m) über das Gebiet gelegt. Pro Zelle der Anteil der Stunden im Fenster, in
denen ihr Mittelpunkt in der Sonne liegt (0 = ganztags Schatten, 1 = ganztags Sonne) –
dieselbe Mittelpunkt-Logik wie bei den Kanten, nur flächig. Ausgabe als GeoTIFF
(sonnendosis.tif) und als Folium-Overlay über dem Orthofoto.

Dächer abziehen: Die LoD2-Gebäude-Footprints werden aus dem Raster gestanzt (Zellen
auf Gebäuden → NODATA). Auf einem Dach hält sich niemand auf; „der Boden unterm Haus ist
dauerschattig" ist keine sinnvolle Aussage. Vegetation bleibt drin – der Schatten
unter einem Baum ist genau der gesuchte kühle Aufenthaltsort. Kein Puffer: der schattige
Streifen an der Nordwand ist echter Boden, auf dem man geht.

Denkendorf: mit Dächern 52 % beschattet, nach dem Dach-Abzug 44 % (Mittel 0,56). Das
Muster folgt sichtbar Bachlauf und Baumgruppen; Gebäude erscheinen ausgestanzt.

2. Sonnendosis × tatsächliche Nutzung (modules/nutzung.py)

Das Dosis-Raster wird mit den amtlichen ALKIS-Flurstücken (LGL, Shape, EPSG:25832)
verschnitten. Je Flurstück das flächengewichtete Mittel der gültigen (Freiflächen-)Zellen
per bincount-Zonalstatistik, etikettiert mit der dominanten Nutzung aus dem
tntxt-Feld (Format Nutzungsart;Fläche_m², mehrere mit | verkettet – die
flächengrößte gewinnt; der separate nutzung-Layer ist für einen ersten Durchgang
unnötig).

Mindest-Freifläche (MIN_FREIFLAECHE_M2, Standard 20 m²): Flurstücke mit weniger
gültiger Freifläche gelten als nicht bewertbar (grau) – ein Mittel über 1–2 Zellen wäre
Rauschen. Das sind faktisch die vollversiegelten Flurstücke, selbst eine planungsrelevante
Klasse.

Ausgabe: Choroplethe je Flurstück (grün = schattig, rot = sonnig), je Nutzungsklasse
abschaltbar, plus eine flächengewichtete Klassentabelle („Sonnendosis je Nutzung") –
die belastbare, strategische Aussage.

Denkendorf (validiert gegen Ortswissen und Orthofoto): Ackerland 0,93 (offen → Sonne),
Laubholz 0,00 (Wald → ganztags Schatten; ALKIS und nDOM stimmen am selben Ort überein),
Wohnbaufläche-Mittel ~0,45, Grünanlagen gegen Satellitenbild geprüft (Bäume vorhanden).

Detail-Lupe (karte_flurstueck_detail): Über DETAIL_PUNKT_LATLON lässt sich ein
einzelnes Flurstück zoomen – jede 2-m-Zelle einzeln eingefärbt, Dach-Zellen grau
(„rausgerechnet"), Grenze als Umriss, Mittelwert beschriftet. Macht den Zwischenschritt
„Zellen → Mittel je Flurstück" transparent – ein Erklär-Werkzeug für Präsentationen. Die
Koordinate ist per Klick auf der Übersichtskarte ablesbar (LatLngPopup).

3. Aufenthaltsorte × Verschattung (modules/aufenthalt.py)

ALKIS-Nutzungsarten sind für Aufenthaltsorte zu grob: „Öffentliche Zwecke" mischt Schule,
Rathaus und Kirche; Bushaltestellen sind gar keine Flurstücke. Quelle ist daher
OpenStreetMap (gleiche osmnx-Maschinerie wie bei den Gebäuden). Erster Durchgang:
Schulen (amenity=school), Kindergärten (amenity=kindergarten), Spielplätze
(leisure=playground) als Flächen; Bushaltestellen (highway=bus_stop ∪
public_transport=platform, auf BUSHALT_DEDUP_M = 10 m entdoppelt, dann
AUFENTHALT_PUNKT_PUFFER_M = 5 m Wartebereich).

Einheitliche Logik: alles wird zu einem kleinen Bereich, dann Mittel der Dosis-Zellen
darin – wie bei den Flurstücken. Umgekehrte Leserichtung: an einem Aufenthaltsort ist
rot = sonnig = Verschattungsbedarf. Ausgabe: Rangliste „größter Verschattungsbedarf" und
Karte je Kategorie abschaltbar.

**Campus-Fragmentierung (Cluster-Fix, v4.1):** Große Einrichtungen – vor allem
Schulcampusse – werden in OSM häufig ohne ein gemeinsames Geländepolygon gemappt.
Stattdessen trägt jedes einzelne Gebäude/jede Teilfläche für sich dasselbe `amenity`-Tag,
meist nur eines davon mit Namen. Unbehandelt erschien ein einzelner Schulcampus so als
viele einzelne „Schule (ohne Name)"-Einträge und verzerrte die Top-N-Rangliste massiv
(ein Standort belegte mehrere Rangplätze, eine tatsächlich zweite Einrichtung fiel dafür
heraus). `_cluster_flaechen()` fasst räumlich zusammenhängende Flächen **derselben
Kategorie** zu einem Ort zusammen (Buffer + `unary_union`, Standard-GIS-Technik für
Connected Components; Toleranz `AUFENTHALT_CLUSTER_PUFFER_M`, Default 8 m). Kategorien
werden dabei strikt getrennt behandelt – eine Kita kann nie mit einer benachbarten
Schule verschmelzen, nur mit einer benachbarten Kita.

Zwei eingebaute Sicherungen gegen Über-Merging (relevant vor allem in dichter Bebauung,
z. B. Stuttgart-West, wo zwei eigenständige Einrichtungen derselben Kategorie nur wenige
Meter auseinanderliegen können):

- **Namenskonflikt:** Tragen mehrere Fragmente eines Clusters UNTERSCHIEDLICHE echte
  Namen, wird nicht zusammengefasst – das ist eher ein Hinweis auf zwei echte
  Einrichtungen dicht beieinander als auf Fragmente einer einzelnen. Stattdessen laute
  Konsolenwarnung, jede Fläche bleibt eigener Ort.
- **Grenzfall-Warnung:** Bei jedem erfolgreichen Merge wird geprüft, wie groß die größte
  Lücke zwischen zwei direkt verbundenen Fragmenten war. Nahe 0 m (Fragmente berühren
  sich, z. B. angrenzende Gebäudeflügel) = hohe Merge-Sicherheit, keine Meldung. Näher an
  `AUFENTHALT_CLUSTER_PUFFER_M` als an 0 → Konsolenwarnung „Grenzfall", da der Merge nur
  knapp innerhalb der Toleranz zustande kam.

**Ungelöster Rest-Fall:** Liegt eine zweite, tatsächlich eigenständige Einrichtung
derselben Kategorie im Puffer UND hat in OSM KEINEN Namen, ist sie von einem echten
Fragment aus Geometrie + Name allein nicht unterscheidbar – weder der Namenskonflikt-
noch der Grenzfall-Schutz greifen zuverlässig, wenn schlicht kein Name da ist, gegen den
geprüft werden kann. Dieser Fall ist real aufgetreten (Denkendorf: Klingenacker-
Kindergarten, unbenannt in OSM, fälschlich mit dem benachbarten Mühlhalden-Kindergarten
verschmolzen, Lücke rechnerisch ~8 m – praktisch exakt an der Puffer-Grenze) und bleibt
ein manueller Prüf-Schritt bei jedem neuen Ort (siehe *Ausnahmeliste* unten sowie
`ablauf.md`, Abschnitt 3a).

**Ausnahmeliste (`ausnahmen/<ORT_SLUG>.txt`):** pro Ort gepflegte, im Repo versionierte
(bewusst NICHT in `data/`, das ist gitignored Cache) Korrekturliste für von Hand
entdeckte OSM-Probleme. Drei Eintragstypen:

| Typ | Syntax | Wirkung | Anwendungsfall |
|---|---|---|---|
| Name | exakter Text | Objekt komplett entfernt | Falsche Kategorie/Fehl-Tagging (z. B. ein Jugendzentrum mit `amenity=school`) |
| Ausschluss-Koordinate | `@x,y[,radius]` | Objekt komplett entfernt | Wie oben, aber ohne Namen zum Matchen |
| Isolier-Koordinate | `!x,y[,radius]` | Objekt bleibt, wird nur vom Merge ausgenommen | Echte, eigenständige Einrichtung, die nur mangels Namen fälschlich mit einer Nachbareinrichtung verschmolzen wurde |

Koordinaten in CRS_METRISCH. `@` und `!` sind bewusst verschieden: `@` für Objekte, die
in dieser Kategorie zurecht nicht existieren sollten (löschen); `!` für Objekte, die
zurecht existieren, nur falsch zugeordnet wurden (trennen, nicht löschen – sie sollen wie
eine unbenannte Sitzbank in der Rangliste auftauchen). Datei ist optional; fehlt sie,
ändert sich nichts. Kein automatischer Fehlererkennungsmechanismus – bewusst manuelle,
dokumentierte Kuratierung pro Ort, kein Autopilot.

Denkendorf (nach Cluster-Fix + Ausnahmeliste, 800-m-Ausschnitt): 91 Orte (41 Sitzbänke,
23 Bushaltestellen, 16 Spielplätze, 7 Kindergärten, 3 Schulen, 2 Soziale Einrichtungen),
76 mit gültigen Zellen. Fünf statt vormals vier Kindergärten nach Korrektur des
Klingenacker-Falls – die fünfte Einrichtung war zuvor unsichtbar in einem falschen
Mittelwert versteckt, nicht bloß falsch benannt.

4. Gemeinderatsvorlage (modules/vorlage.py)

Kein Ersatz für die interaktive Folium-Karte aus Schritt 3 – ein zusätzliches, druckfertiges
PDF (A4 quer) für die Papierform: Karte mit nummerierten Top-Orten links, Tabelle mit
denselben Nummern rechts, je Kategorie die Top-N (Standard 3) aus der Dringlichkeits-
Rangliste. Baut direkt auf `orte_bewertet` + `ranglisten` aus `aufenthalt.py` auf,
keine eigene Berechnung.

Zwei optionale Erweiterungen (v4.2):

- **Kartenhintergrund** (`contextily`, CartoDB Positron): Punkte ohne räumlichen Kontext
  sind für jemanden ohne Ortskenntnis nicht einzuordnen. contextily ist bewusst KEINE
  harte Abhängigkeit – fehlt das Paket oder schlägt der Kachel-Download fehl (kein
  Internetzugriff beim Export), fällt die Vorlage automatisch auf den bisherigen
  Gebietsumriss zurück statt abzubrechen; eine Warnung erscheint auf der Konsole.
  Esri World Imagery bewusst vermieden – Lizenzbedingungen für Druck/Weitergabe eines
  offiziellen Gemeinderatsdokuments sind bei OSM-basierten Kacheln (CartoDB/OSM)
  eindeutiger.
- **Straßennamen unter unbenannten Orten:** Für Orte ohne Namen wird die nächstgelegene
  Kante im bereits vorhandenen Geh-Graphen (`loader.lade_geh_graph()`) nachgeschlagen und
  deren Straßenname als zweite Zeile im Namensfeld angezeigt – kein zweiter OSM-Download,
  keine neue Abhängigkeit. Graph wird nur bei Bedarf geladen (Cache-Hit ist schnell, aber
  unnötig, wenn ohnehin alle Orte einen Namen haben).

---

## Installation & Nutzung

```bash
# eigene Umgebung (empfohlen – getrennt von anderen Modulen)
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate          # Linux/macOS
pip install -r requirements.txt

# kompletter Durchlauf
python run.py
```

Ergebnisse landen als HTML-Karten im Ordner `output/`. Einzelne Module lassen sich
auch separat starten (z. B. `python modules/schatten.py`).

### Konfiguration (`config.py`)

| Parameter | Bedeutung |
|---|---|
| `PLACE` | Ort (ganzer Ort), OSM-kompatibel |
| `ZENTRUM`, `RADIUS_M` | optionaler Zuschnitt auf einen Kreis (schnell, zum Entwickeln); `ZENTRUM = None` → ganzer `PLACE`. Bestimmt zugleich, welche LGL-/nDOM-Kacheln verwendet werden. |
| `DATUM`, `UHRZEIT`, `ZEITZONE` | Zeitpunkt des Schattenwurfs (Einzelmoment) |
| `AGG_AKTIV` | `True` → Hitzeexpositions-Layer wird über das Stundenfenster gemittelt; `UHRZEIT` gilt dann nur noch für `schatten_check.html` |
| `AGG_START_STUNDE`, `AGG_END_STUNDE` | Stundenfenster der Aggregation, beide Ränder einschließlich (Standard 11–18) |
| `VEG_AKTIV` | `True` → Baumschatten aus nDOM einbeziehen; `False` → nur Gebäudeschatten |
| `NDOM_KACHEL_UNTERORDNER` | Unterordner in `data/` mit den nDOM-Kacheln (`ndom1_*.tif`) |
| `VEG_MIN_HOEHE`, `GEB_PUFFER_M`, `VEG_MIN_FLAECHE_M2` | Vegetations-Schalter (siehe Abschnitt *Vegetation*) |
| `START`, `ZIEL` | Routing-Punkte als `(lat, lon)`; `None` → Route abgeschaltet bzw. Demo-Diagonale |
| `ALPHA_SCHATTIG` | Stärke der Schattenbevorzugung (siehe unten) |

LGL-LoD2-Kacheln liegen als `LoD2_*.gml`, nDOM-Kacheln als `ndom1_*.tif` im Ordner
`data/<ort>/`.

### Der `ALPHA`-Regler

Die Kantengewichtung lautet:

```
gewicht = laenge * (1 + ALPHA * sonnenanteil)
```

`ALPHA` ist der **Wechselkurs zwischen Umweg und Sonne**: wie viele zusätzliche Meter
in Kauf genommen werden, um einen Meter Sonne zu vermeiden.

- `ALPHA = 0` → schnellster Weg (Schatten egal)
- `ALPHA = 3` → ein Sonnenmeter „kostet" wie 4 Meter Gehen
- höher → stärkere Schattenbevorzugung, größere Umwege

Wichtig: `ALPHA` wirkt nur, wo es schattige Alternativen *gibt*. Über offene Plätze,
Brücken oder freie Geraden existiert kein Schatten – diese Abschnitte bleiben sonnig,
unabhängig von `ALPHA`. Jenseits des Punktes einer Strecke an dem der schattige
Umweg billiger wird als die sonnige Direktroute, ändert ein höheres `ALPHA` nichts mehr.

---

## Datengrundlage & Technik

| Zweck | Quelle / Werkzeug |
|---|---|
| Wegenetz, Gebäude-Footprints (Fallback) | OpenStreetMap via `osmnx` |
| Gebäudehöhen | **LGL-LoD2** (`measuredHeight`, amtlich) innerhalb BW · **Fallback:** OSM (`height`, `building:levels`, Default 2 Geschosse) |
| Baumhöhen / Vegetation | **LGL-nDOM1** (normalisiertes Oberflächenmodell, 1 m), Gebäude per LoD2 maskiert |
| Schatten / Sonnenstand | `pybdshadow` |
| CityGML einlesen | eigener Parser `modules/lgl_lod2.py` (ElementTree + `shapely`) |
| Raster (nDOM) einlesen | `rasterio`, `scipy.ndimage` (`modules/vegetation.py`) |
| Geometrie | `geopandas`, `shapely` |
| Graph / Routing | `networkx` |
| Karten | `folium` |
| Kartenhintergrund (PDF-Export) | `contextily` (CartoDB Positron, optional) |
| Tatsächliche Nutzung (Flurstücke) | LGL-ALKIS (Shape, Feld `tntxt`: Nutzungsart;Fläche) |
| Aufenthaltsorte (Schulen, Kindergärten, Spielplätze, Bushaltestellen) | OpenStreetMap via `osmnx` |
| Raster / Zonalstatistik | `rasterio`, `numpy.bincount` (exposition.py, nutzung.py, aufenthalt.py) |

**Koordinatensystem:** EPSG:25832 (ETRS89/UTM32N) für alle metrischen Berechnungen –
identisch mit dem CRS der LGL-Daten (LoD2 *und* nDOM), daher kein Umprojizieren nötig.

---

## Stand (v4)

| Schritt | Status |
|---|---|
| pybdshadow verifiziert | ✅ |
| Loader: Geh-Graph + Gebäude mit Höhe | ✅ |
| Schatten-Wrapper (pybdshadow) | ✅ |
| Schatten-zu-Kante-Zuordnung + Kantengewichtung | ✅ |
| Routing: schnellster vs. schattigster Weg (Umschalter) | ✅ |
| Folium-Kartenausgabe mit Parametern + Quellenangabe | ✅ |
| Einstiegspunkt `run.py` | ✅ |
| Echte Gebäudehöhen via LGL-LoD2 (ersetzt OSM-Schätzung in BW) | ✅ |
| **Zeit-Aggregation / Sonnendosis (Stundenfenster, gemittelt)** | ✅ |
| **Baumschatten via nDOM (LoD2-Maskierung, kalibrierte Schalter)** | ✅ |
| Wege = Bürgersteig statt Straßenachse (Schattenseiten-Sampling) | ⬜ offen |
| Kachel-Auswahl je Gebiet + Höhen-Cache (Skalierung) | ⬜ offen |
| GPX-Export | ⬜ optional, offen |

| Flächige Sonnendosis (Raster, exposition.py) | ✅ |
| Dächer ausgestanzt (LoD2-Footprints raus, Vegetation bleibt) | ✅ |
| Sonnendosis × ALKIS-Nutzung (Zonal, Klassentabelle, nutzung.py) | ✅ |
| Detail-Lupe einzelnes Flurstück | ✅ |
| Aufenthaltsorte × Verschattung (OSM, Leserichtung umgedreht, aufenthalt.py) | ✅ (Feinschliffe offen) |
| Haltestellen-Entdopplung: Wartebereich statt Fahrbahn bevorzugen (`_dedup_priorisiert`, `platform` > `bus_stop`) | ✅ |
| **Campus-Fragmentierung filtern (Cluster-Fix `_cluster_flaechen`, ersetzt frühere "Schul-Dubletten"-Aufgabe, jetzt alle Flächen-Kategorien statt nur Schulen)** | ✅ |
| **Namenskonflikt-Schutz (unterschiedlich benannte Nachbar-Einrichtungen nicht zusammenfassen)** | ✅ |
| **Grenzfall-Warnung (Merges nahe der Puffer-Grenze automatisch markieren)** | ✅ |
| **Ausnahmeliste pro Ort (`ausnahmen/<ORT_SLUG>.txt`, drei Eintragstypen)** | ✅ |
| **vorlage.py: Kartenhintergrund (contextily) + Straßennamen unter unbenannten Orten** | ✅ |
| Restrisiko: unbenannte, tatsächlich eigenständige Nachbar-Einrichtung wird von Namenskonflikt-/Grenzfall-Schutz nicht sicher erkannt | ⬜ bleibt manueller Prüf-Schritt |
| `AUFENTHALT_CLUSTER_PUFFER_M` von `aufenthalt.py` nach `config.py` zentralisieren | ⬜ offen |
| `OUTPUT_DIR`-Doppeldefinition in `config.py` beheben (zweite Zuweisung überschrieb die ort-abhängige) | ✅ behoben |
| Aufenthaltsorte feiner (Bänke, Pflegeheime, weitere Tags) | ⬜ offen |

---

## Validierung

Schattenrichtung und -länge werden gegen den berechneten Sonnenstand geprüft: Beispiel
Esslingen am Neckar, 21.06., Sonne im SSW bei hoher Sonnenhöhe → Schatten zeigen nach NNO;
Schattenlänge konsistent zur Gebäudehöhe und zum physikalischen Sonnenstand.

Geprüft an zwei Orten (Esslingen, Denkendorf). Mit der LGL-LoD2-Anbindung beruhen die
Höhen im Testgebiet Esslingen zu 100 % auf amtlichen Messwerten (Median ~11 m) statt auf
Schätzung – die absoluten Schattenwerte sind damit erstmals belastbar.

**Baumschatten (Denkendorf, Ortskenntnis als Maßstab):** Über das Fenster 11–18 Uhr steigt
der beschattete Netzanteil mit Vegetation auf ~31 % (gegenüber ~6 % ohne Bäume im selben
Fenster). Der zusätzliche Schatten folgt sichtbar dem Grünzug entlang des Bachlaufs – genau
dort, wo vor Ort die meisten Bäume stehen. Die nDOM-Höhen steigen über den Nachmittag
plausibel an (kurze Schatten zur Mittagszeit, lange am Abend), konsistent zum Sonnenstand.

Der direkte Vergleich am Bachlauf macht den Effekt sichtbar: Ohne Vegetation erscheint der
Grünzug fälschlich sonnig (rot); erst mit Baumschatten färbt sich dieselbe Strecke schattig
(grün). Beide Karten zeigen dasselbe Fenster (11–18 Uhr, gemittelt).

| Ohne Baumschatten (~6 % beschattet) | Mit Baumschatten (~31 % beschattet) |
|---|---|
| ![Sonnenanteil-Karte ohne Baumschatten – der Grünzug am Bachlauf erscheint durchgehend sonnig](docs/ohnebaumschatten.jpg) | ![Sonnenanteil-Karte mit Baumschatten – der Grünzug am Bachlauf ist als schattiger Korridor erkennbar](docs/mitbaumschatten.jpg) |

---

## Grenzen dieser Auswertung

Bewusste, dokumentierte Einschränkungen:

1. **Wege = Straßenachsen, nicht Bürgersteige.** Der osmnx-`walk`-Graph nutzt die
   Straßenachse, wo Gehwege nicht als eigene Geometrie kartiert sind. Fußgänger laufen
   am Gebäuderand (schattiger) statt in der Straßenmitte. Der Fußgänger-Schatten wird
   dadurch eher **unter- als überschätzt** – die realen Werte liegen tendenziell über den
   ausgewiesenen.
2. **Baumschatten ist eine Obergrenze.** Bäume werden als massive Blöcke extrudiert; die
   Porosität der Krone (durchfallendes Licht) ist nicht modelliert. Der Vegetations-Schatten
   ist daher tendenziell zu dicht. Brauchbar für „wo ist überhaupt Schatten", nicht für
   exakte Bestrahlungsstärke.
3. **Höhen nur in Baden-Württemberg amtlich.** Innerhalb BW (und wo Kacheln vorliegen)
   kommen gemessene LGL-LoD2- und nDOM-Höhen zum Einsatz. Außerhalb BW oder ohne Kachel
   greift die OSM-Schätzung bzw. entfällt die Vegetation. `measuredHeight` ist Firsthöhe
   (siehe Abschnitt *Gebäudehöhen*).
4. **Stundenraster.** Die Aggregation arbeitet in vollen Stunden; das Fenster ist eine
   Planer-Entscheidung, kein temperaturbasierter Physik-Wert.
5. **Keine thermische Strahlungsmodellierung.** Bewusste Abgrenzung zu wissenschaftlich
   rigorosen Werkzeugen wie UMEP/SOLWEIG, die DSM-basiert rechnen und Kronen-Transmissivität
   sowie mittlere Strahlungstemperatur abbilden. Stadtschatten ist der schlanke, scriptbare,
   vollständig nachvollziehbare Weg – nicht das physikalisch vollständigste Modell.
6. Flächen-/Parzellenmittel ist räumlich blind. Der Sonnendosis-Wert eines Flurstücks
oder Aufenthaltsbereichs ist ein korrekter Durchschnitt über seine Freifläche, kann aber
innerhalb der Fläche stark schwanken (z. B. Stellplatz schattig, Garten sonnig). Bei
kleinen Flächen schwankt der Einzelwert zusätzlich durch Schatten der Nachbarn. Belastbar
ist die Klassentabelle über viele Flächen, nicht der Einzelwert.
7. OSM-Abdeckung uneinheitlich. Aufenthaltsorte stammen aus OpenStreetMap; Haltestellen
und Schulen sind in Deutschland meist gut erfasst, anderes (Bänke, Sitzgelegenheiten)
lückenhaft. Was OSM nicht kennt, fehlt in der Auswertung.
8. Wartehäuschen nicht modelliert. Bushaltestellen-Unterstände stecken weder in LoD2
(kein Gebäude) noch verlässlich im nDOM; eine überdachte Haltestelle liest sich als voll
sonnig. (Ein kleines Dächlein ist ohnehin nur begrenzt Sonnenschutz.)
9. OSM-Haltestellenpunkt teils auf der Fahrbahn statt im Wartebereich – der gepufferte
Bereich bewertet dann offenen Asphalt (siehe offene Feinschliffe im Aufenthalts-Abschnitt).
10. ALKIS zu grob für Aufenthaltsfunktion. „Öffentliche Zwecke" mischt Schule, Rathaus,
Kirche; Bushaltestellen sind keine Flurstücke. Aufenthaltsorte kommen deshalb aus OSM,
nicht aus dem Kataster.
11. Campus-Zusammenfassung hat ein algorithmisch nicht schließbares Restrisiko. Der
Cluster-Fix (siehe Aufenthaltsorte-Abschnitt) fasst benachbarte OSM-Fragmente derselben
Kategorie zusammen und erkennt Namenskonflikte sowie geometrische Grenzfälle. Trägt eine
zweite, tatsächlich eigenständige Nachbareinrichtung in OSM aber KEINEN Namen, ist sie von
einem echten Fragment nicht unterscheidbar – weder Code noch dieses Dokument können das
für einen neuen Ort im Voraus ausschließen. Bleibt ein manueller Prüf-Schritt pro Ort
(`ausnahmen/<ORT_SLUG>.txt`, siehe `ablauf.md` Abschnitt 3a) – kein Automatismus, keine
Garantie ohne diesen Schritt.
12. Ausnahmeliste ist handkuratiert, nicht validiert gegen eine zweite Quelle. Einträge in
`ausnahmen/<ORT_SLUG>.txt` beruhen auf Stichproben gegen Google Maps/Ortswissen, nicht auf
einer systematischen Prüfung aller Aufenthaltsorte. Bei Orten ohne persönliche Ortskenntnis
(Subunternehmer-Auftrag in fremder Stadt) ist dieser Schritt aufwendiger und die
Fehlerquote potenziell höher als in Denkendorf.

---

## Ausblick

- **Frequenz × Sonnenbelastung:** Stark begangene *und* stark besonnte Wege als
  Prioritätskarte für Beschattungsmaßnahmen – der eigentliche planerische Hebel. Ansätze:
  Betweenness-Zentralität (strukturell) oder zielorientiertes Routing (zu Schulen,
  Bahnhof, Busbahnhof). Bleibt ein Modell, keine gemessene Frequenz.
- **Schattenseiten-Sampling:** Stützpunkte seitlich von der Achse versetzen und die
  schattigere Straßenseite werten – bildet reales Fußgängerverhalten ab (adressiert Grenze 1).
- **Kachel-Auswahl je Gebiet + Höhen-Cache:** damit über die Testgebiete hinaus skalierbar
  und ohne wiederholtes Parsen der großen CityGML-/Raster-Kacheln.
- **GPX-Export** der gewählten Route (für Navigation unterwegs).
- **Kronen-Transmissivität** als optionaler Premium-Pfad (SOLWEIG-Anbindung), wenn echte
  thermische Komfortanalyse gefragt ist.
- Weitere Städte.

---

## Datenlizenz

OpenStreetMap-Daten © OpenStreetMap-Mitwirkende (ODbL).

Diese Auswertung nutzt amtliche Geobasisdaten des Landesamts für Geoinformation und
Landentwicklung Baden-Württemberg (LGL): 3D-Gebäudemodelle (LoD2) und das normalisierte
Oberflächenmodell (nDOM1). Datenlizenz Deutschland – Namensnennung 2.0, Quellenangabe:
**„Datenquelle: LGL, www.lgl-bw.de"**. Die Angabe erscheint in der README sowie auf jeder
erzeugten Karte.

Der optionale Kartenhintergrund in `vorlage.py` (CartoDB Positron via `contextily`)
bringt eine eigene Attribution mit: **„© OpenStreetMap-Mitwirkende, © CARTO"**, erscheint
in der Fußzeile des PDFs, nur wenn der Hintergrund tatsächlich geladen werden konnte.