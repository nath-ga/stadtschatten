# stadtschatten/modules/startseite.py
#
# Baut die Startseite (index.html) fuer einen Ort - rein aus config.py.
# Verlinkt die drei Ergebniskarten im selben Ordner (output/<ort>/) und gibt
# dem Betrachter eine kurze Einordnung. Nur vorhandene Karten werden verlinkt.
#
# Aufruf NACH den drei Karten:  python modules/startseite.py
# Ergebnis: output/<ort>/index.html

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (OUTPUT_DIR, PLACE, ZENTRUM, RADIUS_M,
                    DATUM, AGG_START_STUNDE, AGG_END_STUNDE)

# Karten in Lese-Reihenfolge: von der reinen Flaeche zur Handlungsempfehlung.
KARTEN = [
    ("sonnendosis.html", "Grundlage",
     "Verschattung der Flächen",
     "Wie sonnig ist jede Fläche im Tagesmittel? Dächer sind herausgerechnet – "
     "bewertet wird der offene Boden, auf dem man sich aufhält."),
    ("nutzung_sonnendosis.html", "Einordnung",
     "Verschattung nach Nutzung",
     "Dieselbe Verschattung, verknüpft mit der amtlichen Nutzung der Grundstücke: "
     "welche Nutzungsart – Wohnen, Grünanlage, Gewerbe – wie stark besonnt ist. "
     "Je Nutzung einzeln einblendbar."),
    ("aufenthalt_bedarf.html", "Empfehlung",
     "Verschattungsbedarf an Aufenthaltsorten",
     "Schulen, Spielplätze, Bushaltestellen und Bänke, bewertet nach Sonne: "
     "rot heißt sonniger Aufenthaltsort – hier bringt Schatten am meisten."),
    ("route.html", "Beispiel",
     "Schattigster vs. schnellster Weg",
     "Ein Einzelbeispiel zwischen zwei festen Punkten: wie stark weicht der "
     "schattigste Weg vom schnellsten ab, und welcher Umweg wird dafür in Kauf "
     "genommen? Keine flächendeckende Auswertung wie die drei Karten oben, "
     "sondern eine Demonstration des Abwägungs-Prinzips für eine Route."),
]

HINWEISE = [
    ("Screening, kein Entscheidungswerkzeug",
     "Die Karten zeigen, wo genaueres Hinschauen lohnt – nicht den fertigen Maßnahmenplan."),
    ("Momentaufnahme",
     "Berechnet für den genannten Tag und das Stundenfenster; ein anderer Tag ergibt andere Schatten."),
    ("Einzelwerte mit Vorsicht",
     "Belastbar ist der Vergleich zwischen Nutzungsklassen; der Wert eines einzelnen kleinen "
     "Grundstücks schwankt stärker."),
    ("Was die Daten nicht kennen, fehlt",
     "Wartehäuschen an Haltestellen und in OpenStreetMap nicht erfasste Orte sind nicht berücksichtigt."),
]

STIL = """
:root{
  --ink:#1b2430; --muted:#5d6b7a; --paper:#f4f2ec; --card:#ffffff;
  --line:#e3dfd6; --shade:#1a9641; --mid:#e3a008; --sun:#d7191c; --deep:#234a59;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:820px;margin:0 auto;padding:56px 24px 72px}
.eyebrow{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);
  font-weight:600;margin:0 0 14px}
.wordmark{font-size:13px;letter-spacing:.32em;text-transform:uppercase;font-weight:700;
  color:var(--deep);margin:0 0 6px}
h1{font-size:clamp(34px,6vw,54px);line-height:1.02;margin:0 0 4px;font-weight:800;
  letter-spacing:-.02em}
.unterort{font-size:clamp(34px,6vw,54px);font-weight:300;color:var(--muted);
  letter-spacing:-.02em;display:block}
.band{height:10px;border-radius:6px;margin:26px 0 8px;
  background:linear-gradient(90deg,var(--shade) 0%,#9bbf3a 30%,var(--mid) 60%,var(--sun) 100%)}
.bandlabels{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);
  letter-spacing:.04em;margin-bottom:30px}
.these{font-size:19px;line-height:1.5;margin:0 0 26px;max-width:62ch}
.meta{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;
  color:var(--deep);background:#fff;border:1px solid var(--line);border-radius:8px;
  padding:11px 14px;display:inline-block;margin-bottom:44px}
.meta span{color:var(--muted)}
.karten{display:flex;flex-direction:column;gap:16px;margin:0 0 48px}
.karte{display:block;text-decoration:none;color:inherit;background:var(--card);
  border:1px solid var(--line);border-left:4px solid var(--deep);border-radius:10px;
  padding:20px 22px;transition:none}
@media (prefers-reduced-motion:no-preference){
  .karte{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
}
.karte:hover{transform:translateY(-2px);box-shadow:0 6px 22px rgba(27,36,48,.10);
  border-left-color:var(--sun)}
.karte:focus-visible{outline:3px solid var(--deep);outline-offset:2px}
.kat{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
  font-weight:700;margin:0 0 6px}
.karte h2{font-size:21px;margin:0 0 8px;font-weight:700;letter-spacing:-.01em}
.karte p{margin:0 0 14px;color:#3c4854;font-size:15px;max-width:60ch}
.oeffnen{font-weight:700;color:var(--deep);font-size:14.5px}
.oeffnen::after{content:" →"}
.hinweise{border-top:1px solid var(--line);padding-top:28px;margin-bottom:40px}
.hinweise h3{font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);
  margin:0 0 16px;font-weight:700}
.hinweise dl{margin:0;display:grid;gap:14px}
.hinweise dt{font-weight:700;font-size:14.5px}
.hinweise dd{margin:2px 0 0;color:var(--muted);font-size:14px;max-width:64ch}
footer{border-top:1px solid var(--line);padding-top:22px;color:var(--muted);font-size:12.5px;
  line-height:1.7}
"""


