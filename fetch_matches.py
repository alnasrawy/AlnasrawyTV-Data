import os
import sys
import io
import json
import random
import time
import re
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from curl_cffi import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

BROWSERS = ["chrome120"]
TZ = timezone(timedelta(hours=3))

LEAGUES_MAPPING = {
    "دوري أبطال أوروبا": ["أبطال أوروبا", "دوري الابطال", "دوري الأبطال"],
    "الدوري الأوروبي": ["الدوري الأوروبي", "اليوروباليج", "يوروباليغ"],
    "دوري المؤتمر الأوروبي": ["المؤتمر الأوروبي", "دوري المؤتمر"],
    "دوري أبطال أفريقيا": ["أبطال أفريقيا", "أبطال إفريقيا", "دوري ابطال افريقيا"],
    "دوري أبطال آسيا": ["أبطال آسيا", "دوري ابطال اسيا", "النخبة", "دوري أبطال آسيا للنخبة"],
    "كأس العالم": ["كأس العالم", "المونديال", "كأس العالم للأندية"],
    "كأس أمم أوروبا": ["يورو", "أمم أوروبا", "كأس أمم أوروبا"],
    "كوبا أمريكا": ["كوبا أمريكا", "كوبا امريكا"],
    "كأس أمم أفريقيا": ["أمم أفريقيا", "أمم إفريقيا", "الأمم الإفريقية"],
    "كأس آسيا": ["كأس آسيا", "أمم آسيا", "الأمم الآسيوية"],
    "الدوري الإنجليزي": ["إنجليزي", "الإنجليزي", "بريميرليج", "البريميرليج", "انجلترا"],
    "الدوري الإسباني": ["إسباني", "الإسباني", "ليجا", "الليجا", "اسبانيا"],
    "الدوري الإيطالي": ["إيطالي", "الإيطالي", "كالتشيو", "الكالتشيو", "ايطاليا"],
    "الدوري الألماني": ["ألماني", "الألماني", "بوندسليجا", "البوندسليجا", "المانيا"],
    "الدوري الفرنسي": ["فرنسي", "الفرنسي", "فرنسا"],
    "الدوري السعودي": ["روشن", "سعودي", "السعودي", "للمحترفين"],
    "الدوري العراقي": ["عراقي", "العراقي", "نجوم العراق"],
    "الدوري المصري": ["مصري", "المصري", "النيل"],
    "الدوري المغربي": ["مغربي", "المغربي", "الاحترافية"],
    "الدوري الإماراتي": ["إماراتي", "الإماراتي", "أدنوك"],
    "الدوري القطري": ["قطري", "القطري", "نجوم قطر", "إكسبو"],
}

def _load_config(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_CFG = _load_config()
_cfg_vip = _CFG.get("vip", {}) or {}
if _cfg_vip.get("leagues"):
    LEAGUES_MAPPING = _cfg_vip["leagues"]

TELEGRAM = _CFG.get("telegram", {}) or {}
GLOBAL_DELAY = _CFG.get("global_delay", [1.0, 2.0]) or [1.0, 2.0]

STATE_FILE = os.path.join(BASE_DIR, "state.json")
MATCHES_FILE = os.path.join(BASE_DIR, "matches.json")

def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"started_notified": {}, "ended_notified": {}, "prev_status": {}}

def _save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

_TG_WARNED = {"once": False}

def send_telegram(text):
    if not TELEGRAM.get("enabled"):
        return False
    token = os.environ.get("TG_BOT_TOKEN")
    chat = (TELEGRAM.get("channel") or "").strip()
    if not token or not chat:
        if not _TG_WARNED["once"]:
            print("    ⚠️ Telegram: TG_BOT_TOKEN or channel not configured — skipping.")
            _TG_WARNED["once"] = True
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"    ❌ Telegram send failed: {e}")
        return False

def send_telegram_photo(png_bytes, caption=""):
    if not TELEGRAM.get("enabled"):
        return False
    token = os.environ.get("TG_BOT_TOKEN")
    chat = (TELEGRAM.get("channel") or "").strip()
    if not token or not chat:
        if not _TG_WARNED["once"]:
            print("    ⚠️ Telegram: TG_BOT_TOKEN or channel not configured — skipping.")
            _TG_WARNED["once"] = True
        return False
    try:
        from curl_cffi import CurlMime
        mime = CurlMime.from_list([{
            "name": "photo", "filename": "match_card.png",
            "data": png_bytes, "content_type": "image/png",
        }])
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat, "caption": caption},
            multipart=mime,
            timeout=60,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"    ❌ Telegram sendPhoto failed: {e}")
        return False


_FONT_CACHE = {}
_LOGO_CACHE = {}
LOGOS_CACHE_DIR = os.path.join(BASE_DIR, "logos_cache")

