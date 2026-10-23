#!/usr/bin/env python3
"""
Quill – Bereinigung des Personenregisters (Tabelle persons).

Liest
  exports/personen-export.csv            (id, name, aliases, emails, party, source, created_at, created_by
                                          optional zusätzlich: birth_date, user_id)
  exports/person_connections_counts.csv  (person_id, anzahl_verbindungen)

und schreibt
  exports/personen-entscheidungen.csv    (id, name_alt, entscheidung, name_neu, kanonische_id,
                                          unterkategorie, konfidenz, begruendung)
  exports/personen-restmenge.csv         Einträge, die nach den Regeln noch "unklar" sind
                                          (für die Einzelbewertung; Spalte "entscheidung_neu" ausfüllen
                                          und mit --einzelbewertung zurückspielen)
  exports/personen-zusammenfassung.md    Zahlen je Kategorie
  scripts/personen-bereinigung-daten.sql Staging-INSERTs für scripts/personen-bereinigung.sql

Vorgehen
  1. regelbasiert (Regex für E-Mails, Zahlen, URLs, Parteitage/Ereignisse, Organisationen,
     Namensmuster "Nachname, Vorname", Präfixe wie "A- ", Titel, Klammerzusätze)
  2. Namensnormalisierung (Umlaute, Reihenfolge, Titel) + Dubletten-Gruppierung;
     zusammengelegt wird nur, wenn Vor- UND Nachname passen und weder Partei, Geburtsdatum
     noch Benutzerzuordnung widersprechen
  3. Restmenge -> unklar (so klein wie möglich), separat exportiert

Aufruf (aus dem Repo-Wurzelverzeichnis):
  python3 -I scripts/personen-klassifikation.py
  python3 -I scripts/personen-klassifikation.py --einzelbewertung exports/personen-restmenge-bewertet.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------------------

RUN_ID = "personen-bereinigung-" + datetime.now().strftime("%Y-%m-%d")

DECISION_COLUMNS = [
    "id", "name_alt", "entscheidung", "name_neu", "kanonische_id",
    "unterkategorie", "konfidenz", "begruendung",
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
EMAIL_ANYWHERE_RE = re.compile(r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}")
URL_RE = re.compile(r"(https?://|www\.|\.(de|com|org|net|eu|info|at|ch)(/|$))", re.I)
PHONE_RE = re.compile(r"^[+\d][\d\s/()\-]{6,}$")
DIGIT_RE = re.compile(r"\d")
PREFIX_LETTER_RE = re.compile(r"^[A-Za-zÄÖÜ]{1,2}\s*[-–]\s+(?=\S)")          # "A- Baum, Christina"
TRAILING_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*$")
LEADING_PAREN_RE = re.compile(r"^\s*[\(\[][^\)\]]*[\)\]]\s*")
TRAILING_SEP_RE = re.compile(r"\s+[-–|/,;:]\s+.*$")                          # "Name - AfD", "Name | MdB"
MULTI_WS_RE = re.compile(r"\s+")
JUNK_CHARS_RE = re.compile(r"[\"„“”‚‘’'`´*_#~^<>{}\[\]|\\]+")
INITIAL_RE = re.compile(r"^[A-ZÄÖÜ]\.?$")

TITLES = {
    "dr", "dr.", "prof", "prof.", "med", "med.", "jur", "jur.", "phil", "phil.", "rer", "rer.", "nat", "nat.",
    "h.c.", "hc", "dipl", "dipl.", "dipl.-ing", "dipl.-ing.", "dipl.-kfm", "dipl.-kfm.", "dipl.-päd.", "ing", "ing.",
    "mag", "mag.", "msc", "m.sc.", "bsc", "b.sc.", "ba", "b.a.", "ma", "m.a.", "mba", "ll.m.", "llm",
    "mdb", "mdl", "mdep", "mep", "mda", "mdbb", "mdhb", "mdep.",
    "herr", "frau", "hr", "hr.", "fr", "fr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "sir",
    "ra", "ra.", "rechtsanwalt", "rechtsanwältin", "pfarrer", "pastor", "pater", "bischof",
    "senator", "senatorin", "staatssekretär", "staatssekretärin", "minister", "ministerin",
    "bürgermeister", "bürgermeisterin", "oberbürgermeister", "oberbürgermeisterin", "landrat", "landrätin",
    "abg", "abg.", "abgeordneter", "abgeordnete", "fraktionsvorsitzender", "fraktionsvorsitzende",
    "vorsitzender", "vorsitzende", "generalsekretär", "generalsekretärin", "sprecher", "sprecherin",
    "kandidat", "kandidatin", "stadtrat", "stadträtin", "kreisrat", "kreisrätin",
}
PARTICLES = {"von", "van", "de", "der", "den", "del", "della", "di", "da", "du", "zu", "zur", "zum", "la", "le",
             "af", "av", "ten", "ter", "und", "y", "el", "al", "bin", "ibn", "o'", "mac", "mc", "st.", "saint"}

PARTY_TOKENS = {
    "afd", "cdu", "csu", "spd", "fdp", "grüne", "gruene", "die grünen", "bündnis 90/die grünen", "b90", "linke",
    "die linke", "bsw", "npd", "die heimat", "freie wähler", "fw", "piraten", "ödp", "oedp", "volt",
    "die partei", "iii. weg", "der iii. weg", "dritter weg", "die basis", "diebasis", "werteunion", "bvb",
    "tierschutzpartei", "familie", "mlpd", "dkp", "rep", "republikaner", "pro deutschland", "die rechte",
    "jn", "ja", "junge alternative", "junge union", "ju", "jusos", "grüne jugend", "linksjugend", "julis",
}

ORG_KEYWORDS = [
    # Rechtsformen
    r"\bgmbh\b", r"\bag\b", r"\bkg\b", r"\bkga?a\b", r"\bmbh\b", r"\bug\b", r"\bse\b", r"\bohg\b", r"\bgbr\b",
    r"\be\.\s?v\.?", r"\bev\b", r"\bltd\.?\b", r"\binc\.?\b", r"\bllc\b", r"\bs\.?a\.?\b", r"\bsarl\b", r"\bbv\b",
    r"\bco\.\b", r"\b&\s?co\b", r"\bplc\b", r"\bgmbh\s?&\s?co", r"\bholding\b", r"\bgroup\b", r"\bgruppe\b",
    # Vereine, Verbände, Stiftungen
    r"\bverein\b", r"\bverband\b", r"\bbundesverband\b", r"\blandesverband\b", r"\bkreisverband\b", r"\bortsverband\b",
    r"\bortsgruppe\b", r"\bkreisgruppe\b", r"\bstiftung\b", r"\bgesellschaft\b", r"\bgenossenschaft\b",
    r"\bbündnis\b", r"\bbuendnis\b", r"\binitiative\b", r"\bbewegung\b", r"\bnetzwerk\b", r"\bplattform\b",
    r"\bkameradschaft\b", r"\bburschenschaft\b", r"\blandsmannschaft\b", r"\bbruderschaft\b", r"\bbund\b",
    r"\bfraktion\b", r"\bpartei\b", r"\bjugend\b", r"\bjunge\s", r"\bjusos\b", r"\bjulis\b",
    r"\bgewerkschaft\b", r"\bbetriebsrat\b", r"\bpersonalrat\b", r"\bkammer\b", r"\binnung\b",
    r"\bfeuerwehr\b", r"\bsportverein\b", r"\bsv\b", r"\bfc\b", r"\btsv\b", r"\bvfb\b", r"\bvfl\b", r"\bsg\b",
    # Behörden, Politik, Justiz
    r"\bministerium\b", r"\bstaatskanzlei\b", r"\bsenat\b", r"\blandtag\b", r"\bbundestag\b", r"\bbundesrat\b",
    r"\bkreistag\b", r"\bstadtrat\b", r"\bgemeinderat\b", r"\bortschaftsrat\b", r"\brathaus\b", r"\bbürgeramt\b",
    r"\bamt\b", r"\bbehörde\b", r"\bbundesamt\b", r"\blandesamt\b", r"\bfinanzamt\b", r"\bjobcenter\b",
    r"\bagentur\b", r"\bpolizei\b", r"\bpolizeiinspektion\b", r"\bpolizeidirektion\b", r"\bbundespolizei\b",
    r"\bstaatsanwaltschaft\b", r"\bgeneralstaatsanwaltschaft\b", r"\bgericht\b", r"\blandgericht\b",
    r"\bamtsgericht\b", r"\boberlandesgericht\b", r"\bverwaltungsgericht\b", r"\bverfassungsgericht\b",
    r"\bverfassungsschutz\b", r"\bbka\b", r"\blka\b", r"\bbnd\b", r"\bzoll\b", r"\bbundeswehr\b",
    r"\bregierung\b", r"\bbundesregierung\b", r"\blandesregierung\b", r"\bverwaltung\b", r"\bkommune\b",
    r"\bstadt\b", r"\bgemeinde\b", r"\blandkreis\b", r"\bkreis\b", r"\bbezirk\b", r"\bregion\b",
    # Bildung, Kirche, Gesundheit
    r"\buniversität\b", r"\buni\b", r"\bhochschule\b", r"\bfachhochschule\b", r"\binstitut\b", r"\bakademie\b",
    r"\bschule\b", r"\bgymnasium\b", r"\bgrundschule\b", r"\bkita\b", r"\bkindergarten\b", r"\bbibliothek\b",
    r"\bkirche\b", r"\bkirchengemeinde\b", r"\bgemeindeverband\b", r"\bbistum\b", r"\bdiakonie\b", r"\bcaritas\b",
    r"\bmoschee\b", r"\bsynagoge\b", r"\bklinik\b", r"\bklinikum\b", r"\bkrankenhaus\b", r"\bpraxis\b",
    r"\bzentrum\b", r"\bcenter\b", r"\bheim\b",
    # Medien, Wirtschaft
    r"\bverlag\b", r"\bredaktion\b", r"\bzeitung\b", r"\bzeitschrift\b", r"\bmagazin\b", r"\brundfunk\b",
    r"\bfernsehen\b", r"\bradio\b", r"\bsender\b", r"\bstudio\b", r"\bmedien\b", r"\bpresse\b", r"\bpressestelle\b",
    r"\bnachrichten\b", r"\bnews\b", r"\bmdr\b", r"\bndr\b", r"\bwdr\b", r"\bzdf\b", r"\bard\b", r"\brbb\b",
    r"\bbr\b", r"\bswr\b", r"\bhr\b", r"\bsr\b", r"\bdeutschlandfunk\b", r"\bdpa\b", r"\bepd\b", r"\bafp\b",
    r"\bbank\b", r"\bsparkasse\b", r"\bvolksbank\b", r"\bversicherung\b", r"\bkanzlei\b", r"\bbüro\b",
    r"\bgeschäftsstelle\b", r"\bsekretariat\b", r"\babteilung\b", r"\bteam\b", r"\bfirma\b", r"\bunternehmen\b",
    r"\bbetrieb\b", r"\bwerk\b", r"\bfabrik\b", r"\bhandel\b", r"\bservice\b", r"\bservices\b", r"\bsolutions\b",
    r"\bconsulting\b", r"\bmanagement\b", r"\bimmobilien\b", r"\blogistik\b", r"\btechnik\b", r"\bsystems\b",
    r"\bsoftware\b", r"\bdigital\b", r"\bonline\b", r"\bshop\b", r"\bstore\b", r"\bhotel\b", r"\bgasthaus\b",
    r"\brestaurant\b", r"\bcafé\b", r"\bbäckerei\b", r"\bapotheke\b", r"\bautohaus\b", r"\bwerkstatt\b",
    r"\bbaumarkt\b", r"\bmarkt\b", r"\bbrauerei\b", r"\bweingut\b", r"\bhof\b", r"\bgut\b",
    r"\bkollektiv\b", r"\bkollegium\b", r"\bgremium\b", r"\bausschuss\b", r"\bkommission\b", r"\bbeirat\b",
    r"\brat\b", r"\bvorstand\b", r"\bpräsidium\b", r"\bdirektion\b", r"\bleitung\b", r"\bbeauftragte[rn]?\b",
    r"\bsupport\b", r"\bkundenservice\b", r"\bkundendienst\b", r"\bhotline\b", r"\binfo\b", r"\bkontakt\b",
    r"\bnewsletter\b", r"\bnoreply\b", r"\bno-reply\b", r"\bmailer\b", r"\badmin\b", r"\bwebmaster\b",
    r"\bpostmaster\b", r"\bticket\b", r"\bbestellung\b", r"\brechnung\b", r"\baccount\b", r"\bbenachrichtigung\b",
]
ORG_RE = re.compile("|".join(ORG_KEYWORDS), re.I)

SERVICE_RE = re.compile(
    r"\b(support|kundenservice|kundendienst|hotline|info|kontakt|newsletter|noreply|no-reply|mailer|admin|"
    r"webmaster|postmaster|ticket|bestellung|rechnung|account|benachrichtigung|notification|service|"
    r"team|abo|abonnement|zahlung|payment|lieferung|versand|paypal|amazon|ebay|google|facebook|instagram|"
    r"twitter|x\.com|youtube|tiktok|linkedin|xing|telegram|whatsapp|signal|apple|microsoft|netflix|spotify)\b", re.I)

EVENT_KEYWORDS = [
    r"\bparteitag\b", r"\bbundesparteitag\b", r"\blandesparteitag\b", r"\bkreisparteitag\b", r"\bparteikonvent\b",
    r"\bkonvent\b", r"\bkongress\b", r"\bkonferenz\b", r"\btagung\b", r"\bsymposium\b", r"\bforum\b",
    r"\bgipfel\b", r"\bsummit\b", r"\bmesse\b", r"\bfestival\b", r"\bfest\b", r"\bfeier\b", r"\bjubiläum\b",
    r"\bjahrestag\b", r"\bgedenktag\b", r"\bgedenken\b", r"\bgedenkveranstaltung\b",
    r"\bdemo\b", r"\bdemonstration\b", r"\bkundgebung\b", r"\bprotest\b", r"\bmahnwache\b", r"\baufmarsch\b",
    r"\bmarsch\b", r"\bspaziergang\b", r"\bmontagsdemo\b", r"\bversammlung\b", r"\bmitgliederversammlung\b",
    r"\bhauptversammlung\b", r"\bgeneralversammlung\b", r"\bsitzung\b", r"\bplenarsitzung\b", r"\banhörung\b",
    r"\bwahl\b", r"\bwahlen\b", r"\bbundestagswahl\b", r"\blandtagswahl\b", r"\bkommunalwahl\b",
    r"\beuropawahl\b", r"\bstichwahl\b", r"\bwahlkampf\b", r"\bwahlkampfauftakt\b", r"\bwahlparty\b",
    r"\bwahlabend\b", r"\bwahlnacht\b", r"\bnominierung\b", r"\baufstellungsversammlung\b",
    r"\btreffen\b", r"\bstammtisch\b", r"\bbürgerdialog\b", r"\bbürgergespräch\b", r"\bdiskussion\b",
    r"\bpodium\b", r"\bpodiumsdiskussion\b", r"\bvortrag\b", r"\blesung\b", r"\bworkshop\b", r"\bseminar\b",
    r"\bschulung\b", r"\bpressekonferenz\b", r"\bpressetermin\b", r"\bempfang\b", r"\bneujahrsempfang\b",
    r"\bsommerfest\b", r"\bgrillfest\b", r"\bweihnachtsfeier\b", r"\bsommerinterview\b",
    r"\bprozess\b", r"\bverhandlung\b", r"\burteil\b", r"\brazzia\b", r"\bdurchsuchung\b", r"\banschlag\b",
    r"\bangriff\b", r"\bbrand\b", r"\bunfall\b", r"\bskandal\b", r"\baffäre\b", r"\bkrise\b",
    r"\bturnier\b", r"\bspiel\b", r"\bderby\b", r"\bpokal\b", r"\bmeisterschaft\b", r"\bolympia\b",
    r"\bsendung\b", r"\btalk\b", r"\btalkshow\b", r"\bshow\b", r"\bpodcast\b", r"\binterview\b",
    r"\bdokumentation\b", r"\bdoku\b", r"\breportage\b", r"\bbericht\b", r"\bbeitrag\b", r"\bfolge\b",
    r"\bepisode\b", r"\bstaffel\b", r"\blivestream\b", r"\bstream\b", r"\bvideo\b", r"\bserie\b",
    r"\btagesschau\b", r"\btagesthemen\b", r"\bheute[- ]journal\b", r"\bheute\b", r"\bmorgenmagazin\b",
    r"\bmittagsmagazin\b", r"\bbrennpunkt\b", r"\bpanorama\b", r"\bmonitor\b", r"\bkontraste\b", r"\bfakt\b",
    r"\bfrontal\b", r"\breport\b", r"\bexakt\b", r"\bumschau\b", r"\bsachsenspiegel\b", r"\bsachsen-anhalt heute\b",
    r"\bthüringen journal\b", r"\bhart aber fair\b", r"\bmaischberger\b", r"\banne will\b", r"\bmarkus lanz\b",
    r"\bmaybrit illner\b", r"\bcaren miosga\b", r"\bpresseclub\b", r"\bwahlarena\b", r"\btriell\b", r"\bduell\b",
]
EVENT_RE = re.compile("|".join(EVENT_KEYWORDS), re.I)
# Sendungen, die zugleich Personennamen sind, bleiben Personen (Moderator/in als Marke)
SHOW_IS_PERSON = {"markus lanz", "anne will", "maybrit illner", "caren miosga", "sandra maischberger"}
MEDIA_FORMAT_RE = re.compile(
    r"\b(sendung|talk|talkshow|show|podcast|dokumentation|doku|reportage|folge|episode|staffel|livestream|"
    r"stream|video|serie|tagesschau|tagesthemen|heute[- ]journal|morgenmagazin|mittagsmagazin|brennpunkt|"
    r"panorama|monitor|kontraste|fakt|frontal|report|exakt|umschau|sachsenspiegel|presseclub|wahlarena)\b", re.I)

DATE_RE = re.compile(
    r"(\b\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\s?(januar|februar|märz|april|mai|juni|"
    r"juli|august|september|oktober|november|dezember|jan|feb|mär|apr|jun|jul|aug|sep|sept|okt|nov|dez)\b)", re.I)
MONTH_RE = re.compile(r"^(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b", re.I)
WEEKDAY_RE = re.compile(r"^(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)\b", re.I)
UNIT_WORDS = {"tagen", "tage", "tag", "wochen", "woche", "monate", "monaten", "monat", "jahre", "jahren", "jahr",
              "uhr", "prozent", "euro", "eur", "mio", "mrd", "millionen", "milliarden", "stunden", "minuten",
              "kilometer", "km", "meter", "personen", "menschen", "teilnehmer", "stimmen", "sitze", "mandate",
              "seiten", "mal", "fälle", "fällen"}

# Häufige Vornamen (de/en/tr/pl u. a.) – nur zur Konfidenzschätzung und Reihenfolge-Erkennung
FIRST_NAMES = set("""
alexander andreas andre andrea anna anne anja anke anton angela angelika annette antje armin arne astrid axel
barbara bastian beate benjamin bernd bernhard bettina birgit bjoern björn bodo boris brigitte britta bruno carsten
carina carla carmen carolin caroline catharina cathrin christa christel christian christiane christina christine
christoph christopher claudia clemens cornelia dagmar daniel daniela david denis dennis detlef dieter dietmar dirk
dominik dora doris dorothea eberhard eckhard edgar edith eduard egon elisabeth elke ellen emil enrico erich erika
erik ernst erwin eva fabian falk felix ferdinand florian frank franz franziska frauke friedrich fritz gabriele gabi
georg gerd gerda gerhard gerlinde gernot gert gisela gregor gudrun guenter günter günther gunter gustav hanna hannah
hannelore hanno hans harald hartmut heidi heike heinrich heinz helga helmut hendrik henning henry herbert hermann
hilde holger horst hubert hugo ilona ilse ina ines inga inge ingeborg ingo ingrid irene iris irmgard isabel
isabell isabella jan jana janine jasmin jens jessica joachim jochen johann johanna johannes jonas jörg joerg josef
joseph juergen jürgen julia julian juliane jutta kai karin karl karla karsten katharina kathrin katja katrin kay
kerstin kevin klaus knut konrad konstantin kristin kurt lars laura lea lena leon leonie lisa lothar luca lucas
ludwig luise lukas lutz maik manfred manuel manuela marc marcel marco marcus margarete margit maria marianne marie
marina mario marion marita mark marko markus marlene marlies martha martin martina mathias matthias max maximilian
melanie michael michaela mike mirko monika moritz nadine nadja nancy natalie nicole niklas nico nils nina norbert
olaf oliver olga oskar otto patrick paul paula peter petra philipp philip pia rainer ralf ralph ramona regina
reinhard reinhold renate rene rené richard rita robert roland rolf roman rosemarie rudolf rüdiger ruediger ruth
sabine sabrina sandra sarah sascha sebastian sigrid silke silvia simon simone sonja sophia sophie stefan steffen
steffi stephan stephanie susanne sven swen sylvia tanja theo theodor thomas thorsten tilo tim timo tino tobias tom
torsten ulf ulla ulrich ulrike ursula uta ute uwe vanessa vera verena viktor viktoria volker walter waltraud werner
wilfried wilhelm willi wolfgang yvonne zoe
ahmed ali ayse aylin can cem deniz emre fatma hasan hüseyin ibrahim kemal mehmet murat mustafa osman ömer selin
agnieszka aleksander andrzej anita ewa jacek jakub janusz katarzyna krzysztof magdalena malgorzata marek marta
pawel piotr tomasz wojciech zofia
ben charlotte elias emma finn hanna leo liam luis mia noah sophie tom
""".split())


# --------------------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------------------

def strip_accents(s: str) -> str:
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_key(s: str) -> str:
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return MULTI_WS_RE.sub(" ", s).strip()


def parse_list_field(raw: str) -> list[str]:
    """Postgres-Array-Literal, JSON-Array oder ';'/'|'-getrennte Liste -> Liste von Strings."""
    raw = (raw or "").strip()
    if not raw or raw in ("{}", "[]", "null", "NULL"):
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            out = []
            for item in data:
                if isinstance(item, dict):
                    v = item.get("value") or item.get("email") or item.get("name") or item.get("handle")
                    if v:
                        out.append(str(v))
                elif item is not None:
                    out.append(str(item))
            return out
        except json.JSONDecodeError:
            pass
    if raw.startswith("{") and raw.endswith("}"):
        inner = raw[1:-1]
        items, cur, quoted, esc = [], "", False, False
        for ch in inner:
            if esc:
                cur += ch
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                quoted = not quoted
            elif ch == "," and not quoted:
                items.append(cur)
                cur = ""
            else:
                cur += ch
        if cur or items:
            items.append(cur)
        return [i.strip() for i in items if i.strip() and i.strip().upper() != "NULL"]
    return [p.strip() for p in re.split(r"[;|]", raw) if p.strip()]


def title_case_token(tok: str) -> str:
    if not tok:
        return tok
    if tok.lower() in PARTICLES:
        return tok.lower()
    parts = re.split(r"(-)", tok)
    out = []
    for p in parts:
        if p == "-" or not p:
            out.append(p)
        elif p[:2].lower() == "mc" and len(p) > 2:
            out.append("Mc" + p[2:3].upper() + p[3:].lower())
        elif "'" in p:
            out.append("'".join(x[:1].upper() + x[1:].lower() for x in p.split("'")))
        else:
            out.append(p[:1].upper() + p[1:].lower())
    return "".join(out)


def is_all_caps(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def looks_like_name_token(tok: str) -> bool:
    if not tok:
        return False
    if tok.lower() in PARTICLES:
        return True
    if INITIAL_RE.match(tok):
        return True
    if DIGIT_RE.search(tok):
        return False
    core = tok.replace("-", "").replace("'", "").replace(".", "")
    if not core.isalpha():
        return False
    return tok[0].isupper() or tok[0] in "ÄÖÜ"


# --------------------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------------------

@dataclass
class Person:
    id: str
    name: str
    aliases: list[str]
    emails: list[str]
    party: str
    source: str
    created_at: str
    created_by: str
    birth_date: str = ""
    connections: int = 0
    # Ergebnis
    entscheidung: str = ""
    name_neu: str = ""
    kanonische_id: str = ""
    unterkategorie: str = ""
    konfidenz: float = 0.0
    begruendung: str = ""
    # intern
    name_clean: str = ""          # korrigierter Name (auch wenn person_ok)
    key: str = ""                 # Normalisierungsschlüssel (voller Name)
    key_fl: str = ""              # Schlüssel (Vorname + Nachname)
    has_middle: bool = False
    fixes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Schritt 1: Namensreparatur
# --------------------------------------------------------------------------------------

def clean_person_name(raw: str) -> tuple[str, list[str], str]:
    """Liefert (bereinigter Name, Liste der angewandten Korrekturen, abgetrennter Zusatz)."""
    fixes: list[str] = []
    extra = ""
    s = raw.strip()

    if JUNK_CHARS_RE.search(s):
        s = JUNK_CHARS_RE.sub(" ", s)
        fixes.append("Sonderzeichen entfernt")

    m = PREFIX_LETTER_RE.match(s)
    if m:
        s = s[m.end():]
        fixes.append(f"Präfix '{m.group(0).strip()}' entfernt")

    m = LEADING_PAREN_RE.match(s)
    if m:
        extra = (extra + " " + m.group(0).strip()).strip()
        s = s[m.end():]
        fixes.append("Klammerzusatz entfernt")
    while True:
        m = TRAILING_PAREN_RE.search(s)
        if not m or m.start() == 0:
            break
        extra = (extra + " " + m.group(0).strip()).strip()
        s = s[:m.start()]
        if "Klammerzusatz entfernt" not in fixes:
            fixes.append("Klammerzusatz entfernt")

    # "Name - AfD", "Name | MdB", "Name / Journalist"  (nur wenn davor ein plausibler Name steht)
    m = TRAILING_SEP_RE.search(s)
    if m and m.start() > 0:
        head = s[:m.start()].strip()
        if len(head.split()) >= 2 or "," in head:
            extra = (extra + " " + s[m.start():].strip(" -–|/,;:")).strip()
            s = head
            fixes.append("Zusatz nach Trennzeichen entfernt")

    s = s.strip(" .,;:-–/|")
    s = MULTI_WS_RE.sub(" ", s)

    # "Nachname, Vorname" bzw. "Nachname,Vorname"
    if s.count(",") == 1:
        last, first = [p.strip() for p in s.split(",")]
        if last and first:
            s = f"{first} {last}"
            fixes.append("Reihenfolge 'Nachname, Vorname' gedreht")
    elif s.count(",") > 1:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        # "Nachname, Vorname, Titel"  -> Titel wird unten entfernt
        if len(parts) >= 2:
            s = f"{parts[1]} {parts[0]} " + " ".join(parts[2:])
            fixes.append("Reihenfolge 'Nachname, Vorname' gedreht")

    tokens = s.split()
    kept = []
    removed_titles = []
    for tok in tokens:
        t = tok.lower().strip()
        if t in TITLES or t.rstrip(".") in TITLES or re.fullmatch(r"(dr|prof|dipl|mag|ing|med|jur|phil|rer|nat|h\.?c)\.?(-[a-z]+\.?)*", t):
            removed_titles.append(tok)
            continue
        kept.append(tok)
    if removed_titles:
        fixes.append("Titel entfernt: " + " ".join(removed_titles))
    tokens = kept

    # Groß-/Kleinschreibung
    new_tokens = []
    case_fixed = False
    for tok in tokens:
        if is_all_caps(tok) or (tok[:1].islower() and tok.lower() not in PARTICLES):
            new_tokens.append(title_case_token(tok))
            case_fixed = True
        else:
            new_tokens.append(tok)
    if case_fixed:
        fixes.append("Groß-/Kleinschreibung korrigiert")
    tokens = new_tokens

    # "NACHNAME Vorname" (Versalien-Nachname vorn) -> "Vorname Nachname"
    if len(tokens) >= 2 and is_all_caps(raw.split()[0]) and not is_all_caps(raw.split()[-1]) and "," not in raw:
        tokens = tokens[1:] + tokens[:1]
        fixes.append("Reihenfolge 'NACHNAME Vorname' gedreht")
    # "Nachname Vorname [Vorname]" (Vornamen am Lexikon erkennbar, erstes Token nicht)
    elif 2 <= len(tokens) <= 4:
        first, rest = tokens[0], tokens[1:]
        if (norm_key(first) not in FIRST_NAMES and first.lower() not in PARTICLES
                and all(norm_key(t) in FIRST_NAMES for t in rest)):
            tokens = rest + [first]
            fixes.append("Reihenfolge 'Nachname Vorname' gedreht")

    cleaned = " ".join(tokens).strip()
    if cleaned != raw.strip() and not fixes:
        fixes.append("Leerzeichen/Interpunktion bereinigt")
    return cleaned, fixes, extra


# --------------------------------------------------------------------------------------
# Schritt 2: Kategorisierung (regelbasiert)
# --------------------------------------------------------------------------------------

def classify(p: Person) -> None:
    raw = p.name.strip()
    low = raw.lower()
    nk = norm_key(raw)

    def nonperson(sub: str, conf: float, why: str) -> None:
        p.entscheidung = "keine_person"
        p.unterkategorie = sub
        p.konfidenz = conf
        p.begruendung = why

    def unklar(conf: float, why: str) -> None:
        p.entscheidung = "unklar"
        p.konfidenz = conf
        p.begruendung = why

    if not raw:
        return nonperson("fragment", 0.99, "Leerer Name.")
    if EMAIL_RE.match(raw) or (EMAIL_ANYWHERE_RE.search(raw) and len(raw.split()) <= 2):
        return nonperson("email", 0.99, "Name ist eine E-Mail-Adresse.")
    if URL_RE.search(raw) and len(raw.split()) <= 3:
        return nonperson("sonstiges", 0.95, "Name ist eine URL/Domain.")
    if PHONE_RE.match(raw):
        return nonperson("fragment", 0.97, "Name ist eine Telefonnummer/Zahlenfolge.")
    if re.fullmatch(r"[\d\s.,:/%-]+", raw):
        return nonperson("fragment", 0.99, "Name besteht nur aus Zahlen/Zeichen.")
    if len(nk.replace(" ", "")) <= 2:
        return nonperson("fragment", 0.98, "Name ist zu kurz (max. 2 Zeichen).")

    tokens = raw.split()
    # Zahl + Einheit ("30 Tagen", "14 Uhr", "3 Prozent")
    if DIGIT_RE.search(tokens[0]) and (len(tokens) == 1 or tokens[-1].lower().strip(".,") in UNIT_WORDS):
        return nonperson("fragment", 0.97, "Zahl mit Einheit/Zeitangabe, kein Name.")
    if DATE_RE.search(raw) and not EVENT_RE.search(raw):
        return nonperson("fragment", 0.9, "Datumsangabe statt Name.")
    if MONTH_RE.match(raw) or WEEKDAY_RE.match(raw):
        return nonperson("fragment", 0.9, "Monats-/Wochentagsangabe statt Name.")

    # Sendungen mit Personennamen bleiben Personen
    if nk in SHOW_IS_PERSON:
        pass
    elif EVENT_RE.search(raw) and not (len(tokens) == 2 and all(looks_like_name_token(t) for t in tokens) and not MEDIA_FORMAT_RE.search(raw) and norm_key(tokens[0]) in FIRST_NAMES):
        if MEDIA_FORMAT_RE.search(raw):
            return nonperson("sonstiges", 0.9, "Sendung/Medienformat, keine Person.")
        if re.search(r"parteitag|konvent|wahl", low):
            return nonperson("ereignis", 0.97, "Parteitag/Wahl-Ereignis, keine Person.")
        return nonperson("ereignis", 0.88, "Veranstaltungs-/Ereignisbezeichnung, keine Person.")

    # Partei allein oder mit Zusatz
    if nk in PARTY_TOKENS or any(nk.startswith(pt + " ") for pt in PARTY_TOKENS if " " not in pt and len(pt) > 2):
        if len(tokens) <= 3 and not any(norm_key(t) in FIRST_NAMES for t in tokens):
            return nonperson("organisation", 0.95, "Parteibezeichnung, keine Person.")

    if ORG_RE.search(raw):
        # Ausnahme: zweiteiliger Name, bei dem ein Token nur zufällig Schlüsselwort ist ("Peter Bank", "Anna Markt")
        if len(tokens) == 2 and all(looks_like_name_token(t) for t in tokens) and norm_key(tokens[0]) in FIRST_NAMES:
            pass
        elif SERVICE_RE.search(raw) and len(tokens) <= 3 and not any(norm_key(t) in FIRST_NAMES for t in tokens):
            return nonperson("sonstiges", 0.9, "Service-/System-Adresse, keine Person.")
        else:
            return nonperson("organisation", 0.9, "Organisations-/Behörden-/Firmenbezeichnung.")

    if "&" in raw or " + " in raw:
        return nonperson("organisation", 0.85, "Verbund aus mehreren Namen ('&'), eher Firma/Kanzlei.")
    if re.search(r"\b(und|and|u\.)\b", low) and len(tokens) >= 3:
        return unklar(0.5, "Mehrere Personen in einem Eintrag ('und'); Aufteilung nötig.")

    # Fragmente: Kleinschreibung am Anfang, Artikel, Satzfetzen
    if tokens[0][:1].islower() and norm_key(tokens[0]) not in FIRST_NAMES and tokens[0].lower() not in PARTICLES:
        return nonperson("fragment", 0.88, "Beginnt kleingeschrieben, Satzfragment statt Name.")
    if tokens[0].lower() in {"der", "die", "das", "ein", "eine", "dem", "den", "des", "the", "a", "an", "mit", "für",
                            "von", "vom", "zum", "zur", "am", "im", "in", "an", "auf", "nach", "über", "unter"} and len(tokens) >= 2 and tokens[0].lower() not in {"von"}:
        return nonperson("fragment", 0.9, "Beginnt mit Artikel/Präposition, Satzfragment.")

    # Namensreparatur anwenden
    cleaned, fixes, extra = clean_person_name(raw)
    ctoks = cleaned.split()
    name_like = [t for t in ctoks if t.lower() not in PARTICLES]

    if not ctoks:
        return nonperson("fragment", 0.9, "Nach Entfernen von Titeln/Zusätzen bleibt kein Name übrig.")

    if len(name_like) == 1:
        tok = name_like[0]
        if norm_key(tok) in FIRST_NAMES:
            return nonperson("fragment", 0.8, "Nur ein Vorname ohne Nachname.")
        if INITIAL_RE.match(tok):
            return nonperson("fragment", 0.95, "Nur ein Initial.")
        if p.connections >= 3 or p.party or p.emails:
            return unklar(0.45, "Einzelnes Wort mit Verbindungen/Attributen; Nachname allein oder Fragment.")
        return nonperson("fragment", 0.7, "Einzelnes Wort ohne Vornamen und ohne Verbindungen, kein verwertbarer Name.")

    if len(name_like) > 6:
        return nonperson("fragment", 0.8, "Mehr als sechs Wörter, Satzfragment statt Personenname.")

    bad = [t for t in ctoks if not looks_like_name_token(t)]
    if bad:
        if DIGIT_RE.search(cleaned):
            return nonperson("fragment", 0.85, "Enthält Ziffern, kein Personenname.")
        return unklar(0.4, f"Untypische Namensbestandteile: {' '.join(bad)}.")

    # Jetzt: plausibler Personenname
    conf = 0.8
    if norm_key(name_like[0]) in FIRST_NAMES:
        conf += 0.15
    if p.party or p.source or p.emails or p.connections > 0:
        conf += 0.04
    if len(name_like) >= 5:
        conf -= 0.2
    conf = round(min(conf, 0.99), 2)

    p.name_clean = cleaned
    if fixes:
        p.entscheidung = "person_korrigieren"
        p.name_neu = cleaned
        p.konfidenz = conf
        p.begruendung = "; ".join(fixes) + (f" (Zusatz: {extra})" if extra else "") + "."
    else:
        p.entscheidung = "person_ok"
        p.name_neu = ""
        p.konfidenz = conf
        p.begruendung = "Plausibler Personenname (Vorname Nachname), keine Auffälligkeiten."


# --------------------------------------------------------------------------------------
# Schritt 3: Dubletten
# --------------------------------------------------------------------------------------

def person_keys(p: Person) -> None:
    name = p.name_clean or p.name
    toks = [t for t in norm_key(name).split() if t not in {norm_key(x) for x in PARTICLES}]
    p.key = " ".join(norm_key(name).split())
    if len(toks) >= 2:
        p.key_fl = f"{toks[0]} {toks[-1]}"
        p.has_middle = len(toks) > 2
    else:
        p.key_fl = p.key
        p.has_middle = False


def norm_party(s: str) -> str:
    k = norm_key(s or "")
    k = k.replace("buendnis 90 die gruenen", "gruene").replace("die gruenen", "gruene").replace("die linke", "linke")
    return k


def conflict(a: Person, b: Person) -> str | None:
    pa, pb = norm_party(a.party), norm_party(b.party)
    if pa and pb and pa != pb:
        return f"Partei widerspricht ({a.party} vs. {b.party})"
    if a.birth_date and b.birth_date and a.birth_date[:10] != b.birth_date[:10]:
        return "Geburtsdatum widerspricht"
    if a.created_by and b.created_by and a.created_by != b.created_by:
        return "verschiedene Benutzer (created_by), vermutlich bewusste Kopie"
    ea, eb = {e.lower() for e in a.emails}, {e.lower() for e in b.emails}
    if ea and eb and not (ea & eb):
        return "E-Mail-Adressen widersprechen"
    return None


def canonical_score(p: Person) -> tuple:
    score = 0.0
    score += 3 if p.source else 0
    score += 2 if p.party else 0
    score += 2 if p.birth_date else 0
    score += min(len(p.emails), 3)
    score += min(len(p.aliases) * 0.5, 2)
    score += 1 if p.created_by else 0            # in der Oberfläche sichtbar
    score += 1 if p.entscheidung == "person_ok" else 0
    import math
    score += 2 * math.log1p(p.connections)
    # älteres created_at als Tiebreak (negativ, damit kleiner = besser nach Umkehr)
    return (score, -(_ts(p.created_at)))


def _ts(s: str) -> float:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace("+00", "+0000") if s.endswith("+00") else s, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def split_by_conflicts(group: list[Person]) -> list[list[Person]]:
    """Zerlegt eine Kandidatengruppe in widerspruchsfreie Teilgruppen (greedy, deterministisch)."""
    ordered = sorted(group, key=canonical_score, reverse=True)
    buckets: list[list[Person]] = []
    for p in ordered:
        placed = False
        for b in buckets:
            if all(conflict(p, q) is None for q in b):
                b.append(p)
                placed = True
                break
        if not placed:
            buckets.append([p])
    return buckets


def dedupe(persons: list[Person]) -> dict:
    stats = {"gruppen": 0, "dubletten": 0, "konflikt_getrennt": 0}
    cands = [p for p in persons if p.entscheidung in ("person_ok", "person_korrigieren")]
    for p in cands:
        person_keys(p)

    # Alias-Index: Alias (normalisiert) -> Personen, die diesen Alias tragen
    alias_index: dict[str, set[str]] = defaultdict(set)
    by_id = {p.id: p for p in cands}
    for p in cands:
        for a in p.aliases:
            ck, _, _ = clean_person_name(a)
            k = norm_key(ck)
            if len(k.split()) >= 2:
                alias_index[k].add(p.id)

    # Union-Find über: gleicher voller Schlüssel; Alias == Name eines anderen; Vor+Nachname gleich
    parent: dict[str, str] = {p.id: p.id for p in cands}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_key: dict[str, list[Person]] = defaultdict(list)
    by_fl: dict[str, list[Person]] = defaultdict(list)
    for p in cands:
        by_key[p.key].append(p)
        by_fl[p.key_fl].append(p)
    for k, ps in by_key.items():
        for q in ps[1:]:
            union(ps[0].id, q.id)
    for p in cands:
        for other_id in alias_index.get(p.key, ()):
            if other_id != p.id:
                union(p.id, other_id)
    # Gleiche Namensbestandteile in anderer Reihenfolge ("Schmidt Jan Wenzel" vs. "Jan Wenzel Schmidt")
    for p in cands:
        toks = p.key.split()
        if len(toks) >= 2:
            rotated = " ".join(toks[1:] + toks[:1])
            for q in by_key.get(rotated, ()):
                union(p.id, q.id)
    # Vor+Nachname gleich, aber nur wenn höchstens eine Seite Zwischennamen trägt
    for k, ps in by_fl.items():
        if len(ps) < 2:
            continue
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                a, b = ps[i], ps[j]
                if a.key == b.key:
                    continue
                if a.has_middle and b.has_middle:
                    continue  # unterschiedliche Zwischennamen -> keine Vermutung
                union(a.id, b.id)

    groups: dict[str, list[Person]] = defaultdict(list)
    for p in cands:
        groups[find(p.id)].append(p)

    for root, group in groups.items():
        if len(group) < 2:
            continue
        subgroups = split_by_conflicts(group)
        if len(subgroups) > 1:
            stats["konflikt_getrennt"] += 1
            # Hinweis auf nicht zusammengelegte Namensvettern
            for sg in subgroups:
                for p in sg:
                    others = [q for osg in subgroups if osg is not sg for q in osg]
                    why = conflict(p, others[0]) if others else None
                    if why:
                        p.begruendung = (p.begruendung.rstrip(".") +
                                         f"; gleichnamig mit {others[0].id}, nicht zusammengelegt: {why}.")
        for sg in subgroups:
            if len(sg) < 2:
                continue
            stats["gruppen"] += 1
            sg.sort(key=canonical_score, reverse=True)
            canon = sg[0]
            dup_ids = [q.id for q in sg[1:]]
            canon.kanonische_id = canon.id
            # Beste Schreibweise für den kanonischen Namen: Umlaute/ß vor Transliteration, sonst kanonischer Name
            canon_name = canon.name_clean or canon.name
            best = max(sg, key=lambda x: (norm_key((x.name_clean or x.name).split()[0]) in FIRST_NAMES,
                                          sum(1 for ch in (x.name_clean or x.name) if ord(ch) > 127), x is canon))
            best_name = best.name_clean or best.name
            if best_name != canon_name and sorted(norm_key(best_name).split()) == sorted(norm_key(canon_name).split()):
                canon.name_clean = best_name
                canon.name_neu = best_name
                canon.entscheidung = "person_korrigieren"
                canon.begruendung = (canon.begruendung.rstrip(".") +
                                     f"; Schreibweise mit Umlaut/ß aus Dublette {best.id} übernommen.")
            canon.begruendung = (canon.begruendung.rstrip(".") +
                                 f"; kanonisch für {len(dup_ids)} Dublette(n): {', '.join(dup_ids)}.")
            canon_alias_keys = {norm_key(clean_person_name(a)[0]) for a in canon.aliases}
            for q in sg[1:]:
                stats["dubletten"] += 1
                exact = q.key == canon.key
                q_alias_keys = {norm_key(clean_person_name(a)[0]) for a in q.aliases}
                via_alias = (not exact) and (q.key in canon_alias_keys or canon.key in q_alias_keys)
                shared_mail = bool({e.lower() for e in q.emails} & {e.lower() for e in canon.emails})
                conf = 0.95 if exact else (0.85 if sorted(q.key.split()) == sorted(canon.key.split()) else 0.8)
                if shared_mail:
                    conf = min(0.99, conf + 0.04)
                if norm_party(q.party) and norm_party(q.party) == norm_party(canon.party):
                    conf = min(0.99, conf + 0.02)
                if exact:
                    basis = "identischer normalisierter Name"
                elif sorted(q.key.split()) == sorted(canon.key.split()):
                    basis = "gleiche Namensbestandteile in anderer Reihenfolge"
                elif via_alias:
                    basis = "Name ist als Alias des anderen Datensatzes hinterlegt"
                else:
                    basis = "Vor- und Nachname identisch, Zwischenname nur auf einer Seite"
                q.entscheidung = "dublette"
                q.kanonische_id = canon.id
                q.name_neu = canon.name_clean or canon.name
                q.konfidenz = round(conf, 2)
                q.begruendung = (f"Dublette von {canon.id} ('{canon.name}'): {basis}"
                                 + (", gemeinsame E-Mail" if shared_mail else "")
                                 + f"; kanonisch wegen Quelle/Partei/Verbindungen (Score {canonical_score(canon)[0]:.1f}).")
    return stats


# --------------------------------------------------------------------------------------
# Ein-/Ausgabe
# --------------------------------------------------------------------------------------

def read_persons(path: Path, counts_path: Path | None) -> list[Person]:
    counts: dict[str, int] = {}
    if counts_path and counts_path.exists():
        with counts_path.open(newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            for row in rd:
                pid = (row.get("person_id") or row.get("id") or "").strip()
                try:
                    counts[pid] = int(float(row.get("anzahl_verbindungen") or row.get("count") or 0))
                except ValueError:
                    counts[pid] = 0
    persons: list[Person] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        cols = {c.lower(): c for c in rd.fieldnames or []}

        def g(row, *names):
            for n in names:
                if n in cols:
                    return (row.get(cols[n]) or "").strip()
            return ""

        for row in rd:
            pid = g(row, "id")
            if not pid:
                continue
            persons.append(Person(
                id=pid,
                name=g(row, "name", "canonical_name"),
                aliases=parse_list_field(g(row, "aliases")),
                emails=parse_list_field(g(row, "emails")),
                party=g(row, "party", "partei"),
                source=g(row, "source", "quelle"),
                created_at=g(row, "created_at"),
                created_by=g(row, "created_by", "user_id"),
                birth_date=g(row, "birth_date", "geburtsdatum"),
                connections=counts.get(pid, 0),
            ))
    return persons


def apply_einzelbewertung(persons: list[Person], path: Path) -> int:
    """Spielt manuelle/LLM-Einzelbewertungen der Restmenge zurück (Spalten: id, entscheidung_neu, name_neu,
    kanonische_id, unterkategorie, begruendung)."""
    by_id = {p.id: p for p in persons}
    n = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            p = by_id.get((row.get("id") or "").strip())
            dec = (row.get("entscheidung_neu") or row.get("entscheidung") or "").strip()
            if not p or not dec or dec == "unklar":
                continue
            p.entscheidung = dec
            p.name_neu = (row.get("name_neu") or "").strip()
            p.kanonische_id = (row.get("kanonische_id") or "").strip()
            p.unterkategorie = (row.get("unterkategorie") or "").strip()
            p.konfidenz = float(row.get("konfidenz") or 0.7)
            p.begruendung = (row.get("begruendung") or "Einzelbewertung.").strip()
            if dec in ("person_ok", "person_korrigieren"):
                p.name_clean = p.name_neu or p.name
            n += 1
    return n


def write_decisions(persons: list[Person], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(DECISION_COLUMNS)
        for p in persons:
            w.writerow([p.id, p.name, p.entscheidung, p.name_neu, p.kanonische_id, p.unterkategorie,
                        f"{p.konfidenz:.2f}", p.begruendung])


def write_restmenge(persons: list[Person], path: Path) -> int:
    rest = [p for p in persons if p.entscheidung == "unklar"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "aliases", "emails", "party", "source", "created_by", "anzahl_verbindungen",
                    "begruendung_regel", "entscheidung_neu", "name_neu", "kanonische_id", "unterkategorie",
                    "konfidenz", "begruendung"])
        for p in rest:
            w.writerow([p.id, p.name, "; ".join(p.aliases), "; ".join(p.emails), p.party, p.source, p.created_by,
                        p.connections, p.begruendung, "", "", "", "", "", ""])
    return len(rest)


def sql_str(s: str | None) -> str:
    if s is None or s == "":
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def write_staging_sql(persons: list[Person], path: Path, run_id: str) -> None:
    """Erzeugt die Staging-INSERTs für persons_cleanup_decisions (idempotent, eigene Transaktion)."""
    with path.open("w", encoding="utf-8") as fh:
        fh.write("-- Automatisch erzeugt von scripts/personen-klassifikation.py – nicht von Hand bearbeiten.\n")
        fh.write(f"-- Lauf: {run_id}, Einträge: {len(persons)}\n")
        fh.write("BEGIN;\n")
        fh.write("""CREATE TABLE IF NOT EXISTS persons_cleanup_decisions (
  run_id         TEXT NOT NULL,
  id             UUID NOT NULL,
  name_alt       TEXT,
  entscheidung   TEXT NOT NULL CHECK (entscheidung IN ('person_ok','person_korrigieren','dublette','keine_person','unklar')),
  name_neu       TEXT,
  kanonische_id  UUID,
  unterkategorie TEXT,
  konfidenz      NUMERIC(3,2),
  begruendung    TEXT,
  applied_at     TIMESTAMPTZ,
  PRIMARY KEY (run_id, id)
);
""")
        fh.write(f"DELETE FROM persons_cleanup_decisions WHERE run_id = {sql_str(run_id)} AND applied_at IS NULL;\n")
        batch: list[str] = []

        def flush():
            if batch:
                fh.write("INSERT INTO persons_cleanup_decisions (run_id, id, name_alt, entscheidung, name_neu, "
                         "kanonische_id, unterkategorie, konfidenz, begruendung) VALUES\n")
                fh.write(",\n".join(batch))
                fh.write("\nON CONFLICT (run_id, id) DO UPDATE SET name_alt = EXCLUDED.name_alt, "
                         "entscheidung = EXCLUDED.entscheidung, name_neu = EXCLUDED.name_neu, "
                         "kanonische_id = EXCLUDED.kanonische_id, unterkategorie = EXCLUDED.unterkategorie, "
                         "konfidenz = EXCLUDED.konfidenz, begruendung = EXCLUDED.begruendung "
                         "WHERE persons_cleanup_decisions.applied_at IS NULL;\n")
                batch.clear()

        for p in persons:
            batch.append(f"({sql_str(run_id)}, {sql_str(p.id)}::uuid, {sql_str(p.name)}, {sql_str(p.entscheidung)}, "
                         f"{sql_str(p.name_neu or None)}, {sql_str(p.kanonische_id or None)}"
                         f"{'::uuid' if p.kanonische_id else ''}, {sql_str(p.unterkategorie or None)}, "
                         f"{p.konfidenz:.2f}, {sql_str(p.begruendung)})")
            if len(batch) >= 500:
                flush()
        flush()
        fh.write("COMMIT;\n")


def write_summary(persons: list[Person], stats: dict, path: Path, run_id: str) -> str:
    c = Counter(p.entscheidung for p in persons)
    sub = Counter(p.unterkategorie for p in persons if p.entscheidung == "keine_person")
    by_user = Counter((p.created_by or "NULL") for p in persons)
    lines = [f"# Personenregister – Zusammenfassung ({run_id})", "",
             f"Einträge gesamt: {len(persons)}", "",
             "| Entscheidung | Anzahl |", "|---|---:|"]
    for k in ("person_ok", "person_korrigieren", "dublette", "keine_person", "unklar"):
        lines.append(f"| {k} | {c.get(k, 0)} |")
    lines += ["", "Unterkategorien keine_person:", "", "| Unterkategorie | Anzahl |", "|---|---:|"]
    for k in ("email", "organisation", "ereignis", "fragment", "sonstiges"):
        lines.append(f"| {k} | {sub.get(k, 0)} |")
    lines += ["", f"Dubletten-Gruppen: {stats['gruppen']} (zusammengelegte Einträge: {stats['dubletten']}; "
              f"Gruppen wegen Widerspruch bei Partei/Geburtsdatum/Benutzer/E-Mail getrennt: {stats['konflikt_getrennt']})",
              "", "Einträge nach created_by (Sichtbarkeit in der Oberfläche hängt an persons.user_id):", "",
              "| created_by | Anzahl |", "|---|---:|"]
    for k, v in by_user.most_common(10):
        lines.append(f"| {k} | {v} |")
    remaining = c.get("person_ok", 0) + c.get("person_korrigieren", 0)
    lines += ["", f"Verbleibende Personen nach Bereinigung: {remaining}", ""]
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default="exports/personen-export.csv")
    ap.add_argument("--counts", default="exports/person_connections_counts.csv")
    ap.add_argument("--out", default="exports/personen-entscheidungen.csv")
    ap.add_argument("--rest", default="exports/personen-restmenge.csv")
    ap.add_argument("--summary", default="exports/personen-zusammenfassung.md")
    ap.add_argument("--staging-sql", default="scripts/personen-bereinigung-daten.sql")
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--einzelbewertung", help="CSV mit bewerteter Restmenge (Spalte entscheidung_neu)")
    args = ap.parse_args()

    export = Path(args.export)
    if not export.exists():
        print(f"FEHLER: {export} nicht gefunden.", file=sys.stderr)
        return 2
    persons = read_persons(export, Path(args.counts))
    print(f"{len(persons)} Einträge gelesen.")

    for p in persons:
        classify(p)
    if args.einzelbewertung:
        n = apply_einzelbewertung(persons, Path(args.einzelbewertung))
        print(f"{n} Einzelbewertungen übernommen.")
    stats = dedupe(persons)

    # Konsistenz: Dubletten dürfen nur auf Datensätze zeigen, die selbst bleiben
    by_id = {p.id: p for p in persons}
    for p in persons:
        if p.entscheidung == "dublette":
            c = by_id.get(p.kanonische_id)
            assert c and c.entscheidung in ("person_ok", "person_korrigieren"), p.id

    write_decisions(persons, Path(args.out))
    rest_n = write_restmenge(persons, Path(args.rest))
    write_staging_sql(persons, Path(args.staging_sql), args.run_id)
    print(write_summary(persons, stats, Path(args.summary), args.run_id))
    print(f"Restmenge für Einzelbewertung: {rest_n} -> {args.rest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