def _ort_anzeige():
    return PLACE.split(",")[0].strip()


def _datum_anzeige():
    try:
        j, m, t = DATUM.split("-")
        return f"{t}.{m}.{j}"
    except Exception:
        return DATUM


def _gebiet_anzeige():
    if ZENTRUM:
        return f"Ausschnitt {RADIUS_M} m"
    return "ganzer Ort"


def baue_startseite(pfad=None):
    if pfad is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pfad = os.path.join(OUTPUT_DIR, "index.html")

    karten_html = ""
    for datei, kat, titel, text in KARTEN:
        if not os.path.exists(os.path.join(OUTPUT_DIR, datei)):
            continue   # nur vorhandene Karten verlinken
        karten_html += (
            f'<a class="karte" href="{datei}">'
            f'<p class="kat">{kat}</p>'
            f'<h2>{titel}</h2><p>{text}</p>'
            f'<span class="oeffnen">Karte öffnen</span></a>\n'
        )
    if not karten_html:
        karten_html = ('<p class="these">Noch keine Karten in diesem Ordner. '
                       'Erst exposition / nutzung / aufenthalt laufen lassen.</p>')

    hinweise_html = "".join(
        f"<dt>{t}</dt><dd>{b}</dd>" for t, b in HINWEISE)

    ort = _ort_anzeige()
    html = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stadtschatten – {ort}</title>
<style>{STIL}</style></head>
<body><div class="wrap">
  <p class="eyebrow">Klimaangepasste Stadtplanung</p>
  <p class="wordmark">Stadtschatten</p>
  <h1>{ort}<span class="unterort">Verschattung &amp; Aufenthalt</span></h1>

  <div class="band"></div>
  <div class="bandlabels"><span>ganztags schattig</span><span>ganztags sonnig</span></div>

  <p class="these">Wo fehlt Schatten dort, wo sich Menschen aufhalten? Diese Auswertung
  verbindet die Verschattung über den Tag mit der tatsächlichen Nutzung der Flächen und den
  Orten, an denen Menschen sich aufhalten – als Übersicht, wo genaueres Hinschauen lohnt.</p>

  <p class="meta">Datum {_datum_anzeige()} <span>·</span> Zeitfenster {AGG_START_STUNDE}–{AGG_END_STUNDE} Uhr <span>·</span> Gebiet {_gebiet_anzeige()}</p>

  <div class="karten">
  {karten_html}
  </div>

  <div class="hinweise">
    <h3>So lesen Sie die Karten</h3>
    <dl>{hinweise_html}</dl>
  </div>

  <footer>
    Datenquelle Verschattung: LGL, www.lgl-bw.de (LoD2, nDOM1, ALKIS)<br>
    Aufenthaltsorte: © OpenStreetMap-Mitwirkende<br>
    © Nathalie Gassert · Stadtschatten · github.com/nath-ga/stadtschatten
  </footer>
</div></body></html>"""

    with open(pfad, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Startseite gespeichert: {pfad}")
    return pfad


if __name__ == "__main__":
    baue_startseite()