_TEAM_LOGO_FOOTYLOGOS = {
    "مانشسترسيتي": "manchester-city",
    "ارسنال": "arsenal",
    "ليفربول": "liverpool-fc",
    "تشيلسي": "chelsea-fc",
    "مانشستريونايتد": "manchester-united",
    "توتنهامهوتسبر": "tottenham-hotspur",
    "نيوكاسل": "newcastle-united",
    "نيوكاسليونايتد": "newcastle-united",
    "استونفيلا": "aston-villa",
    "وستهاميونايتد": "west-ham-united",
    "برايتون": "brighton-and-hove-albion",
    "برينتفورد": "brentford-fc",
    "فولهام": "fulham-fc",
    "كريستالبالاس": "crystal-palace",
    "ويلفرهامبتون": "wolverhampton-wanderers",
    "بورنموث": "afc-bournemouth",
    "نوتنهام": "nottingham-forest",
    "نوتنجهامفورست": "nottingham-forest",
    "ليسترسيتي": "leicester-city",
    "ليدزيونايتد": "leeds-united",
    "بيرنلي": "burnley-fc",
    "شيفيلديونايتد": "sheffield-united",
    "هالسيتي": "hull-city",
    "كوفنتريسيتي": "coventry-city",
    "وستبروميتش": "west-bromwich-albion",
    "وستبروميتشالبيون": "west-bromwich-albion",
    "برمنجهامسيتي": "birmingham-city",
    "ميدلسبره": "middlesbrough-fc",
    "ستوكسيتي": "stoke-city",
    "نورويتشسيتي": "norwich-city",
    "ساوثامبتون": "southampton",
    "بورتسموث": "portsmouth-fc",
    "كوينزباركرينجرز": "queens-park-rangers",
    "ميلوول": "millwall-fc",
    "ديربيكاونتي": "derby-county",
    "تشارلتوناثليتيك": "charlton-athletic",
    "تشارلتوناتليتك": "charlton-athletic",
    "شيفيلدوينزداي": "sheffield-wednesday",
    "لينكولنسيتي": "lincoln-city",
    "بريستون": "preston-north-end",
    "بولتونواندررز": "bolton-wanderers",
    "ويجان": "wigan-athletic",
    "ويمبلدون": "afc-wimbledon",
    "ريالمدريد": "real-madrid",
    "برشلونه": "fc-barcelona",
    "اتلتيكومدريد": "atletico-madrid",
    "اتليتكبلباو": "athletic-club-bilbao",
    "ريالسوسيداد": "real-sociedad",
    "ريالبيتيس": "real-betis-balompie",
    "فياريال": "villarreal-cf",
    "اشبيليه": "sevilla-fc",
    "جيرونا": "girona-fc",
    "فالنسيا": "valencia-cf",
    "خيتافي": "getafe-cf",
    "سيلتافيجو": "celta-de-vigo",
    "رايوفاييكانو": "rayo-vallecano",
    "اوساسونا": "ca-osasuna",
    "اسبانيول": "rcd-espanyol",
    "لاسبالماس": "ud-las-palmas",
    "جدة": "casino-barcelona",
    "بايرنميونيخ": "bayern-munchen",
    "بروسيادورتموند": "borussia-dortmund",
    "لايبزيج": "rb-leipzig",
    "بايرليفركوزن": "bayer-04-leverkusen",
    "اينتراختفرانكفورt": "eintracht-frankfurt",
    "فولفسبورج": "vfl-wolfsburg",
    "شتوتجارت": "vfb-stuttgart",
    "فرايبورج": "sc-freiburg",
    "(monchengladbach": "borussia-monchengladbach",
    "بوروسيامونشنجلادباخ": "borussia-monchengladbach",
    "كولن": "1-fc-koln",
    "ماينز05": "1-fsv-mainz-05",
    "اوجسبورج": "fc-augsburg",
    "يردربريمن": "sv-werder-bremen",
    "هوفنهايم": "tsg-1899-hoffenheim",
    "بوخوم": "vfl-bochum",
    "هيرتابرلين": "hertha-berlin",
    "روتارفورت": "sv-sandhausen",
    "داندALKsh": "1-fc-heidenheim",
    "هايدينهايم": "1-fc-heidenheim",
    "هايدنهايم": "1-fc-heidenheim",
    "باريسسانجيرمان": "paris-saint-germain",
    "موناكو": "as-monaco",
    "ليون": "olympique-lyonnais",
    "اولمبيكليون": "olympique-lyonnais",
    "مارسيليا": "olympique-de-marseille",
    "اولمبيكمارسيليا": "olympique-de-marseille",
    "ليل": "losc-lille",
    "نيس": "ogc-nice",
    "لانس": "rc-lens",
    "رين": "stade-rennais",
    "ستراسبورج": "rc-strasbourg",
    "مونبلييه": "montpellier-hsc",
    "نانت": "fc-nantes",
    "تولوز": "toulouse-fc",
    "بريست": "stade-brestois-29",
    "لومان": "le-mans",
    "اميان": "amiens-sc",
    "تروا": "troyes-ac",
    "ديجون": "dijon-fco",
    "سانجวน": "saint-etienne",
    "سانتايتيان": "as-saint-etienne",
    "كليرمون": "clermont-foot-63",
    "لوريان": "fc-lorient",
    "باستيا": "sc-bastia",
    "اوكسير": "aj-auxerre",
    "ルアン": "stade-de-reims",
    "رافال": "rc-lens",
    "ميلان": "ac-milan",
    "انترميلان": "fc-internazionale-milano",
    "يوفنتوس": "juventus",
    "روما": "as-roma",
    "لاتسيو": "ss-lazio",
    "نابولي": "ssc-napoli",
    "اتالانتا": "atalanta-bc",
    "فيورنتينا": "acf-fiorentina",
    "تورينو": "torino-fc",
    "بولونيا": "bologna-fc-1909",
    "امبoli": "empoli-fc",
    "سامبدوريا": "uc-sampdoria",
    "كالياري": "cagliari-calcio",
    "فيرونا": "hellas-verona-fc",
    "كييفوفيرونا": "hellas-verona-fc",
    "اودينيزي": "udinese-calcio",
    "ساسولو": "us-sassuolo-calcio",
    "лачио": "ss-lazio",
    "ليتشي": "us-lecce",
    "فروزينوني": "frosinone-calcio",
    "جنوه": "genoa-cfc",
    "كومو": "como-1907",
    "كالياري": "cagliari-calcio",
    "بارما": "parma-calcio-1913",
    "كريمونزي": "us-cremonese",
    "بادوفا": "calcio-padena",
    "بريشيا": "bsc-brescia",
    "سيينا": "acn-siena-1904",
    "リジェナ": "us-reggiana-1919",
    "ريجينا": "us-reggiana-1919",
    "モデナ": "modena-fc",
    "مودينا": "modena-fc",
    "بيروجيا": "ac-perugia",
    "بيسكارا": "delfino-pescara-1936",
    "إمبولي": "empoli-fc",
    "الهلال": "al-hilal-sfc",
    "النصر": "al-nassr-fc",
    "الاتحاد": "al-ittihad-fc",
    "الشباب": "al-shabab-fc",
    "الأهلي": "al-ahli-sa",
    "الفيحاء": "al-fayha-fc",
    "التعاون": "al-taawoun-fc",
    "ضمك": "damac-fc",
    "الطائي": "al-tai-fc",
    "الرائد": "al-raed-sa",
    "الرياض": "al-riyadh-sc",
    "القادسيه": "al-qadisiyah-fc",
    "ابها": "abha-fc",
    "الخليج": "al-khaleej-sa",
    "الнатس": "al-hazm-fc",
    "ال hj": "al-akhdoud-sc",
    "نيوم": "neom-fc",
    "ال Auckland": "al-ettifaq-fc",
    "الزمالك": "zamalek-sc",
    "الزوراء": "al-zawraa-sc",
    "القوة الجوية": "al-quwa-al-jawiya",
    "الشرطة": "al-shorta-sc",
    "الطلبة": "al-talaba-sc",
    "الكرخ": "al-karkh-sc",
    "الجولان": "al-gholan-sc",
    "نادي南阳": "al-naft-sc",
    "النفط": "al-naft-sc",
    "الموصل": "al-quwa-al-jawiya",
    "الميناء": "al-mina-sc",
    "زاخو": "zakho-sc",
    "ديالى": "diya-la-sc",
    "اربيل": "erbil-sc",
    "نفط ميسان": "najaf-fc",
    "الفرات": "al-foreat-sc",
    "الكربلاء": "al-karraba-sc",
    "الكرمة": "al-karma-sc",
    "المجزل": "al-majd-sc",
    "ال bab": "al-sinaa-sc",
    "الن finally": "al-talaba-sc",
}

