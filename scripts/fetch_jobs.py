#!/usr/bin/env python3
"""Radar de trabajo remoto: baja vacantes de feeds publicos, las etiqueta por
area y region, y escribe data/jobs.json.

Solo usa la libreria estandar de Python (no hay nada que instalar).

Uso:
    python scripts/fetch_jobs.py            # actualiza data/jobs.json
    python scripts/fetch_jobs.py --check    # sale con error si alguna fuente fallo
"""
import hashlib
import html as htmllib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "keywords.json"
COMPANIES_PATH = ROOT / "config" / "companies.json"
EXCLUDED_PATH = ROOT / "data" / "employer_excluded.json"
OUT_PATH = ROOT / "data" / "jobs.json"

USER_AGENT = "remote-jobs-radar/0.1 (personal project; every job links back to its source)"
NOW = datetime.now(timezone.utc)

SOURCE_HOMES = {
    "RemoteOK": "https://remoteok.com",
    "Remotive": "https://remotive.com",
    "Himalayas": "https://himalayas.app",
    "We Work Remotely": "https://weworkremotely.com",
    "Jobicy": "https://jobicy.com",
    "Working Nomads": "https://www.workingnomads.com",
}

# ---------------------------------------------------------------- utilidades


def norm(text):
    """Minusculas, sin acentos, solo letras y numeros separados por espacios."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def http_get(url, retries=2, timeout=40):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise  # no insistir si nos limitan
            last = e
        except Exception as e:  # red, timeout, etc.
            last = e
        time.sleep(2 * (attempt + 1))
    raise last


def http_json(url):
    return json.loads(http_get(url).decode("utf-8"))


def parse_dt(value):
    """Acepta epoch (s o ms), ISO 8601 y RFC 822. Devuelve datetime UTC o None."""
    if value in (None, "", 0, "0"):
        return None
    try:
        if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,13}", str(value)):
            n = float(value)
            if n > 1e11:
                n /= 1000
            return datetime.fromtimestamp(n, tz=timezone.utc)
        s = str(value).strip()
        if re.search(r"[A-Za-z]{3},", s):
            dt = parsedate_to_datetime(s)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("["):
            try:
                return [str(x) for x in json.loads(v.replace("'", '"')) if x]
            except Exception:
                pass
        return [p.strip() for p in re.split(r"[,;]", v) if p.strip()]
    return [str(value)]


def money(n):
    n = float(n)
    return f"{n / 1000:g}k" if n >= 1000 else f"{n:g}"


def fmt_salary(low, high, currency="USD", period="year"):
    try:
        low = float(low or 0)
        high = float(high or 0)
    except Exception:
        return ""
    if not low and not high:
        return ""
    cur = currency or "USD"
    if low and high and low != high:
        rng = f"{money(low)}-{money(high)}"
    else:
        rng = money(high or low)
    return f"{cur} {rng} / {period}"


def safe_url(url):
    url = (url or "").strip()
    return url if re.match(r"^https?://", url, re.I) else ""


# ------------------------------------------------------------------- region

LATAM_COUNTRIES = {
    "Argentina": ["argentina"],
    "Bolivia": ["bolivia"],
    "Brazil": ["brazil", "brasil"],
    "Chile": ["chile"],
    "Colombia": ["colombia"],
    "Costa Rica": ["costa rica"],
    "Cuba": ["cuba"],
    "Dominican Republic": ["dominican republic", "republica dominicana"],
    "Ecuador": ["ecuador"],
    "El Salvador": ["el salvador"],
    "Guatemala": ["guatemala"],
    "Honduras": ["honduras"],
    "Mexico": ["mexico"],
    "Nicaragua": ["nicaragua"],
    "Panama": ["panama"],
    "Paraguay": ["paraguay"],
    "Peru": ["peru"],
    "Uruguay": ["uruguay"],
    "Venezuela": ["venezuela"],
}
LATAM_GENERIC = re.compile(r"\b(latam|latin america|south america|central america|americas)\b")
WORLDWIDE = re.compile(
    r"\b(worldwide|world wide|anywhere|global|globally|any location|all countries|everywhere)\b"
)
NOT_WORLDWIDE = re.compile(
    r"\banywhere in (the )?(us|usa|u s|united states|uk|eu|europe|canada|germany|france|spain)\b"
)
OTHER_REGIONS = re.compile(
    r"\b(usa|us|u s|united states|canada|europe|european|eu|emea|apac|uk|united kingdom|england|"
    r"scotland|wales|india|asia|australia|new zealand|germany|france|spain|portugal|poland|"
    r"ireland|netherlands|italy|switzerland|sweden|denmark|norway|finland|belgium|austria|"
    r"czech republic|czechia|hungary|greece|estonia|latvia|lithuania|slovakia|slovenia|croatia|"
    r"philippines|pakistan|south africa|africa|nigeria|kenya|ghana|morocco|egypt|singapore|"
    r"indonesia|japan|china|korea|taiwan|thailand|vietnam|malaysia|hong kong|israel|turkey|"
    r"uae|united arab emirates|dubai|saudi arabia|ukraine|romania|bulgaria|serbia|cet|"
    r"north america|california|new york|texas|florida|massachusetts|illinois|colorado|"
    r"seattle|chicago|boston|austin|atlanta|denver|san francisco|los angeles|toronto|"
    r"vancouver|montreal|ottawa|edmonton|dublin|london|paris|berlin|amsterdam|munich|lisbon|"
    r"tokyo|sydney|bangalore|bengaluru|manila|nyc|sf|sfo|sea|chi|dc|bay area|silicon valley|"
    r"west coast|east coast|midwest|pacific time|eastern time|central time|mountain time)\b"
)
CODE_TO_COUNTRY = {
    "AR": "Argentina", "BO": "Bolivia", "BR": "Brazil", "CL": "Chile", "CO": "Colombia",
    "CR": "Costa Rica", "CU": "Cuba", "DO": "Dominican Republic", "EC": "Ecuador",
    "SV": "El Salvador", "GT": "Guatemala", "HN": "Honduras", "MX": "Mexico",
    "NI": "Nicaragua", "PA": "Panama", "PY": "Paraguay", "PE": "Peru", "UY": "Uruguay",
    "VE": "Venezuela",
}
LATAM_CODES = set(CODE_TO_COUNTRY)


def classify_region(text):
    """Devuelve (scope, paises_latam).
    scope: worldwide | latam | countries | other | unknown"""
    t = norm(text)
    if not t:
        return "unknown", []
    countries = [
        name
        for name, aliases in LATAM_COUNTRIES.items()
        if any(re.search(rf"\b{re.escape(a)}\b", t) for a in aliases)
    ]
    if LATAM_GENERIC.search(t):
        return "latam", countries
    if countries:
        return "countries", countries
    if WORLDWIDE.search(t) and not NOT_WORLDWIDE.search(t):
        return "worldwide", []
    if OTHER_REGIONS.search(t):
        return "other", []
    return "unknown", []


# -------------------------------------------------------------------- areas


def compile_phrases(phrases):
    out = []
    for p in phrases:
        n = norm(p)
        if n:
            out.append(re.compile(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])"))
    return out


def load_config():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for n in cfg["niches"]:
        n["_inc"] = compile_phrases(n["include"])
        n["_exc"] = compile_phrases(n.get("exclude", []))
    return cfg


def match_niches(cfg, title, extras):
    title_n = norm(title)
    text_n = norm(f"{title} {' '.join(extras)}")
    found = []
    for n in cfg["niches"]:
        if any(rx.search(title_n) for rx in n["_exc"]):
            continue
        if any(rx.search(text_n) for rx in n["_inc"]):
            found.append(n["id"])
    return found


# ------------------------------------------------------------------ fuentes
# Cada fuente devuelve una lista de dicts con estas claves:
# source, source_id, title, company, url, posted, expires, region_text,
# scope (opcional, si la fuente ya lo resolvio), type, salary, tags


def fetch_remoteok(cfg):
    data = http_json("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue  # el primer elemento es el aviso legal
        out.append(
            dict(
                source="RemoteOK",
                source_id=str(j.get("id") or j.get("slug")),
                title=j["position"],
                company=j.get("company", ""),
                url=j.get("url") or j.get("apply_url"),
                posted=parse_dt(j.get("date") or j.get("epoch")),
                expires=None,
                region_text=j.get("location", ""),
                type="",
                salary=fmt_salary(j.get("salary_min"), j.get("salary_max"), "USD", "year"),
                tags=as_list(j.get("tags")),
            )
        )
    return out


def fetch_remotive(cfg):
    # Remotive pide maximo 4 consultas al dia y publica las vacantes con 24 h de
    # retraso. Hacemos una sola.
    data = http_json("https://remotive.com/api/remote-jobs")
    out = []
    for j in data.get("jobs", []):
        out.append(
            dict(
                source="Remotive",
                source_id=str(j.get("id")),
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url"),
                posted=parse_dt(j.get("publication_date")),
                expires=None,
                region_text=j.get("candidate_required_location", ""),
                type=(j.get("job_type") or "").replace("_", " "),
                salary=j.get("salary") or "",
                tags=as_list(j.get("tags")) + as_list(j.get("category")),
            )
        )
    return out


class Partial(Exception):
    """La fuente respondio a medias (por ejemplo, limite de consultas)."""

    def __init__(self, rows, note):
        super().__init__(note)
        self.rows = rows
        self.note = note


def fetch_himalayas(cfg):
    """Himalayas permite filtrar por pais: con country=AR devuelve las vacantes
    abiertas a Argentina (sin restriccion + las que listan Argentina)."""
    out, seen = [], set()
    # Los 19 paises no caben en una corrida sin pasarse del limite de consultas: cada dia se
    # revisan unos cuantos y se rota. Las vacantes "worldwide" salen en todos. Con 19 paises y 4
    # por corrida, todos se revisan cada ~5 dias (menos que los 10 dias que se conserva lo visto).
    all_countries = cfg.get("himalayas_countries", ["AR"])
    per_run = min(int(cfg.get("himalayas_countries_per_run", len(all_countries))), len(all_countries))
    start = (NOW.toordinal() * per_run) % len(all_countries)
    countries = [all_countries[(start + i) % len(all_countries)] for i in range(per_run)]
    print("Himalayas, paises de hoy:", ", ".join(countries))
    for ci, country in enumerate(countries):
        pages = int(cfg.get("himalayas_pages_per_query", 2)) if ci == 0 else 1
        for q in cfg["himalayas_queries"]:
            for page in range(1, pages + 1):
                url = "https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode(
                    {"q": q, "country": country, "sort": "recent", "page": page, "limit": 20}
                )
                try:
                    data = http_json(url)
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        raise Partial(out, "limite de consultas alcanzado; resultados parciales")
                    raise
                jobs = data.get("jobs", [])
                for j in jobs:
                    guid = j.get("guid") or j.get("applicationLink")
                    if not guid or guid in seen:
                        continue
                    seen.add(guid)
                    restrictions = as_list(j.get("locationRestrictions"))
                    out.append(
                        dict(
                            source="Himalayas",
                            source_id=guid,
                            title=j.get("title", ""),
                            company=j.get("companyName", ""),
                            url=(j.get("applicationLink") or guid).split("?")[0],
                            posted=parse_dt(j.get("pubDate")),
                            expires=parse_dt(j.get("expiryDate")),
                            # lista vacia = sin restriccion (worldwide), segun la doc de Himalayas
                            region_text=", ".join(restrictions) if restrictions else "Worldwide",
                            type=j.get("employmentType") or "",
                            salary=fmt_salary(
                                j.get("minSalary"),
                                j.get("maxSalary"),
                                j.get("currency") or "USD",
                                {"annual": "year", "monthly": "month", "hourly": "hour",
                                 "weekly": "week", "fortnightly": "2 weeks"}.get(
                                    j.get("salaryPeriod") or "annual", "year"),
                            ),
                            tags=[],
                            strict=bool(restrictions),
                        )
                    )
                if len(jobs) < 20:
                    break
                time.sleep(1.5)
            time.sleep(1.5)
    return out


def fetch_wwr(cfg):
    raw = http_get("https://weworkremotely.com/remote-jobs.rss")
    root = ET.fromstring(raw)
    out = []
    for it in root.findall(".//item"):
        full_title = (it.findtext("title") or "").strip()
        company, _, title = full_title.partition(": ")
        if not title:
            company, title = "", full_title
        region = it.findtext("region") or ""
        country = it.findtext("country") or ""
        # Si WWR lista paises concretos, esos son los que cuentan.
        region_text = country if country.strip() else region
        out.append(
            dict(
                source="We Work Remotely",
                source_id=it.findtext("guid") or it.findtext("link"),
                title=title,
                company=company,
                url=it.findtext("link"),
                posted=parse_dt(it.findtext("pubDate")),
                expires=parse_dt(it.findtext("expires_at")),
                region_text=region_text,
                type=it.findtext("type") or "",
                salary="",
                tags=[],
                # "Anywhere in the World" sin paises = worldwide. Con paises, se evalua
                # la lista y lo que no mencione LATAM se descarta.
                scope_override=(
                    None if country.strip()
                    else ("worldwide" if WORLDWIDE.search(norm(region)) else None)
                ),
                strict=bool(country.strip()),
            )
        )
    return out


def fetch_jobicy(cfg):
    out, seen = [], set()
    for geo in ("latam", "anywhere"):
        cursor = None
        for _page in range(4):  # 100 por pagina; la ventana publica es de 7 dias
            url = f"https://jobicy.com/api/v2/remote-jobs?count=100&geo={geo}"
            if cursor:
                url += "&cursor=" + urllib.parse.quote(cursor)
            data = http_json(url)
            for j in data.get("jobs", []):
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                out.append(
                    dict(
                        source="Jobicy",
                        source_id=jid,
                        title=j.get("jobTitle", ""),
                        company=j.get("companyName", ""),
                        url=j.get("url"),
                        posted=parse_dt(j.get("pubDate")),
                        expires=None,
                        region_text=re.sub(r"\s+", " ", str(j.get("jobGeo") or "")),
                        type=", ".join(as_list(j.get("jobType"))),
                        salary="",
                        tags=as_list(j.get("jobIndustry")),
                    )
                )
            cursor = data.get("nextCursor")
            if not cursor or not data.get("hasMore", True):
                break
            time.sleep(1)
        time.sleep(1)
    return out


def fetch_workingnomads(cfg):
    data = http_json("https://www.workingnomads.com/api/exposed_jobs/")
    out = []
    for j in data:
        out.append(
            dict(
                source="Working Nomads",
                source_id=j.get("url"),
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url"),
                posted=parse_dt(j.get("pub_date")),
                expires=None,
                region_text=j.get("location", ""),
                type="",
                salary="",
                tags=as_list(j.get("tags")) + as_list(j.get("category_name")),
            )
        )
    return out


FETCHERS = [
    ("RemoteOK", fetch_remoteok),
    ("Remotive", fetch_remotive),
    ("Himalayas", fetch_himalayas),
    ("We Work Remotely", fetch_wwr),
    ("Jobicy", fetch_jobicy),
    ("Working Nomads", fetch_workingnomads),
]

# ------------------------------------------------- empresas (sitios de empleo)
# Lee directamente el tablero de vacantes de cada empresa (Greenhouse, Lever, Ashby,
# SmartRecruiters). Aqui la region se VERIFICA con tres pasos:
#   1. la vacante debe estar marcada como remota por la empresa,
#   2. la ubicacion no puede ser un pais o region fuera de LATAM (EE. UU., Canada, Europa...),
#   3. el texto de la descripcion no puede exigir residir en EE. UU. (ni en otro pais fuera de LATAM).
# Lo que no se puede confirmar queda como "region sin indicar" (oculto por defecto).

_US = r"(?:us|u s|usa|u s a|united states(?: of america)?)"
US_RESTRICTIONS = [re.compile(p) for p in [
    r"\bcontinental " + _US + r"\b",
    r"\blower 48\b",
    rf"\b{_US} (?:based|residents?|citizens?|only|work authorization)\b",
    rf"\bbased in the {_US}\b",
    rf"\b(?:located|reside|residing|resident|residents|live|living|based|working|work) (?:in|within) the {_US}\b",
    rf"\b(?:authorized|eligible|legally entitled|permitted|right) to work in the {_US}\b",
    rf"\bwithin the {_US}\b",
    rf"\bremote (?:in|within|from) the {_US}\b",
    rf"\b(?:open|available) (?:only )?to (?:candidates|applicants|residents) (?:in|within|located in) (?:the )?{_US}\b",
    rf"\bmust (?:be|have)[^.]{{0,60}}\b{_US} (?:work )?(?:authorization|citizen|resident)",
]]
MUST_LIVE_IN = re.compile(
    r"\bmust (?:be )?(?:located|based|residing|reside|live|living)(?: and work)? (?:in|within) (?:the )?([a-z0-9 ]{2,40})"
)
POSITIVE_WORLD = [re.compile(p) for p in [
    r"\b(?:work|working|hire|hiring|hired|located|based)\b[a-z0-9 ]{0,50}\b(?:anywhere in the world|from anywhere|worldwide|around the world|across the globe)\b",
    r"\b(?:anywhere in the world|worldwide)\b[a-z0-9 ]{0,40}\b(?:remote|work|hire|hiring)\b",
]]
POSITIVE_LATAM = re.compile(
    r"\b(?:remote|hire|hiring|located|based|work|working)\b[a-z0-9 ]{0,60}\b(?:latam|latin america|south america)\b"
)


def strip_html(text):
    t = htmllib.unescape(str(text or ""))  # Greenhouse entrega el HTML escapado
    t = re.sub(r"<(?:br|/p|/li|/h\d|/div)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(t))


def is_remote_text(text):
    return bool(re.search(r"remote|anywhere|worldwide|distributed", text or "", re.I))


def evaluate_employer_job(loc_texts, codes, description):
    """Devuelve ((scope, paises, verificacion), None) o (None, motivo_de_descarte)."""
    loc = "; ".join(t for t in loc_texts if t)
    scope, countries = classify_region(loc)
    if scope == "other":
        return None, f"Ubicación fuera de LATAM: {loc[:70]}"
    codes = [c.upper() for c in codes if c]
    if codes and scope not in ("worldwide", "latam") and not any(c in LATAM_CODES for c in codes):
        return None, f"País fuera de LATAM: {', '.join(codes)}"

    # Texto de la descripcion, frase por frase.
    live_in = None  # pais(es) LATAM que la descripcion exige, si los menciona
    for raw in re.split(r"[.!?\n]+", description or ""):
        n = norm(raw)
        if len(n) < 8:
            continue
        for rx in US_RESTRICTIONS:
            if rx.search(n):
                return None, "La descripción exige EE. UU.: «" + raw.strip()[:140] + "»"
        m = MUST_LIVE_IN.search(n)
        if m:
            where = " ".join(m.group(1).split()[:6])
            sc, _ = classify_region(where)
            if sc == "other":
                return None, "La descripción exige residir fuera de LATAM: «" + raw.strip()[:140] + "»"
            if sc in ("countries", "latam"):
                live_in = (sc, classify_region(where)[1])

    if scope in ("worldwide", "latam", "countries"):
        return (scope, countries, "location"), None
    code_countries = [CODE_TO_COUNTRY[c] for c in codes if c in CODE_TO_COUNTRY]
    if code_countries:  # la ficha trae un codigo de pais LATAM (por ejemplo AR)
        return ("countries", code_countries, "location"), None

    # La ubicacion no dice region: buscar evidencia positiva en la descripcion.
    if live_in:
        return (live_in[0], live_in[1], "description"), None
    for raw in re.split(r"[.!?\n]+", description or ""):
        n = norm(raw)
        if POSITIVE_LATAM.search(n):
            return ("latam", [], "description"), None
        if any(rx.search(n) for rx in POSITIVE_WORLD):
            return ("worldwide", [], "description"), None
    return ("unknown", [], "none"), None


def employer_board_url(c):
    base = {
        "greenhouse": "https://job-boards.greenhouse.io/",
        "lever": "https://jobs.lever.co/",
        "ashby": "https://jobs.ashbyhq.com/",
        "smartrecruiters": "https://jobs.smartrecruiters.com/",
    }[c["ats"]]
    return base + c["slug"]


def collect_candidates(c, cfg):
    """Devuelve (candidatas, vacantes_abiertas). Candidata = remota + titulo en tus areas."""
    ats, slug = c["ats"], c["slug"]
    cands, total = [], 0

    def want(title):
        return bool(match_niches(cfg, title, []))

    if ats == "greenhouse":
        jobs = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")["jobs"]
        total = len(jobs)
        for j in jobs:
            loc = (j.get("location") or {}).get("name", "")
            if not (is_remote_text(loc) and want(j.get("title", ""))):
                continue
            jid = j["id"]
            cands.append(dict(
                id=str(jid), title=j["title"], url=j.get("absolute_url"),
                posted=parse_dt(j.get("first_published") or j.get("updated_at")),
                loc=[loc], codes=[], type="",
                desc=lambda jid=jid: (strip_html(http_json(
                    f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}").get("content")), None),
            ))
    elif ats == "lever":
        jobs = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        total = len(jobs)
        for j in jobs:
            if (j.get("workplaceType") or "").lower() != "remote" or not want(j.get("text", "")):
                continue
            cats = j.get("categories") or {}
            lists = " ".join(strip_html(x.get("content")) for x in (j.get("lists") or []))
            text = " ".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""])
            cands.append(dict(
                id=j["id"], title=j["text"], url=j.get("hostedUrl"), posted=parse_dt(j.get("createdAt")),
                loc=[cats.get("location", "")] + list(cats.get("allLocations") or []),
                codes=[j.get("country")], type=cats.get("commitment", ""),
                desc=lambda text=text: (text, None),
            ))
    elif ats == "ashby":
        jobs = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"]
        total = len(jobs)
        for j in jobs:
            wt = j.get("workplaceType")
            remote = wt == "Remote" or (wt is None and j.get("isRemote"))
            if not (remote and want(j.get("title", ""))):
                continue
            locs = [j.get("location", "")]
            for sec in j.get("secondaryLocations") or []:
                locs.append(sec.get("location", "") if isinstance(sec, dict) else str(sec))
            locs.append((((j.get("address") or {}).get("postalAddress")) or {}).get("addressCountry", ""))
            cands.append(dict(
                id=j["id"], title=j["title"], url=j.get("jobUrl"), posted=parse_dt(j.get("publishedAt")),
                loc=locs, codes=[], type=j.get("employmentType") or "",
                desc=lambda t=j.get("descriptionPlain") or "": (t, None),
            ))
    elif ats == "smartrecruiters":
        data = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
        jobs = data.get("content", [])
        total = data.get("totalFound", len(jobs))
        for j in jobs:
            loc = j.get("location") or {}
            if not (loc.get("remote") and want(j.get("name", ""))):
                continue

            def detail(ref=j["ref"]):
                d = http_json(ref)
                secs = (d.get("jobAd") or {}).get("sections") or {}
                text = " ".join(strip_html((v or {}).get("text")) for v in secs.values())
                return text, d.get("postingUrl")

            cands.append(dict(
                id=str(j["id"]), title=j["name"], url=None, posted=parse_dt(j.get("releasedDate")),
                loc=[loc.get("fullLocation") or loc.get("city") or "", loc.get("country") or ""],
                codes=[loc.get("country")],
                type=((j.get("typeOfEmployment") or {}).get("label")) or "", desc=detail,
            ))
    else:
        raise ValueError(f"ATS no soportado: {ats}")
    return cands, total


def fetch_employer(c, cfg, excluded):
    cands, total = collect_candidates(c, cfg)
    rows = []
    for cand in cands:
        time.sleep(0.4)
        text, url2 = cand["desc"]()
        resolved, reason = evaluate_employer_job(cand["loc"], cand["codes"], text)
        url = url2 or cand["url"]
        if resolved is None:
            excluded.append({"company": c["name"], "title": cand["title"], "url": url,
                             "location": "; ".join(x for x in cand["loc"] if x)[:90], "reason": reason})
            continue
        rows.append(dict(
            source=c["name"], source_id=cand["id"], title=cand["title"], company=c["name"], url=url,
            posted=cand["posted"], expires=None,
            region_text="; ".join(x for x in cand["loc"] if x), type=cand["type"], salary="", tags=[],
            resolved=resolved, source_type="employer", src_key=f"{c['ats']}:{c['slug']}",
        ))
    return rows, total, len(cands)


def load_companies():
    if not COMPANIES_PATH.exists():
        return []
    return json.loads(COMPANIES_PATH.read_text(encoding="utf-8")).get("companies", [])


# ---------------------------------------------------------------- pipeline


def build_job(raw, cfg):
    url = safe_url(raw.get("url"))
    title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
    if not url or not title:
        return None
    # Las etiquetas de los feeds son ruidosas (un "Software Engineer" aparece como copywriting):
    # por defecto se busca solo en el titulo. Pon "use_tags": True en una fuente para cambiarlo.
    extras = raw.get("tags", []) if raw.get("use_tags", False) else []
    niches = match_niches(cfg, title, extras)
    if not niches:
        return None

    verification = "feed"
    scope, countries = classify_region(raw.get("region_text"))
    if raw.get("resolved"):
        scope, countries, verification = raw["resolved"]
    elif raw.get("scope_override"):
        scope, countries = raw["scope_override"], []
    elif raw.get("strict") and scope not in ("latam", "countries"):
        scope = "other"
    if scope == "other":
        return None

    posted = raw.get("posted")
    if posted and posted < NOW - timedelta(days=cfg.get("max_age_days", 45)):
        return None
    expires = raw.get("expires")
    if expires and expires < NOW:
        return None

    job_id = hashlib.sha1(f"{raw['source']}|{raw['source_id']}".encode()).hexdigest()[:12]
    return {
        "id": job_id,
        "title": title,
        "company": re.sub(r"\s+", " ", str(raw.get("company") or "")).strip(),
        "url": url,
        "source": raw["source"],
        "source_type": raw.get("source_type", "board"),
        "src_key": raw.get("src_key"),
        "verification": verification,
        "sources": [{"name": raw["source"], "url": url, "type": raw.get("source_type", "board")}],
        "posted": iso(posted) or iso(NOW),
        "first_seen": iso(NOW),
        "last_seen": iso(NOW),
        "expires": iso(expires),
        "niches": niches,
        "scope": scope,
        "countries": countries,
        "location": re.sub(r"\s+", " ", str(raw.get("region_text") or "")).strip()[:90],
        "type": (raw.get("type") or "")[:40],
        "salary": raw.get("salary") or "",
        "tags": [t for t in raw.get("tags", []) if len(t) < 30][:6],
    }


def load_previous():
    if not OUT_PATH.exists():
        return {}
    try:
        data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        return {j["id"]: j for j in data.get("jobs", [])}
    except Exception:
        return {}


def merge_duplicates(jobs):
    """Une la misma vacante publicada en varias fuentes (misma empresa + titulo)."""
    by_key, result = {}, []
    for j in sorted(jobs, key=lambda x: (x.get("source_type") != "employer", x["first_seen"])):
        key = norm(j["company"]) + "|" + norm(j["title"])
        if not norm(j["company"]) or key not in by_key:
            by_key[key] = j
            result.append(j)
            continue
        base = by_key[key]
        known = {s["name"] for s in base["sources"]}
        for s in j["sources"]:
            if s["name"] not in known:
                base["sources"].append(s)
                known.add(s["name"])
        base["last_seen"] = max(base["last_seen"], j["last_seen"])
    return result


def main():
    if "--check" in sys.argv:
        data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        bad = [s for s in data["meta"]["sources"] if not s["ok"]]
        for s in bad:
            print(f"::error::{s['name']} fallo: {s.get('error')}")
        for e in data["meta"].get("employers", []):
            if not e["ok"]:
                print(f"::warning::Empresa {e['name']} fallo: {e.get('error')} (revisa ats/slug en config/companies.json)")
        sys.exit(1 if bad else 0)

    cfg = load_config()
    previous = load_previous()
    fresh, statuses = {}, []

    for name, fn in FETCHERS:
        status = {"name": name, "home": SOURCE_HOMES[name], "ok": True, "fetched": 0, "kept": 0}
        rows = []
        try:
            rows = fn(cfg)
        except Partial as p:
            rows = p.rows
            status["note"] = p.note
        except Exception as e:
            status["ok"] = False
            status["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"::warning::{name} fallo: {status['error']}")
        status["fetched"] = len(rows)
        for raw in rows:
            job = build_job(raw, cfg)
            if job:
                fresh[job["id"]] = job
                status["kept"] += 1
        print(f"{name}: {status['fetched']} vacantes leidas, {status['kept']} en tus areas y region")
        statuses.append(status)

    # Empresas con sitio de empleo propio (region verificada).
    employer_statuses, excluded, ok_employers = [], [], set()
    for c in load_companies():
        st = {"name": c["name"], "ats": c["ats"], "home": employer_board_url(c), "ok": True,
              "open": 0, "candidates": 0, "kept": 0}
        try:
            rows, total, n_cands = fetch_employer(c, cfg, excluded)
            st["open"], st["candidates"] = total, n_cands
            ok_employers.add(f"{c['ats']}:{c['slug']}")
            for raw in rows:
                job = build_job(raw, cfg)
                if job:
                    fresh[job["id"]] = job
                    st["kept"] += 1
        except Exception as e:
            st["ok"] = False
            st["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"::warning::Empresa {c['name']} fallo: {st['error']}")
        print(f"{c['name']}: {st['open']} abiertas, {st['candidates']} remotas en tus areas, {st['kept']} verificadas")
        employer_statuses.append(st)
        time.sleep(1)

    if not any(s["ok"] for s in statuses) and not any(e["ok"] for e in employer_statuses):
        print("::error::Ninguna fuente respondio; no se toca data/jobs.json")
        sys.exit(1)

    # Conservar lo visto antes, salvo lo vencido o que lleva dias sin aparecer.
    stale_cut = NOW - timedelta(days=cfg.get("stale_after_days", 10))
    age_cut = NOW - timedelta(days=cfg.get("max_age_days", 45))
    combined = {}
    for jid, old in previous.items():
        last_seen = parse_dt(old.get("last_seen")) or NOW
        posted = parse_dt(old.get("posted")) or NOW
        expires = parse_dt(old.get("expires"))
        if last_seen < stale_cut or posted < age_cut or (expires and expires < NOW):
            continue
        # El tablero de una empresa lista todas sus vacantes abiertas: si respondio hoy y
        # la vacante ya no esta, esta cerrada.
        if old.get("src_key") in ok_employers and jid not in fresh:
            continue
        combined[jid] = old
    for jid, job in fresh.items():
        if jid in combined:
            job["first_seen"] = combined[jid]["first_seen"]
        combined[jid] = job

    jobs = merge_duplicates(list(combined.values()))
    jobs.sort(key=lambda j: j["posted"], reverse=True)

    # Recalcular cuantas vacantes vigentes tiene cada fuente.
    for s in statuses:
        s["kept"] = sum(1 for j in jobs if any(x["name"] == s["name"] for x in j["sources"]))
    for e in employer_statuses:
        e["kept"] = sum(1 for j in jobs if any(x["name"] == e["name"] for x in j["sources"]))

    out = {
        "meta": {
            "generated_at": iso(NOW),
            "total": len(jobs),
            "niches": [{"id": n["id"], "label": n["label"]} for n in cfg["niches"]],
            "countries": list(LATAM_COUNTRIES.keys()),
            "sources": statuses,
            "employers": employer_statuses,
        },
        "jobs": jobs,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    EXCLUDED_PATH.write_text(json.dumps(
        {"generated_at": iso(NOW), "nota": "Vacantes remotas en tus areas que NO se publicaron y por que.",
         "excluded": excluded}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo: {len(jobs)} vacantes en data/jobs.json")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Fuentes\n\n| Fuente | Estado | Leidas | Vigentes |\n|---|---|---|---|\n")
            for s in statuses:
                estado = "ok" if s["ok"] else f"fallo: {s.get('error')}"
                if s.get("note"):
                    estado += f" ({s['note']})"
                f.write(f"| {s['name']} | {estado} | {s['fetched']} | {s['kept']} |\n")
            f.write("\n### Empresas\n\n| Empresa | Estado | Abiertas | Remotas en tus areas | Verificadas |\n|---|---|---|---|---|\n")
            for e in employer_statuses:
                estado = "ok" if e["ok"] else f"fallo: {e.get('error')}"
                f.write(f"| {e['name']} | {estado} | {e['open']} | {e['candidates']} | {e['kept']} |\n")


if __name__ == "__main__":
    main()