_SHAPE_WARNED = {"once": False}
_RAQM = {"done": False, "value": False}

def _uses_raqm():
    if not _RAQM["done"]:
        try:
            from PIL import features
            _RAQM["value"] = bool(features.check("raqm"))
        except Exception:
            _RAQM["value"] = False
        _RAQM["done"] = True
    return _RAQM["value"]

def _contains_rtl(text):
    return any(
        ('\u0600' <= c <= '\u06FF') or ('\u0750' <= c <= '\u077F') or
        ('\uFB50' <= c <= '\uFDFF') or ('\uFE70' <= c <= '\uFEFF')
        for c in str(text)
    )

def _text_direction(text):
    if not _uses_raqm():
        return None
    return "rtl" if _contains_rtl(str(text)) else None

_ARABIC_FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Regular.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Bold.ttf",
]

_FONT_PREFERRED_PATHS = {
    "regular": [
        "/tmp/alnasrawy_fonts/tajawal_regular.ttf",
        r"C:\Users\Ahmed\Documents\Default Project\tajawal_regular.ttf",
    ],
    "bold": [
        "/tmp/alnasrawy_fonts/tajawal_bold.ttf",
        r"C:\Users\Ahmed\Documents\Default Project\tajawal_bold.ttf",
    ],
}

_SYSTEM_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

def _font_path(kind):
    for p in _FONT_PREFERRED_PATHS.get(kind, []):
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            return p
    p = os.path.join(tempfile.gettempdir(), f"card_font_{kind}.ttf")
    if os.path.exists(p) and os.path.getsize(p) > 5000:
        return p
    url = _ARABIC_FONT_URLS[0 if kind == "regular" else 1]
    try:
        r = requests.get(url, timeout=25, impersonate="chrome120")
        if r.status_code == 200 and len(r.content) > 5000:
            with open(p, "wb") as f:
                f.write(r.content)
            return p
    except Exception:
        pass
    for cand in _SYSTEM_FONT_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None

def _font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    path = _font_path("bold" if bold else "regular")
    font = None
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        print("    ⚠️ No Arabic font found — card generation may fail.")
    _FONT_CACHE[key] = font
    return font

def _shape(text):
    if _uses_raqm():
        return str(text)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        if not _SHAPE_WARNED["once"]:
            print("    ⚠️ arabic_reshaper / python-bidi not installed!")
            _SHAPE_WARNED["once"] = True
        return str(text)

def _draw_centered(draw, cx, y, text, font, fill, max_w):
    if font is None:
        return
    s = _shape(text)
    direction = _text_direction(s)
    w = draw.textlength(s, font=font, direction=direction)
    if w <= max_w:
        draw.text((cx - w / 2, y), s, font=font, fill=fill, direction=direction)
        return
    words = s.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font, direction=direction) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=font, direction=direction)
        draw.text((cx - lw / 2, y + i * (font.size + 6)), ln, font=font, fill=fill, direction=direction)

def _draw_right(draw, xr, y, text, font, fill, max_w):
    if font is None:
        return
    s = _shape(text)
    direction = _text_direction(s)
    w = draw.textlength(s, font=font, direction=direction)
    if w <= max_w:
        draw.text((xr - w, y), s, font=font, fill=fill, direction=direction)
        return
    words = s.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font, direction=direction) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=font, direction=direction)
        draw.text((xr - lw, y + i * (font.size + 6)), ln, font=font, fill=fill, direction=direction)

def _draw_tv_icon(d, cx, cy, color, scale=1.0):
    w, h = 46 * scale, 34 * scale
    x, y = cx - w / 2, cy - h / 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=6, outline=color, width=3)
    d.line([x + w / 2, y - 12, x + w / 2, y], fill=color, width=3)
    d.line([x - 10, y - 16, x + w + 10, y - 16], fill=color, width=3)
    d.line([x + w / 2 - 12, y + h + 8, x + w / 2 + 12, y + h + 8], fill=color, width=3)
    d.line([x + w / 2, y + h, x + w / 2, y + h + 8], fill=color, width=3)
    d.rounded_rectangle([x + 6, y + 6, x + w - 6, y + h - 6], radius=3, outline=(70, 90, 150), width=2)


_TEAM_PALETTE = [
    (26, 35, 126), (13, 71, 161), (0, 101, 151), (2, 119, 189), (56, 142, 60), (124, 179, 66),
    (173, 20, 87), (194, 24, 91), (136, 14, 79), (245, 124, 0), (230, 81, 0), (191, 54, 12),
    (69, 39, 160), (81, 45, 168), (3, 155, 229), (18, 137, 167), (27, 94, 32), (255, 109, 0),
]

def _team_color(name):
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return _TEAM_PALETTE[h % len(_TEAM_PALETTE)]

_CHANNEL_APP_KEYWORDS = ['تطبيق', 'thmanyah app']

def _is_app_channel(name):
    n = str(name).lower().strip()
    return any(k in n for k in _CHANNEL_APP_KEYWORDS)

def _norm_key(s):
    s = re.sub(r'[\s\-_ـ]+', '', s or '')
    return s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي').lower()


def _load_team_logo(url, team_name, league=None, size=210):
    """Load logo: local footylogos cache -> YSscores URL -> colored letter circle."""
    key = (url, team_name, league, size)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    tkey = _norm_key(team_name)
    img = None

    footy_slug = _TEAM_LOGO_FOOTYLOGOS.get(tkey)
    if footy_slug:
        local_path = os.path.join(LOGOS_CACHE_DIR, footy_slug + ".png")
        if os.path.isfile(local_path) and os.path.getsize(local_path) > 500:
            try:
                img = Image.open(local_path).convert("RGBA")
                try:
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)
                except Exception:
                    pass
                img.thumbnail((size, size), Image.LANCZOS)
                w, h = img.size
                small = min(w, h)
                target_small = size * 0.92
                if small and small < target_small:
                    f = target_small / small
                    img = img.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
            except Exception:
                img = None

    if img is None and url:
        try:
            ref = "https://www.ysscores.com/"
            if "filgoal" in url:
                ref = "https://www.filgoal.com/"
            r = requests.get(url, timeout=15, impersonate="chrome120", headers={"Referer": ref})
            if r.status_code == 200 and len(r.content) > 100:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                try:
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)
                except Exception:
                    pass
                img.thumbnail((size, size), Image.LANCZOS)
        except Exception:
            img = None

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    d = ImageDraw.Draw(canvas)
    if img is not None:
        canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
    else:
        color = _team_color(team_name)
        d.ellipse([0, 0, size, size], fill=color + (255,))
        f = _font(int(size * 0.42), bold=True)
        letter = _shape((team_name.strip()[:1]) or "?")
        if f is not None:
            lw = d.textlength(letter, font=f)
            d.text(((size - lw) / 2, (size - f.size) / 2), letter, font=f, fill=(255, 255, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    canvas.putalpha(mask)
    _LOGO_CACHE[key] = canvas
    return canvas


def _wrap_lines(draw, text, font, max_w):
    direction = _text_direction(text)
    words = str(text).split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font, direction=direction) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines

def _draw_status_pill(d, cx, cy, text, fill, bg, outline):
    s = _shape(text)
    direction = _text_direction(s)
    font = _font(26, bold=True)
    tw = d.textlength(s, font=font, direction=direction)
    pad_x, pad_y = 24, 10
    pw, ph = tw + pad_x * 2, font.size + pad_y * 2
    x0, y0 = cx - pw / 2, cy - ph / 2
    if bg is not None:
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph / 2, fill=bg)
    elif outline:
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph / 2, outline=fill, width=2)
    dot_r = 5
    d.ellipse([cx - pw / 2 + 16 - dot_r, cy - dot_r, cx - pw / 2 + 16 + dot_r, cy + dot_r], fill=fill)
    d.text((cx - tw / 2 + 6, y0 + pad_y - 2), s, font=font, fill=fill, direction=direction)

def _draw_star(d, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=fill)

def _draw_ball(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(248, 250, 252, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(70, 78, 92, 255), width=2)
    d.arc([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], 200, 340, fill=(70, 78, 92, 255), width=2)
    d.arc([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], 20, 160, fill=(70, 78, 92, 255), width=2)


def compose_match_card(match, kind="end"):
    if Image is None or ImageDraw is None:
        return None
    if _font(30, bold=True) is None:
        return None
    league = match.get('league', '') or ''
    home = match.get('homeTeam', '') or ''
    away = match.get('awayTeam', '') or ''
    score_or_time = match.get('scoreOrTime', '') or '-:-'
    status = match.get('status', '') or ''
    channels = [c for c in (match.get('channels') or []) if c]
    scorers = match.get('scorers') or {"home": [], "away": []}
    hs = scorers.get('home') or []
    aw = scorers.get('away') or []

    is_score = '-' in score_or_time
    W = 1080
    s = 2.25

    MARGIN = 30
    PAD = 54
    RAD = 40
    WRAP = int(80 * s) + 26
    LOGO = int(80 * s)
    inner_x0 = MARGIN + PAD
    inner_x1 = W - MARGIN - PAD
    cx_home = inner_x1 - WRAP // 2
    cx_away = inner_x0 + WRAP // 2
    badge_y = MARGIN + 40
    badge_h = 74
    cy_logo = badge_y + badge_h + 50 + WRAP // 2
    name_y = cy_logo + WRAP // 2 + 27
    accent_y = name_y + 41
    accent_bottom = accent_y + 7
    st_cy = accent_bottom + 76
    div_y = st_cy + 36 + 45 + 4
    title_y = div_y + 9 + 40
    grid_top = title_y + 44 + 31

    rows_n = max(len(hs), len(aw), 0)
    if kind == "start":
        H = 810
    else:
        H = int(grid_top + rows_n * 62 + 30 + MARGIN + 30)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    top_c = (5, 7, 13)
    mid_c = (12, 18, 32)
    for y in range(H):
        t = y / max(1, int(H * 0.6))
        if t < 1:
            c = tuple(int(top_c[i] + (mid_c[i] - top_c[i]) * t) for i in range(3))
        else:
            t2 = (y - H * 0.6) / max(1, int(H * 0.4))
            c = tuple(int(mid_c[i] + (top_c[i] - mid_c[i]) * t2) for i in range(3))
        d.line([(0, y), (W, y)], fill=c + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([int(W * 0.10), -160, int(W * 0.55), 320], fill=(232, 184, 75, 26))
    gd.ellipse([int(W * 0.55), -120, W + 80, 360], fill=(59, 90, 180, 40))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img, "RGBA")

    d.rounded_rectangle([MARGIN, MARGIN, W - MARGIN, H - MARGIN], radius=RAD,
                        fill=(18, 26, 46, 140), outline=(255, 255, 255, 20), width=2)

    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g2 = ImageDraw.Draw(glow2)
    g2.ellipse([W / 2 - 430, 40, W / 2 + 430, 40 + 620], fill=(232, 184, 75, 22))
    img = Image.alpha_composite(img, glow2)
    d = ImageDraw.Draw(img, "RGBA")

    GOLD = (232, 184, 75, 255)
    GOLD_SOFT = (246, 223, 160, 255)
    TEXT_HI = (245, 247, 251, 255)
    TEXT_MID = (170, 178, 197, 255)
    TEXT_LOW = (106, 116, 136, 255)
    LINE = (255, 255, 255, 20)

    badge_font = _font(30, bold=True)
    if league:
        ls = _shape(league)
        ld = _text_direction(ls)
        lw = d.textlength(ls, font=badge_font, direction=ld)
        star_r = 17
        bw = lw + star_r * 2 + 20 + 90
        bx = W / 2 - bw / 2
        by = badge_y
        bh = badge_h
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh / 2,
                            fill=(232, 184, 75, 30), outline=(232, 184, 75, 90), width=2)
        star_cx = bx + 45 + star_r
        text_x = star_cx + star_r + 20
        _draw_star(d, star_cx, by + bh / 2, star_r, GOLD)
        d.text((text_x, by + (bh - badge_font.size) / 2), ls, font=badge_font,
               fill=GOLD_SOFT, direction=ld)

    home_logo = _load_team_logo(match.get('homeLogo'), home, league=league, size=LOGO)
    away_logo = _load_team_logo(match.get('awayLogo'), away, league=league, size=LOGO)
    for cx, lg in ((cx_home, home_logo), (cx_away, away_logo)):
        d.ellipse([cx - WRAP / 2, cy_logo - WRAP / 2, cx + WRAP / 2, cy_logo + WRAP / 2],
                  fill=(255, 255, 255, 255), outline=(255, 255, 255, 20), width=2)
        img.alpha_composite(lg, (int(cx - LOGO / 2), int(cy_logo - LOGO / 2)))
    d = ImageDraw.Draw(img, "RGBA")

    name_font = _font(36, bold=True)
    name_y = cy_logo + WRAP / 2 + 27
    _draw_centered(d, cx_home, name_y, home, name_font, TEXT_HI, 380)
    _draw_centered(d, cx_away, name_y, away, name_font, TEXT_HI, 380)
    hc = _team_color(home)
    ac = _team_color(away)
    accent_y = name_y + 50 - 9
    d.rounded_rectangle([cx_home - 50, accent_y, cx_home + 50, accent_y + 7], radius=4, fill=hc + (255,))
    d.rounded_rectangle([cx_away - 50, accent_y, cx_away + 50, accent_y + 7], radius=4, fill=ac + (255,))

    panel_w, panel_h = int(118 * s) + 70, 150
    px, py = W / 2 - panel_w / 2, cy_logo - panel_h / 2
    d.rounded_rectangle([px, py, px + panel_w, py + panel_h], radius=20,
                        fill=(255, 255, 255, 14), outline=(232, 184, 75, 100), width=2)

    if kind == "end" and is_score:
        parts = [p.strip() for p in score_or_time.split('-')]
        score_style = _font(76, bold=True)
        if len(parts) == 2:
            w1 = d.textlength(parts[0], font=score_style)
            w2 = d.textlength(parts[1], font=score_style)
            dash = _font(45, bold=True)
            wdash = d.textlength(" – ", font=dash)
            total = w1 + w2 + wdash
            x0 = W / 2 - total / 2
            baseline = py + (panel_h - score_style.size) / 2 - 2
            d.text((x0, baseline), parts[1], font=score_style, fill=TEXT_HI)
            d.text((x0 + w2, baseline + (score_style.size - dash.size) / 2), " – ", font=dash, fill=GOLD)
            d.text((x0 + w2 + wdash, baseline), parts[0], font=score_style, fill=TEXT_HI)
        else:
            _draw_centered(d, W // 2, py + 20, score_or_time, score_style, TEXT_HI, panel_w - 30)
    else:
        _draw_centered(d, W // 2, py + 18, score_or_time, _font(72, bold=True),
                       GOLD if not is_score else TEXT_HI, panel_w - 30)

    if status == "انتهت":
        st_color, st_bg, st_border = (5, 7, 13, 255), (34, 197, 94, 255), False
    elif status == "لم تبدأ":
        st_color, st_bg, st_border = (30, 22, 0, 255), (232, 184, 75, 255), False
    else:
        st_color, st_bg, st_border = (239, 68, 68, 255), None, True
    st_cy = accent_y + 7 + 40 + 36
    _draw_status_pill(d, W // 2, st_cy, status or "—", st_color, st_bg, st_border)

    div_y = st_cy + 36 + 45 + 4
    d.line([inner_x0, div_y, inner_x1, div_y], fill=LINE, width=1)

    title_y = div_y + 9 + 40
    if kind == "end":
        tfont = _font(31, bold=True)
        ttxt = _shape("الهدافون")
        tdir = _text_direction(ttxt)
        tw = d.textlength(ttxt, font=tfont, direction=tdir)
        ball_r = 15
        ttotal = ball_r * 2 + 14 + tw
        tx0 = W / 2 - ttotal / 2
        _draw_ball(d, tx0 + ball_r, title_y + 20, ball_r)
        d.text((tx0 + ball_r * 2 + 14, title_y), ttxt, font=tfont, fill=GOLD_SOFT, direction=tdir)

    if kind == "end" and (hs or aw):
        grid_top = title_y + 44 + 31
        col_gap = 22
        div_x = W / 2
        col_w = (inner_x1 - inner_x0 - col_gap * 2 - 2) / 2
        x_home = inner_x1 - col_w
        x_away = inner_x0
        d.line([div_x, grid_top - 6, div_x, grid_top + rows_n * 62 + 6], fill=LINE, width=2)
        scorer_font = _font(30)
        minute_font = _font(26, bold=True)
        for cx0, lst, is_away in ((x_home, hs, False), (x_away, aw, True)):
            iy = grid_top + 31
            for name, minute in lst:
                sn = _shape(name)
                snd = _text_direction(sn)
                nw = d.textlength(sn, font=scorer_font, direction=snd)
                mtxt = _shape(str(minute))
                mw = d.textlength(mtxt, font=minute_font)
                chip_pad = 12
                chip_h = 38
                ball_r = 13
                gap = 10
                if is_away:
                    chip_left = cx0
                    nx = chip_left + mw + chip_pad * 2 + gap
                    name_x = nx
                    ball_cx = name_x + nw + gap + ball_r
                else:
                    ball_cx = inner_x1 - ball_r
                    name_x = ball_cx - ball_r - gap - nw
                    chip_left = name_x - gap - mw - chip_pad * 2
                _draw_ball(d, ball_cx, iy, ball_r)
                d.rounded_rectangle([chip_left, iy - chip_h / 2, chip_left + mw + chip_pad * 2, iy + chip_h / 2],
                                    radius=chip_h / 2, fill=(255, 255, 255, 14))
                d.text((chip_left + chip_pad, iy - minute_font.size / 2), mtxt, font=minute_font, fill=TEXT_LOW)
                d.text((name_x, iy - scorer_font.size / 2), sn, font=scorer_font, fill=TEXT_HI, direction=snd)
                iy += 62
            if not lst:
                _draw_centered(d, cx0 + col_w / 2, grid_top + 31, "—", scorer_font, TEXT_LOW, col_w)
    elif kind == "end":
        _draw_centered(d, W // 2, title_y + 60, "لا توجد أهداف مسجّلة", _font(30), TEXT_LOW, 500)

    if kind == "start":
        ch_text = " • ".join(channels) if channels else "لم يتم تحديد قناة بعد"
        ch_font = _font(30, bold=True)
        ch_lines = _wrap_lines(d, ch_text, ch_font, W - 320)
        bar_h = max(92, 26 + len(ch_lines) * 44)
        bar_y = H - bar_h - 60
        d.rounded_rectangle([MARGIN + 20, bar_y, W - MARGIN - 20, bar_y + bar_h], radius=20,
                            fill=(18, 26, 54, 235), outline=(60, 80, 140, 255), width=2)
        _draw_tv_icon(d, MARGIN + 90, bar_y + bar_h / 2 - 6, GOLD)
        if channels:
            _draw_right(d, W - MARGIN - 50, bar_y + 16, ch_text, ch_font, TEXT_HI, W - 320)
        else:
            _draw_right(d, W - MARGIN - 50, bar_y + 16, ch_text, ch_font, (255, 150, 80, 255), W - 320)

    buf = io.BytesIO()
    flat = Image.new("RGBA", (W, H), (5, 7, 13, 255))
    flat = Image.alpha_composite(flat, img)
    flat.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _format_channels(channels):
    ch = [c for c in (channels or []) if c]
    if not ch:
        return "📺 القنوات:\n• لم يتم تحديد قناة بعد"
    lines = ["📺 القنوات:"]
    for c in ch:
        lines.append(f"• {c}")
    return "\n".join(lines)


def _parse_match_dt(time_str, now):
    """Convert Arabic match time (HH:MMص/م) to a timezone-aware datetime on now's date."""
    t = (time_str or '').strip()
    is_pm = t.endswith('م')
    hm = t.replace('م', '').replace('ص', '').strip()
    dt = datetime.combine(now.date(), datetime.strptime(hm, '%H:%M').time()).replace(tzinfo=TZ)
    if is_pm:
        if dt.hour != 12:
            dt = dt.replace(hour=dt.hour + 12)
    else:
        if dt.hour == 12:
            dt = dt.replace(hour=0)
    return dt


def _run_telegram_notifications(final_list, state):
    now = datetime.now(TZ)
    sent = []
    for m in final_list:
        key = "_".join(sorted([m['homeTeam'], m['awayTeam']]))
        prev = state.get('prev_status', {}).get(key)
        status = m['status']
        state.setdefault('prev_status', {})[key] = status
        started = state.setdefault('started_notified', {})
        ended = state.setdefault('ended_notified', {})

        if TELEGRAM.get("send_start_alerts", True) and status == "لم تبدأ" and not started.get(key):
            time_str = m['scoreOrTime']
            if ':' in time_str and '-' not in time_str:
                try:
                    start_dt = _parse_match_dt(time_str, now)
                    window = timedelta(minutes=TELEGRAM.get("start_alert_minutes", 10))
                    if now >= start_dt - window and now < start_dt:
                        cap_comm = f"🎙️ {m['commentator']}" if m.get('commentator') else ""
                        caption = (f"🔔 تبدأ قريباً\n\n"
                                   f"🏆 {m['league']}\n"
                                   f"⚽ {m['homeTeam']} 🆚 {m['awayTeam']}\n"
                                   f"⏰ {m['scoreOrTime']}\n"
                                   f"{cap_comm}\n\n"
                                   f"{_format_channels(m['channels'])}")
                        card = compose_match_card(m, 'start')
                        ok = send_telegram_photo(card, caption) if card else False
                        if not ok:
                            ok = send_telegram(caption)
                        if ok:
                            started[key] = True
                            sent.append(f"start:{m['homeTeam']} vs {m['awayTeam']}")
                except Exception:
                    pass

        if TELEGRAM.get("send_end_summary", True) and status == "انتهت" and not ended.get(key) and prev != "انتهت":
            _sc = m.get('scorers') or {"home": [], "away": []}
            cap_sc = ""
            hsc = _sc.get('home') or []
            asc = _sc.get('away') or []
            if hsc:
                cap_sc += f"\n\n⚽ {m['homeTeam']}:\n" + "\n".join(f"  • {n} ({t})" for n, t in hsc)
            if asc:
                cap_sc += f"\n⚽ {m['awayTeam']}:\n" + "\n".join(f"  • {n} ({t})" for n, t in asc)
            caption = (f"🏁 انتهت المباراة\n\n"
                       f"🏆 {m['league']}\n"
                       f"⚽ {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']}"
                       f"{cap_sc}\n\n"
                       f"{_format_channels(m['channels'])}")
            card = compose_match_card(m, 'end')
            ok = send_telegram_photo(card, caption) if card else False
            if not ok:
                ok = send_telegram(caption)
            if ok:
                ended[key] = True
                sent.append(f"end:{m['homeTeam']} vs {m['awayTeam']}")

    if sent:
        print(f"    -> 📨 Telegram notifications sent: {len(sent)}")


def prepare_all_matches(matches_list):
    """Keep every match from the source — no filtering or restrictions."""
    today = datetime.now(TZ).strftime('%Y-%m-%d')
    prepared = []
    for m in matches_list:
        m_date = m.get('_match_date', '')
        if m_date and m_date != today:
            continue
        # Normalize the league name to a clean/standard label when we can.
        raw_league = m['league'] or ''
        std_league = raw_league
        for official_name, keywords in LEAGUES_MAPPING.items():
            if any(kw in raw_league for kw in keywords):
                std_league = official_name
                break
        m['league'] = std_league
        prepared.append(m)
    prepared.sort(key=lambda x: x.get('_order', 0))
    return prepared


_CHAMP_LOGO_CACHE = {}

def fetch_championship_logo(link):
    """Return the championship (league) logo URL from its YSscores page."""
    if not link:
        return ''
    if link in _CHAMP_LOGO_CACHE:
        return _CHAMP_LOGO_CACHE[link]
    logo = ''
    try:
        html = GhostScraper().fetch(link, "YSscores championship")
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            el = soup.select_one('img.club-logo')
            if el and el.get('src'):
                logo = el['src']
            else:
                og = soup.select_one('meta[property="og:image"]')
                if og and og.get('content'):
                    logo = og['content']
    except Exception:
        logo = ''
    _CHAMP_LOGO_CACHE[link] = logo
    return logo


def build_grouped_list(final_list):
    """Reorder matches grouped by league, inserting a league header before each group."""
    grouped = []
    seen_leagues = {}
    for m in final_list:
        league = m.get('league') or ''
        if league and league not in seen_leagues:
            seen_leagues[league] = True
            champ_link = m.get('_championship_link') or ''
            grouped.append({
                'type': 'league',
                'league': league,
                'leagueLogo': fetch_championship_logo(champ_link),
            })
        mm = dict(m)
        mm['type'] = 'match'
        grouped.append(mm)
    return grouped


class GhostScraper:
    def __init__(self):
        self._session = None

    def _get_identity(self):
        from curl_cffi import CurlImpersonate
        s = CurlImpersonate("chrome120")
        return s

    def fetch(self, url, source_name=""):
        try:
            time.sleep(random.uniform(1.0, 2.0))
            r = requests.get(url, impersonate="chrome120", timeout=30,
                             headers={"Accept-Language": "ar,en;q=0.9"})
            if r.status_code == 200:
                return r.text
            print(f"    ❌ [{source_name}] HTTP {r.status_code}: {url}")
        except Exception as e:
            print(f"    ❌ [{source_name}] Error: {e}")
        return None

    def scrape_ysscores(self):
        url = "https://www.ysscores.com/ar/today_matches"
        html = self.fetch(url, "YSscores")
        if not html:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        matches = []
        for champ_div in soup.select('div.matches-wrapper'):
            league = champ_div.get('champ_title', '').strip()
            for match_a in champ_div.select('a.ajax-match-item'):
                _order = len(matches)
                match_id = match_a.get('match_id', '')
                home_name = match_a.get('home_name', '').strip()
                away_name = match_a.get('away_name', '').strip()
                if not home_name or not away_name:
                    continue
                home_logo = match_a.get('home_image', '').strip()
                away_logo = match_a.get('away_image', '').strip()
                if home_logo:
                    home_logo = home_logo.replace('/teams/64/', '/teams/128/')
                if away_logo:
                    away_logo = away_logo.replace('/teams/64/', '/teams/128/')
                match_date_el = match_a.select_one('.match-date')
                match_date_text = match_date_el.get_text(strip=True) if match_date_el else ''
                classes = match_a.get('class', [])
                is_live = any('live-match' in c for c in classes)
                is_stopped = any('stopped-match' in c for c in classes)
                r1 = match_a.select_one('.first-team-result')
                r2 = match_a.select_one('.second-team-result')
                live_score = None
                if r1 is not None and r2 is not None:
                    s1 = r1.get_text(strip=True)
                    s2 = r2.get_text(strip=True)
                    if s1 or s2:
                        live_score = f"{s1 or '0'} - {s2 or '0'}"
                if live_score:
                    status = "مباشر" if is_live else "انتهت"
                    score = live_score
                elif ':' in match_date_text and '-' not in match_date_text:
                    status = "لم تبدأ"
                    score = match_date_text
                elif is_live:
                    status = "مباشر"
                    score = match_date_text or "—"
                elif is_stopped or 'انتهت' in match_date_text:
                    status = "انتهت"
                    score = match_date_text
                else:
                    status = "لم تبدأ"
                    score = match_date_text or "—"
                detail_url = match_a.get('href', '').strip()
                today = datetime.now(TZ).strftime('%Y-%m-%d')
                m = {
                    'homeTeam': home_name,
                    'awayTeam': away_name,
                    'league': league,
                    'scoreOrTime': score,
                    'status': status,
                    'channels': [],
                    'commentator': '',
                    'source': 'YSscores',
                    'homeLogo': home_logo if home_logo.startswith('http') else '',
                    'awayLogo': away_logo if away_logo.startswith('http') else '',
                    'scorers': {"home": [], "away": []},
                    '_order': _order,
                    '_ysscores_detail': detail_url,
                    '_ysscores_id': match_id,
                    '_match_date': today,
                }
                matches.append(m)
        return matches

    def _fetch_ysscores_detail(self, detail_url, match_id=""):
        html = self.fetch(detail_url, f"YSscores (detail {match_id})")
        if not html:
            return {}
        result = {}
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or '')
                if data.get('@type') == 'SportsEvent':
                    ht = data.get('homeTeam', {})
                    at = data.get('awayTeam', {})
                    if ht.get('logo'):
                        result['homeLogo'] = ht['logo']
                    if at.get('logo'):
                        result['awayLogo'] = at['logo']
                    loc = data.get('location', {})
                    if loc.get('name'):
                        result['stadium'] = loc['name']
                    if data.get('startDate'):
                        result['_startDate'] = data['startDate']
                    break
            except Exception:
                continue
        channels = []
        commentators = []
        for item in soup.select('.match-info-item'):
            title_el = item.select_one('.title')
            title_text = title_el.get_text(strip=True) if title_el else ''
            if 'البطولة' in title_text:
                champ_el = item.select_one('.content a[href*="/championship/"]')
                if champ_el:
                    result['_rawLeague'] = champ_el.get_text(strip=True)
                    champ_href = champ_el.get('href')
                    if champ_href:
                        result['_championship_link'] = champ_href
            elif 'الجولة' in title_text:
                round_el = item.select_one('.content')
                if round_el:
                    result['round'] = round_el.get_text(strip=True)
            elif 'ملعب' in title_text and 'stadium' not in result:
                st_el = item.select_one('.content')
                if st_el:
                    result['stadium'] = st_el.get_text(strip=True)
            elif 'المعلق' in title_text:
                co_el = item.select_one('.content a[href*="/commentator/"]')
                if co_el:
                    co_name = co_el.get_text(strip=True)
                    if co_name and co_name not in commentators:
                        commentators.append(co_name)
            else:
                co_el = item.select_one('.content a[href*="/commentator/"]')
                if co_el:
                    co_name = co_el.get_text(strip=True)
                    if co_name and co_name not in commentators:
                        commentators.append(co_name)
        en_url = detail_url.replace('/ar/', '/en/')
        if en_url != detail_url:
            en_html = self.fetch(en_url, f"YSscores EN (detail {match_id})")
            if en_html:
                en_soup = BeautifulSoup(en_html, 'html.parser')
                seen_keys = set()
                for item in en_soup.select('.match-info-item'):
                    ch_el = item.select_one('.title a.channel_info')
                    if ch_el:
                        ch_name = ch_el.get_text(strip=True)
                        k = ch_name.lower().replace(' ', '').replace('-', '')
                        if ch_name and k not in seen_keys:
                            channels.append(ch_name)
                            seen_keys.add(k)
                    else:
                        title_el = item.select_one('.title')
                        title_text = title_el.get_text(strip=True) if title_el else ''
                        if 'Channel' in title_text:
                            ch_el2 = item.select_one('.content a.channel_info')
                            ch_name = ch_el2.get_text(strip=True) if ch_el2 else ''
                            if not ch_name:
                                ch_el2 = item.select_one('.content')
                                ch_name = ch_el2.get_text(strip=True) if ch_el2 else ''
                            k = ch_name.lower().replace(' ', '').replace('-', '')
                            if ch_name and k not in seen_keys:
                                channels.append(ch_name)
                                seen_keys.add(k)
        if not channels:
            subs = soup.select('.match-info-item.sub')
            seen_keys = set()
            for item in subs:
                ch_el = item.select_one('.title a.channel_info')
                if ch_el:
                    ch_name = ch_el.get_text(strip=True)
                    k = ch_name.lower().replace(' ', '').replace('-', '')
                    if ch_name and k not in seen_keys:
                        channels.append(ch_name)
                        seen_keys.add(k)
        channels = [c for c in channels if not _is_app_channel(c)]
        if channels:
            result['channels'] = channels
        if commentators:
            result['commentator'] = ' / '.join(commentators)

        scorers = {"home": [], "away": []}
        for ev in soup.select('.match-event-item'):
            cls = ' '.join(ev.get('class', []))
            if 'goal' not in cls:
                continue
            minute_txt = ''
            for txt_el in ev.find_all(string=True, recursive=True):
                t = txt_el.strip()
                if t and (t.endswith("'") or t.endswith("’")):
                    minute_txt = t
                    break
            minute = minute_txt.strip().rstrip("'’")
            names = []
            for nm in ev.find_all(class_=lambda c: c and ('player' in ' '.join(c) or 'team_name' in ' '.join(c))):
                t = nm.get_text(strip=True)
                if t and t not in ('Offside', 'Penalty'):
                    names.append(t)
            if not names:
                continue
            if 'for-team-b' in cls:
                scorers['away'].append((names[0], minute))
            else:
                scorers['home'].append((names[0], minute))
        if scorers['home'] or scorers['away']:
            result['scorers'] = scorers
        return result

    def _enrich_ysscores_details(self, matches):
        import random as _rnd
        yss_matches = [m for m in matches if m.get('_ysscores_detail')]
        if not yss_matches:
            return
        print(f"    -> جلب تفاصيل {len(yss_matches)} مباراة من YSscores...")
        for m in yss_matches:
            detail = self._fetch_ysscores_detail(m['_ysscores_detail'], m.get('_ysscores_id', ''))
            if not detail:
                continue
            if detail.get('homeLogo'):
                m['homeLogo'] = detail['homeLogo']
            if detail.get('awayLogo'):
                m['awayLogo'] = detail['awayLogo']
            if detail.get('channels'):
                m['channels'] = detail['channels']
            if detail.get('commentator') and not m.get('commentator'):
                m['commentator'] = detail['commentator']
            if detail.get('round') and not m.get('round'):
                m['round'] = detail['round']
            if detail.get('stadium') and not m.get('stadium'):
                m['stadium'] = detail['stadium']
            if detail.get('scorers'):
                m['scorers'] = detail['scorers']
            if detail.get('_rawLeague') and not m.get('_rawLeague'):
                m['_rawLeague'] = detail['_rawLeague']
            if detail.get('_championship_link') and not m.get('_championship_link'):
                m['_championship_link'] = detail['_championship_link']
            time.sleep(_rnd.uniform(1.0, 2.0))


scraper_engine = GhostScraper()

def execute_full_cycle():
    now = datetime.now(TZ)
    print(f"\n-> Fetching Matches for Date: {now.strftime('%Y-%m-%d')}...")

    yss = scraper_engine.scrape_ysscores()
    print(f"    -> يلا شووت: {len(yss)} مباراة")
    scraper_engine._enrich_ysscores_details(yss)

    print(f"\n-> [Debug] Total Raw Matches Extracted: {len(yss)}")

    final_list = prepare_all_matches(yss)

    for m in final_list:
        m.pop('_ysscores_id', None)
        m.pop('_ysscores_detail', None)
        m.pop('_match_date', None)
        m.pop('_order', None)
        m.pop('_startDate', None)
        m.pop('_rawLeague', None)

    print("\n-> All Matches Extracted:")
    if not final_list:
        print("   [No matches found!]")
    else:
        for m in final_list:
            print(f"   ✅ [{m['league']}] {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']} | {m['status']} | {', '.join(m['channels'])}")

    grouped_list = build_grouped_list(final_list)

    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(grouped_list, f, ensure_ascii=False, indent=4)

    print(f"\n-> [OK] Grouped by league & Saved to matches.json (headers + {len(final_list)} matches).")

    state = _load_state()
    _run_telegram_notifications(final_list, state)
    _save_state(state)

    return final_list


if __name__ == "__main__":
    try:
        print("-> GitHub Actions Cycle Triggered...")
        now = datetime.now(TZ)

        # —— Credit-saver: skip running while we're still more than the alert
        # window (default 10 min) ahead of the earliest *upcoming* match.
        too_early = False
        if os.path.exists(MATCHES_FILE):
            try:
                with open(MATCHES_FILE, "r", encoding="utf-8") as f:
                    saved_matches = json.load(f)
                alert_min = int(TELEGRAM.get("start_alert_minutes", 10))
                has_live = any(m.get('status') == "مباشر" for m in saved_matches)
                upcoming_dts = []
                horizon = now + timedelta(days=1)
                for m in saved_matches:
                    if m.get('status') != "لم تبدأ":
                        continue
                    sv = m.get('scoreOrTime', '')
                    if ':' not in sv or '-' in sv:
                        continue
                    try:
                        dt = _parse_match_dt(sv, now)
                        if dt < now:
                            dt = dt + timedelta(days=1)  # فجر الغد
                        upcoming_dts.append(dt)
                    except Exception:
                        continue
                future = [dt for dt in upcoming_dts if now <= dt <= horizon]
                if future and not has_live:
                    earliest = min(future)
                    wake_dt = earliest - timedelta(minutes=alert_min)
                    if now < wake_dt:
                        too_early = True
                        print(f"-> 🌙 أقرب مباراة قادمة ستكون الساعة {earliest.strftime('%H:%M')}.")
                        print(f"-> 💤 الوقت ما زال قبلها بأكثر من {alert_min} دقائق. الخروج الفوري لتوفير رصيد GitHub.")
                        sys.exit(0)
            except Exception:
                pass

        if not too_early:
            execute_full_cycle()

    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\n🛑 System stopped by user.")
    except Exception as e:
        print(f"\n🛑 System stopped due to error: {e}")
