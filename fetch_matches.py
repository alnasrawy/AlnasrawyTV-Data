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

# 💡 مجلد هذا السكربت (المجلد المنفصل matches_data) — كل الملفات تُفتح نسبةً إليه
#    حتى يعمل السكربت من أي مكان (مباشرة أو عبر GitHub Actions).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 💡 مكتبات رسم بطاقة المباراة (تُستخدم لإنشاء صورة PNG احترافية للإشعارات)
try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

# 💡 ضمان طباعة العربية على Windows (الكونسول الافتراضي cp1252 يكسر السكربت عند الطباعة)
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

# ================= إعدادات النظام الأساسية =================
BROWSERS = ["chrome120"]
TZ = timezone(timedelta(hours=3))
PROXIES_LIST = []

# ================= القاموس الذكي الشامل لتوحيد أسماء البطولات =================
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

GENERAL_VIP_KEYWORDS = ["سوبر", "كأس الملك", "كأس الأمير", "كأس الرابطة", "كأس الاتحاد", "تصفيات", "كأس خادم الحرمين", "كأس مصر"]

VIP_TEAMS = [
    "ريال مدريد", "برشلونة", "أتلتيكو", "بايرن", "باريس", "مانشستر", "ليفربول", "أرسنال", "تشيلسي", "توتنهام", "يوفنتوس", "ميلان", "إنتر", "روما",
    "الهلال", "النصر", "الاتحاد", "الأهلي", "الشباب", "الزوراء", "القوة الجوية", "الشرطة", "الطلبة", "الزمالك", "الترجي", "الوداد", "الرجاء"
]

BLOCKLIST = ["شباب", "رديف", "u23", "u19", "درجة ثانية", "درجة ثالثة", "هواة", "سيدات"]

# 💡 قوائم بيضاء لأندية الدرجة الأولى (وليس الثانية) — المصادر تسمّي الدرجة الأولى والثانية
# بنفس الاسم (الدوري الإنجليزي = الممتاز + التشامبيونشيب، الإيطالي = سيري آ + سيري بي، ...).
# المفتاح = الاسم الرسمي في LEAGUES_MAPPING، والقيمة = أندية الدرجة الأولى فقط (موسم 2026-27).
TOP_LEAGUE_TEAMS = {}

# ================= تحميل config.json (الإعدادات كلها بيانات لا كود) =================
def _load_config(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "config.json")
    cfg = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    return cfg

_CFG = _load_config()
_cfg_vip = _CFG.get("vip", {}) or {}
if _cfg_vip.get("leagues"):
    LEAGUES_MAPPING = _cfg_vip["leagues"]
if _cfg_vip.get("general_keywords"):
    GENERAL_VIP_KEYWORDS = _cfg_vip["general_keywords"]
if _cfg_vip.get("teams"):
    VIP_TEAMS = _cfg_vip["teams"]
if _cfg_vip.get("blocklist"):
    BLOCKLIST = _cfg_vip["blocklist"]
if _cfg_vip.get("premier_league_teams"):
    TOP_LEAGUE_TEAMS["الدوري الإنجليزي"] = _cfg_vip["premier_league_teams"]
if _cfg_vip.get("top_league_teams"):
    for k, v in _cfg_vip["top_league_teams"].items():
        TOP_LEAGUE_TEAMS[k] = v

TELEGRAM = _CFG.get("telegram", {}) or {}
SITES_CFG = _CFG.get("sites", {}) or {}
GLOBAL_DELAY = _CFG.get("global_delay", [1.0, 2.0]) or [1.0, 2.0]
FILGOAL_CACHE_TTL = float(_CFG.get("filgoal_cache_ttl_minutes", 30))

# ================= كاش فيلجول (يُحفظ في filgoal_cache.json ويعاد رفعه في كل دورة) =================
FILGOAL_CACHE_FILE = os.path.join(BASE_DIR, "filgoal_cache.json")
FILGOAL_CACHE = {}

# ================= كاش تفاصيل بطولات (أهداف المباريات المنتهية) =================
BTOLAT_DETAIL_CACHE_FILE = os.path.join(BASE_DIR, "btolat_detail_cache.json")
BTOLAT_DETAIL_CACHE = {}
BTOLAT_DETAIL_TTL = float(_CFG.get("btolat_detail_cache_ttl_minutes", 60))

def _load_filgoal_cache():
    try:
        with open(FILGOAL_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_filgoal_cache():
    try:
        with open(FILGOAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(FILGOAL_CACHE, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _load_btolat_detail_cache():
    try:
        with open(BTOLAT_DETAIL_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_btolat_detail_cache():
    try:
        with open(BTOLAT_DETAIL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(BTOLAT_DETAIL_CACHE, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

# ================= حالة الإشعارات (يُحفظ في state.json) =================
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
    """إرسال رسالة للقناة عبر البوت. التوكين يأتي من متغير البيئة TG_BOT_TOKEN (سر GitHub) — لا يُخزن في الملفات."""
    if not TELEGRAM.get("enabled"):
        return False
    token = os.environ.get("TG_BOT_TOKEN")
    chat = (TELEGRAM.get("channel") or "").strip()
    if not token or not chat:
        if not _TG_WARNED["once"]:
            print("    ⚠️ Telegram: TG_BOT_TOKEN (سر GitHub) أو channel غير مضبوط — تخطي الإشعارات.")
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
    """إرسال صورة كارت المباراة (PNG) إلى القناة عبر البوت."""
    if not TELEGRAM.get("enabled"):
        return False
    token = os.environ.get("TG_BOT_TOKEN")
    chat = (TELEGRAM.get("channel") or "").strip()
    if not token or not chat:
        if not _TG_WARNED["once"]:
            print("    ⚠️ Telegram: TG_BOT_TOKEN (سر GitHub) أو channel غير مضبوط — تخطي الإشعارات.")
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


# ================= مولّد بطاقة المباراة (صورة احترافية) =================
_FONT_CACHE = {}
_LOGO_CACHE = {}
_SHAPE_WARNED = {"once": False}
_RAQM = {"done": False, "value": False}


def _uses_raqm():
    """هل Pillow مثبّتة مع libraqm؟ إن نعم، Pillow تتشكّل النص العربي تلقائياً (OpenType shaping) —
    لذلك يجب ألا نُعيد التشكيل يدوياً بـ arabic_reshaper وإلا حدث تشكيل مزدوج وأحرف متداخلة.
    (wheels الرسمية لـ Pillow على Linux تأتي مع libraqm مفعّل — راجع سجل GitHub Actions.)"""
    if not _RAQM["done"]:
        try:
            from PIL import features
            _RAQM["value"] = bool(features.check("raqm"))
        except Exception:
            _RAQM["value"] = False
        _RAQM["done"] = True
    return _RAQM["value"]


def _contains_rtl(text):
    """يكشف إن كان النص يحتوي على أحرف عربية (RTL) لتحديد اتجاه الرسم مع libraqm."""
    return any(
        ('\u0600' <= c <= '\u06FF') or ('\u0750' <= c <= '\u077F') or
        ('\uFB50' <= c <= '\uFDFF') or ('\uFE70' <= c <= '\uFEFF')
        for c in str(text)
    )


def _text_direction(text):
    """اتجاه النص الذي يُمرَّر إلى Pillow عند تفعيل libraqm (None = بدون raqm / نص LTR)."""
    if not _uses_raqm():
        return None
    return "rtl" if _contains_rtl(str(text)) else None

_ARABIC_FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Regular.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Bold.ttf",
]

# 💡 مسارات الخط المحمّل مسبقاً في الـ workflow (مضمون 100% — يمنع سقوط السكربت على خط بدون عربية)
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
    # 1) الخط المحمّل مسبقاً في الـ workflow (الأضمن)
    for p in _FONT_PREFERRED_PATHS.get(kind, []):
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            return p
    # 2) خط محمّل مسبقاً في جلسة سابقة (temp)
    p = os.path.join(tempfile.gettempdir(), f"card_font_{kind}.ttf")
    if os.path.exists(p) and os.path.getsize(p) > 5000:
        return p
    # 3) تنزيل Tajawal مباشرة
    url = _ARABIC_FONT_URLS[0 if kind == "regular" else 1]
    try:
        r = requests.get(url, timeout=25, impersonate="chrome120")
        if r.status_code == 200 and len(r.content) > 5000:
            with open(p, "wb") as f:
                f.write(r.content)
            return p
    except Exception:
        pass
    # 4) خط نظام يدعم العربية إن وُجد
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
        print("    ⚠️ لا يوجد خط عربي متاح (فشل تحميل Tajawal) — سيتم إرسال نص بديل بدلاً من كارت مشوّه.")
    _FONT_CACHE[key] = font
    return font


def _shape(text):
    """إعادة تشكيل النص العربي + الاتجاه من اليمين لليسار للعرض الصحيح داخل الصورة.
    ملاحظة مهمة: إذا كانت Pillow مثبّتة مع libraqm فإنها تتشكّل النص تلقائياً،
    وإعادة التشكيل اليدوي هنا تُفسد النص (تشكيل مزدوج → أحرف متداخلة)."""
    if _uses_raqm():
        return str(text)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        if not _SHAPE_WARNED["once"]:
            print("    ⚠️ arabic_reshaper / python-bidi غير مثبتة! ثبّتها في الـ workflow وإلا ظهر النص العربي مشوهاً.")
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

_TEAM_LOGO_FALLBACK = {
    "ابها": "https://semedia.filgoal.com/Photos/Team/Medium/520.png",
    "اتالانتا": "https://semedia.filgoal.com/Photos/Team/Medium/128.png",
    "اتحادكلباء": "https://semedia.filgoal.com/Photos/Team/Medium/1374.png",
    "اتلتيكومدريد": "https://semedia.filgoal.com/Photos/Team/Medium/147.png",
    "اتليتكبلباو": "https://semedia.filgoal.com/Photos/Team/Medium/116.png",
    "ارسنال": "https://semedia.filgoal.com/Photos/Team/Medium/83.png",
    "اسبانيول": "https://semedia.filgoal.com/Photos/Team/Medium/119.png",
    "استونفيلا": "https://semedia.filgoal.com/Photos/Team/Medium/84.png",
    "اسكولي": "https://semedia.filgoal.com/Photos/Team/Medium/536.png",
    "اشبيليه": "https://semedia.filgoal.com/Photos/Team/Medium/126.png",
    "الاتحاد": "https://semedia.filgoal.com/Photos/Team/Medium/175.png",
    "الاتفاق": "https://semedia.filgoal.com/Photos/Team/Medium/182.png",
    "الاخدود": "https://semedia.filgoal.com/Photos/Team/Medium/12747.png",
    "الافيس": "https://semedia.filgoal.com/Photos/Team/Medium/115.png",
    "الانصار": "https://semedia.filgoal.com/Photos/Team/Medium/320.png",
    "الاهلي": "https://semedia.filgoal.com/Photos/Team/Medium/1.png",
    "الاهليالاماراتي": "https://semedia.filgoal.com/Photos/Team/Medium/1199.png",
    "الباسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/206.png",
    "الباطن": "https://semedia.filgoal.com/Photos/Team/Medium/1442.png",
    "التشي": "https://semedia.filgoal.com/Photos/Team/Medium/1393.png",
    "التعاون": "https://semedia.filgoal.com/Photos/Team/Medium/1043.png",
    "الجبيل": "https://semedia.filgoal.com/Photos/Team/Medium/12749.png",
    "الجزيره": "https://semedia.filgoal.com/Photos/Team/Medium/875.png",
    "الجيل": "https://semedia.filgoal.com/Photos/Team/Medium/1446.png",
    "الحر": "https://semedia.filgoal.com/Photos/Team/Medium/2036.png",
    "الحزم": "https://semedia.filgoal.com/Photos/Team/Medium/521.png",
    "الخلود": "https://semedia.filgoal.com/Photos/Team/Medium/12745.png",
    "الخليج": "https://semedia.filgoal.com/Photos/Team/Medium/188.png",
    "الدرع": "https://semedia.filgoal.com/Photos/Team/Medium/12740.png",
    "الدرعيه": "https://semedia.filgoal.com/Photos/Team/Medium/1443.png",
    "الرائد": "https://semedia.filgoal.com/Photos/Team/Medium/184.png",
    "الرياض": "https://semedia.filgoal.com/Photos/Team/Medium/181.png",
    "الزمالك": "https://semedia.filgoal.com/Photos/Team/Medium/2.png",
    "الزوراء": "https://semedia.filgoal.com/Photos/Team/Medium/290.png",
    "السد": "https://semedia.filgoal.com/Photos/Team/Medium/12746.png",
    "الشارقه": "https://semedia.filgoal.com/Photos/Team/Medium/872.png",
    "الشباب": "https://semedia.filgoal.com/Photos/Team/Medium/180.png",
    "الشرطه": "https://semedia.filgoal.com/Photos/Team/Medium/1218.png",
    "الشعله": "https://semedia.filgoal.com/Photos/Team/Medium/186.png",
    "الصقور": "https://semedia.filgoal.com/Photos/Team/Medium/12741.png",
    "الطائي": "https://semedia.filgoal.com/Photos/Team/Medium/185.png",
    "الطلبه": "https://img.btolat.com/teamslogo/11517.png?v=211",
    "الظفره": "https://semedia.filgoal.com/Photos/Team/Medium/867.png",
    "العربي": "https://semedia.filgoal.com/Photos/Team/Medium/1250.png",
    "العروبه": "https://semedia.filgoal.com/Photos/Team/Medium/1251.png",
    "العين": "https://semedia.filgoal.com/Photos/Team/Medium/871.png",
    "الفتح": "https://semedia.filgoal.com/Photos/Team/Medium/995.png",
    "الفجيره": "https://semedia.filgoal.com/Photos/Team/Medium/1252.png",
    "الفيحاء": "https://semedia.filgoal.com/Photos/Team/Medium/1445.png",
    "الفيصلي": "https://semedia.filgoal.com/Photos/Team/Medium/663.png",
    "القادسيه": "https://semedia.filgoal.com/Photos/Team/Medium/179.png",
    "القواتالمسلحه": "https://semedia.filgoal.com/Photos/Team/Medium/1253.png",
    "القوهالجويه": "https://semedia.filgoal.com/Photos/Team/Medium/877.png",
    "الكرخ": "https://semedia.filgoal.com/Photos/Team/Medium/1220.png",
    "الكرمه": "https://img.btolat.com/teamslogo/41313.png?v=847",
    "المجزل": "https://semedia.filgoal.com/Photos/Team/Medium/1444.png",
    "المصفاه": "https://semedia.filgoal.com/Photos/Team/Medium/1260.png",
    "الموصل": "https://semedia.filgoal.com/Photos/Team/Medium/1223.png",
    "الميناء": "https://semedia.filgoal.com/Photos/Team/Medium/1224.png",
    "النجده": "https://semedia.filgoal.com/Photos/Team/Medium/2037.png",
    "النجمه": "https://semedia.filgoal.com/Photos/Team/Medium/183.png",
    "النجوم": "https://semedia.filgoal.com/Photos/Team/Medium/1550.png",
    "النصر": "https://semedia.filgoal.com/Photos/Team/Medium/873.png",
    "النفط": "https://semedia.filgoal.com/Photos/Team/Medium/1226.png",
    "الهلال": "https://semedia.filgoal.com/Photos/Team/Medium/269.png",
    "الواديالاخضر": "https://semedia.filgoal.com/Photos/Team/Medium/1481.png",
    "الوحده": "https://semedia.filgoal.com/Photos/Team/Medium/876.png",
    "الوصل": "https://semedia.filgoal.com/Photos/Team/Medium/869.png",
    "امبولي": "https://semedia.filgoal.com/Photos/Team/Medium/133.png",
    "اميان": "https://semedia.filgoal.com/Photos/Team/Medium/2010.png",
    "انترميلان": "https://semedia.filgoal.com/Photos/Team/Medium/134.png",
    "انجيه": "https://semedia.filgoal.com/Photos/Team/Medium/1542.png",
    "اوجسبورج": "https://semedia.filgoal.com/Photos/Team/Medium/1297.png",
    "اودينسي": "https://semedia.filgoal.com/Photos/Team/Medium/1068.png",
    "اودينيزي": "https://semedia.filgoal.com/Photos/Team/Medium/145.png",
    "اوساسونا": "https://semedia.filgoal.com/Photos/Team/Medium/118.png",
    "اوكسير": "https://semedia.filgoal.com/Photos/Team/Medium/302.png",
    "اولمبيكليون": "https://semedia.filgoal.com/Photos/Team/Medium/211.png",
    "اولمبيكمارسيليا": "https://semedia.filgoal.com/Photos/Team/Medium/222.png",
    "ايبار": "https://semedia.filgoal.com/Photos/Team/Medium/1435.png",
    "ايركوليس": "https://semedia.filgoal.com/Photos/Team/Medium/1545.png",
    "اينتراختفرانكفورت": "https://semedia.filgoal.com/Photos/Team/Medium/196.png",
    "اينجولشتات": "https://semedia.filgoal.com/Photos/Team/Medium/1540.png",
    "بادربورن": "https://semedia.filgoal.com/Photos/Team/Medium/1433.png",
    "بادوفا": "https://img.btolat.com/teamslogo/11956.png?v=491",
    "بارما": "https://semedia.filgoal.com/Photos/Team/Medium/139.png",
    "بارنت": "https://semedia.filgoal.com/Photos/Team/Medium/2038.png",
    "باريسسانجيرمان": "https://semedia.filgoal.com/Photos/Team/Medium/237.png",
    "بازل": "https://semedia.filgoal.com/Photos/Team/Medium/344.png",
    "باليرمو": "https://semedia.filgoal.com/Photos/Team/Medium/322.png",
    "بايرليفركوزن": "https://semedia.filgoal.com/Photos/Team/Medium/156.png",
    "بايرنب": "https://semedia.filgoal.com/Photos/Team/Medium/1517.png",
    "بايرنميونيخ": "https://semedia.filgoal.com/Photos/Team/Medium/153.png",
    "برايتون": "https://semedia.filgoal.com/Photos/Team/Medium/1426.png",
    "برشلونه": "https://semedia.filgoal.com/Photos/Team/Medium/111.png",
    "برمنجامسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/85.png",
    "برمنجهامسيتي": "https://img.btolat.com/teamslogo/9039.png?v=667",
    "بروسيادورتموند": "https://semedia.filgoal.com/Photos/Team/Medium/154.png",
    "بريستولسيتي": "https://img.btolat.com/teamslogo/9066.png?v=886",
    "بريستون": "https://semedia.filgoal.com/Photos/Team/Medium/823.png",
    "بريستوننورثاند": "https://img.btolat.com/teamslogo/9317.png?v=402",
    "بريشيا": "https://semedia.filgoal.com/Photos/Team/Medium/130.png",
    "برينتفورد": "https://semedia.filgoal.com/Photos/Team/Medium/1920.png",
    "بنيياس": "https://semedia.filgoal.com/Photos/Team/Medium/1198.png",
    "بوخوم": "https://semedia.filgoal.com/Photos/Team/Medium/165.png",
    "بورتسموث": "https://semedia.filgoal.com/Photos/Team/Medium/198.png",
    "بورتفايل": "https://semedia.filgoal.com/Photos/Team/Medium/2023.png",
    "بورتو": "https://semedia.filgoal.com/Photos/Team/Medium/224.png",
    "بوردو": "https://semedia.filgoal.com/Photos/Team/Medium/305.png",
    "بورنموث": "https://semedia.filgoal.com/Photos/Team/Medium/1453.png",
    "بوروسيامونشنجلادباخ": "https://semedia.filgoal.com/Photos/Team/Medium/164.png",
    "بولتونواندررز": "https://semedia.filgoal.com/Photos/Team/Medium/87.png",
    "بولونيا": "https://semedia.filgoal.com/Photos/Team/Medium/129.png",
    "بيراميدز": "https://semedia.filgoal.com/Photos/Team/Medium/1451.png",
    "بيرنلي": "https://semedia.filgoal.com/Photos/Team/Medium/992.png",
    "بيروجيا": "https://semedia.filgoal.com/Photos/Team/Medium/140.png",
    "بيسكارا": "https://semedia.filgoal.com/Photos/Team/Medium/1352.png",
    "تروا": "https://semedia.filgoal.com/Photos/Team/Medium/511.png",
    "تريفيزو": "https://semedia.filgoal.com/Photos/Team/Medium/537.png",
    "تشارلتوناتليتك": "https://semedia.filgoal.com/Photos/Team/Medium/88.png",
    "تشارلتوناثليتيك": "https://img.btolat.com/teamslogo/9088.png?v=731",
    "تشيلسي": "https://semedia.filgoal.com/Photos/Team/Medium/89.png",
    "توتنهامهوتسبر": "https://semedia.filgoal.com/Photos/Team/Medium/101.png",
    "تورينو": "https://semedia.filgoal.com/Photos/Team/Medium/144.png",
    "تولوز": "https://semedia.filgoal.com/Photos/Team/Medium/315.png",
    "جرويترفيورث": "https://semedia.filgoal.com/Photos/Team/Medium/1354.png",
    "جيرونا": "https://semedia.filgoal.com/Photos/Team/Medium/2014.png",
    "حتا": "https://semedia.filgoal.com/Photos/Team/Medium/1254.png",
    "خيتافي": "https://semedia.filgoal.com/Photos/Team/Medium/317.png",
    "دارمشتات": "https://semedia.filgoal.com/Photos/Team/Medium/1541.png",
    "دباالحصن": "https://semedia.filgoal.com/Photos/Team/Medium/1255.png",
    "دباالفجيره": "https://semedia.filgoal.com/Photos/Team/Medium/1256.png",
    "دهوك": "https://semedia.filgoal.com/Photos/Team/Medium/1228.png",
    "ديالي": "https://semedia.filgoal.com/Photos/Team/Medium/1229.png",
    "ديجون": "https://semedia.filgoal.com/Photos/Team/Medium/1300.png",
    "ديربيكاونتي": "https://img.btolat.com/teamslogo/9133.png?v=92",
    "دينامودريسدين": "https://semedia.filgoal.com/Photos/Team/Medium/1518.png",
    "راسالخيمه": "https://semedia.filgoal.com/Photos/Team/Medium/1257.png",
    "راسينجسانتاندير": "https://semedia.filgoal.com/Photos/Team/Medium/146.png",
    "رايوفاييكانو": "https://semedia.filgoal.com/Photos/Team/Medium/122.png",
    "روتارفورت": "https://semedia.filgoal.com/Photos/Team/Medium/2024.png",
    "روتفايسايسن": "https://semedia.filgoal.com/Photos/Team/Medium/2020.png",
    "روما": "https://semedia.filgoal.com/Photos/Team/Medium/143.png",
    "ريالبيتيس": "https://semedia.filgoal.com/Photos/Team/Medium/123.png",
    "ريالسرقسطه": "https://semedia.filgoal.com/Photos/Team/Medium/207.png",
    "ريالسوسيداد": "https://semedia.filgoal.com/Photos/Team/Medium/124.png",
    "ريالمايوركا": "https://semedia.filgoal.com/Photos/Team/Medium/121.png",
    "ريالمدريد": "https://semedia.filgoal.com/Photos/Team/Medium/110.png",
    "ريالمورسيا": "https://semedia.filgoal.com/Photos/Team/Medium/208.png",
    "ريجينا": "https://semedia.filgoal.com/Photos/Team/Medium/142.png",
    "زاخو": "https://semedia.filgoal.com/Photos/Team/Medium/1230.png",
    "ساسولو": "https://semedia.filgoal.com/Photos/Team/Medium/1396.png",
    "سامبدوريا": "https://semedia.filgoal.com/Photos/Team/Medium/203.png",
    "سانتايتيان": "https://semedia.filgoal.com/Photos/Team/Medium/313.png",
    "سانتباولي": "https://semedia.filgoal.com/Photos/Team/Medium/1042.png",
    "سانتجالن": "https://semedia.filgoal.com/Photos/Team/Medium/1355.png",
    "ساوثامبتون": "https://semedia.filgoal.com/Photos/Team/Medium/98.png",
    "سبورتنجخيخون": "https://semedia.filgoal.com/Photos/Team/Medium/858.png",
    "ستادبريست29": "https://semedia.filgoal.com/Photos/Team/Medium/1037.png",
    "ستادرين": "https://semedia.filgoal.com/Photos/Team/Medium/312.png",
    "ستوكسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/857.png",
    "سوانزيسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/1294.png",
    "سوانسيسيتي": "https://img.btolat.com/teamslogo/9387.png?v=826",
    "سوتيرولبولدزانو": "https://img.btolat.com/teamslogo/12041.png?v=818",
    "سوشو": "https://semedia.filgoal.com/Photos/Team/Medium/301.png",
    "سياييوروبا": "https://semedia.filgoal.com/Photos/Team/Medium/14453.png",
    "سيرفيت": "https://semedia.filgoal.com/Photos/Team/Medium/1358.png",
    "سيلتافيجو": "https://semedia.filgoal.com/Photos/Team/Medium/117.png",
    "سيينا": "https://semedia.filgoal.com/Photos/Team/Medium/193.png",
    "شالكه": "https://semedia.filgoal.com/Photos/Team/Medium/155.png",
    "شتوتجارت": "https://semedia.filgoal.com/Photos/Team/Medium/160.png",
    "شوروسبريتاون": "https://semedia.filgoal.com/Photos/Team/Medium/1454.png",
    "شيفيلدوينزداي": "https://semedia.filgoal.com/Photos/Team/Medium/1560.png",
    "شيفيلديونايتد": "https://semedia.filgoal.com/Photos/Team/Medium/1035.png",
    "ضمك": "https://semedia.filgoal.com/Photos/Team/Medium/1549.png",
    "عجمان": "https://semedia.filgoal.com/Photos/Team/Medium/868.png",
    "فالنسيا": "https://semedia.filgoal.com/Photos/Team/Medium/112.png",
    "فرايبورج": "https://semedia.filgoal.com/Photos/Team/Medium/195.png",
    "فروزينوني": "https://semedia.filgoal.com/Photos/Team/Medium/1534.png",
    "فورتونادوسلدورف": "https://semedia.filgoal.com/Photos/Team/Medium/1353.png",
    "فولفسبورج": "https://semedia.filgoal.com/Photos/Team/Medium/163.png",
    "فياريال": "https://semedia.filgoal.com/Photos/Team/Medium/127.png",
    "فيردربريمن": "https://semedia.filgoal.com/Photos/Team/Medium/168.png",
    "فينيتسيا": "https://img.btolat.com/teamslogo/12088.png?v=610",
    "فيورنتينا": "https://semedia.filgoal.com/Photos/Team/Medium/323.png",
    "قرطبه": "https://semedia.filgoal.com/Photos/Team/Medium/1434.png",
    "كاتاندزارو": "https://img.btolat.com/teamslogo/11845.png?v=257",
    "كاراريزي": "https://img.btolat.com/teamslogo/11838.png?v=880",
    "كاربي": "https://semedia.filgoal.com/Photos/Team/Medium/1533.png",
    "كالياري": "https://semedia.filgoal.com/Photos/Team/Medium/324.png",
    "كان": "https://semedia.filgoal.com/Photos/Team/Medium/307.png",
    "كربلاء": "https://semedia.filgoal.com/Photos/Team/Medium/1232.png",
    "كروالكساندرا": "https://semedia.filgoal.com/Photos/Team/Medium/1800.png",
    "كوفنتريسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/821.png",
    "كولن": "https://semedia.filgoal.com/Photos/Team/Medium/194.png",
    "كومو": "https://semedia.filgoal.com/Photos/Team/Medium/132.png",
    "كوينزباركرينجرز": "https://semedia.filgoal.com/Photos/Team/Medium/1293.png",
    "كييفوفيرونا": "https://semedia.filgoal.com/Photos/Team/Medium/131.png",
    "لاتسيو": "https://semedia.filgoal.com/Photos/Team/Medium/136.png",
    "لاسبالماس": "https://semedia.filgoal.com/Photos/Team/Medium/1514.png",
    "لانس": "https://semedia.filgoal.com/Photos/Team/Medium/309.png",
    "لايبزيج": "https://semedia.filgoal.com/Photos/Team/Medium/1742.png",
    "لوزان": "https://semedia.filgoal.com/Photos/Team/Medium/1070.png",
    "لوزيرن": "https://semedia.filgoal.com/Photos/Team/Medium/1357.png",
    "لومان": "https://semedia.filgoal.com/Photos/Team/Medium/510.png",
    "ليتشي": "https://semedia.filgoal.com/Photos/Team/Medium/204.png",
    "ليدزيونايتد": "https://semedia.filgoal.com/Photos/Team/Medium/92.png",
    "ليسترسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/199.png",
    "ليفانتي": "https://semedia.filgoal.com/Photos/Team/Medium/314.png",
    "ليفربول": "https://semedia.filgoal.com/Photos/Team/Medium/93.png",
    "ليل": "https://semedia.filgoal.com/Photos/Team/Medium/310.png",
    "لينكولنسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/1902.png",
    "مانشسترسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/94.png",
    "مانشستريونايتد": "https://semedia.filgoal.com/Photos/Team/Medium/95.png",
    "ماينز05": "https://semedia.filgoal.com/Photos/Team/Medium/297.png",
    "مودينا": "https://semedia.filgoal.com/Photos/Team/Medium/138.png",
    "مولده": "https://semedia.filgoal.com/Photos/Team/Medium/1371.png",
    "موناكو": "https://semedia.filgoal.com/Photos/Team/Medium/210.png",
    "ميتز": "https://semedia.filgoal.com/Photos/Team/Medium/311.png",
    "ميدلسبره": "https://semedia.filgoal.com/Photos/Team/Medium/96.png",
    "ميسينا": "https://semedia.filgoal.com/Photos/Team/Medium/318.png",
    "ميلان": "https://semedia.filgoal.com/Photos/Team/Medium/137.png",
    "ميلتونكينزدونز": "https://semedia.filgoal.com/Photos/Team/Medium/1455.png",
    "ميلوول": "https://img.btolat.com/teamslogo/9276.png?v=589",
    "ناديالامارات": "https://semedia.filgoal.com/Photos/Team/Medium/286.png",
    "نوتنجهامفورست": "https://semedia.filgoal.com/Photos/Team/Medium/1423.png",
    "نورنبرج": "https://semedia.filgoal.com/Photos/Team/Medium/167.png",
    "نورويتشسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/298.png",
    "نوفاراكالشيو": "https://semedia.filgoal.com/Photos/Team/Medium/1295.png",
    "نومانسيا": "https://semedia.filgoal.com/Photos/Team/Medium/316.png",
    "نيوكاسليونايتد": "https://semedia.filgoal.com/Photos/Team/Medium/97.png",
    "نيوم": "https://semedia.filgoal.com/Photos/Team/Medium/13692.png",
    "هالسيتي": "https://semedia.filgoal.com/Photos/Team/Medium/856.png",
    "هامبورج": "https://semedia.filgoal.com/Photos/Team/Medium/161.png",
    "هانزاروستوك": "https://semedia.filgoal.com/Photos/Team/Medium/162.png",
    "هانوفر": "https://semedia.filgoal.com/Photos/Team/Medium/166.png",
    "هجر": "https://semedia.filgoal.com/Photos/Team/Medium/1261.png",
    "هوفنهايم": "https://semedia.filgoal.com/Photos/Team/Medium/848.png",
    "هيرتابرلين": "https://semedia.filgoal.com/Photos/Team/Medium/158.png",
    "هيركوليز": "https://semedia.filgoal.com/Photos/Team/Medium/1048.png",
    "هيلاسفيرونا": "https://semedia.filgoal.com/Photos/Team/Medium/1395.png",
    "وستبروميتش": "https://img.btolat.com/teamslogo/9426.png?v=743",
    "وستبروميتشالبيون": "https://semedia.filgoal.com/Photos/Team/Medium/102.png",
    "وستهاميونايتد": "https://semedia.filgoal.com/Photos/Team/Medium/103.png",
    "ويجان": "https://semedia.filgoal.com/Photos/Team/Medium/516.png",
    "ويلفرهامبتون": "https://semedia.filgoal.com/Photos/Team/Medium/200.png",
    "ويمبلدون": "https://semedia.filgoal.com/Photos/Team/Medium/1900.png",
    "يوفنتوس": "https://semedia.filgoal.com/Photos/Team/Medium/135.png",
}

_TEAM_LOGO_FALLBACK_LEAGUE = {
    "الدوريالاماراتي|الاتحاد": "https://semedia.filgoal.com/Photos/Team/Medium/1197.png",
    "الدوريالاماراتي|الاتحادكلباء": "https://semedia.filgoal.com/Photos/Team/Medium/1374.png",
    "الدوريالاماراتي|النصر": "https://semedia.filgoal.com/Photos/Team/Medium/873.png",
    "الدوريالاماراتي|الوحده": "https://semedia.filgoal.com/Photos/Team/Medium/876.png",
    "الدوريالاماراتي|شبابالاهلي": "https://semedia.filgoal.com/Photos/Team/Medium/1199.png",
    "الدوريالسعودي|الاتحاد": "https://semedia.filgoal.com/Photos/Team/Medium/175.png",
    "الدوريالسعودي|النصر": "https://semedia.filgoal.com/Photos/Team/Medium/177.png",
    "الدوريالسعودي|الوحده": "https://semedia.filgoal.com/Photos/Team/Medium/187.png",
}


def _team_color(name):
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return _TEAM_PALETTE[h % len(_TEAM_PALETTE)]


def _load_team_logo(url, team_name, league=None, size=210):
    """تحميل لوجو الفريق من رابط المسح، فإن فشل نجرب خريطة اللوجوهات الثابتة
    (مفاتيح أسماء مُطبّعة)، ثم نرسم دائرة ملونة بأول حرف من اسم الفريق."""
    key = (url, team_name, league, size)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    candidates = [url] if url else []
    tkey = _norm_key(team_name)
    fb = _TEAM_LOGO_FALLBACK.get(tkey)
    if fb and fb not in candidates:
        candidates.append(fb)
    fb_lg = _TEAM_LOGO_FALLBACK_LEAGUE.get(f"{_norm_key(league)}|{tkey}")
    if fb_lg and fb_lg not in candidates:
        candidates.append(fb_lg)
    img = None
    for u in candidates:
        try:
            r = requests.get(u, timeout=15, impersonate="chrome120",
                             headers={"Referer": "https://www.filgoal.com/"})
            if r.status_code == 200 and len(r.content) > 100:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                # قص الفراغ الشفاف حول اللوجو ثم تكبيره ليملأ الدائرة تقريباً
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
                break
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
    """يقسّم نصاً إلى أسطر حسب عرض متاح (يستخدم _draw_centered نفس المنطق)."""
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
    return lines or [str(text)]


def _draw_badge(d, cx, cy, text, font, fill, bg):
    """شارة (بيل) دائرية الزوايا حول نص — خلفية صلبة ونص متباين دائماً.
    إذا كان bg = None تُرسم خلفية شفافة مع حدود بلون fill (نمط "مباشر" LIVE)."""
    if font is None:
        return
    s = _shape(text)
    direction = _text_direction(s)
    tw = d.textlength(s, font=font, direction=direction)
    w, h = tw + 56, font.size + 26
    x0, y0 = cx - w / 2, cy - h / 2
    if bg is not None:
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=bg)
    else:
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=(255, 255, 255, 6),
                            outline=fill, width=2)
    d.text((cx - tw / 2, y0 + (h - font.size) / 2), s, font=font, fill=fill, direction=direction)


def _draw_status_pill(d, cx, cy, text, fill, bg, outline):
    """شارة الحالة مثل .status-pill في القالب: نقطة + نص، خلفية صلبة ملونة
    أو شفافة بحدود ملونة عندما outline=True (حالة مباشر)."""
    if fill is None:
        return
    font = _font(29, bold=True)
    s = _shape(text)
    direction = _text_direction(s)
    tw = d.textlength(s, font=font, direction=direction)
    dot_r = 7
    gap = 14
    w = tw + dot_r * 2 + gap + 36
    h = font.size + 26
    x0, y0 = cx - w / 2, cy - h / 2
    if outline:
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=(255, 255, 255, 6),
                            outline=fill, width=2)
    else:
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h / 2, fill=bg)
    d.ellipse([x0 + 22 - dot_r, cy - dot_r, x0 + 22 + dot_r, cy + dot_r], fill=fill)
    d.text((x0 + 22 + dot_r + gap, y0 + (h - font.size) / 2), s, font=font, fill=fill, direction=direction)


def _draw_star(d, cx, cy, r, fill):
    """نجمة خماسية بسيطة — بديل إيموجي 🏆 (لا يُرسم بالخط العربي)."""
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=fill)


def _draw_ball(d, cx, cy, r):
    """كرة قدم مصغّرة (⚽) مرسومة بخطوط — تُستخدم بدل الإيموجي."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(248, 250, 252, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(70, 78, 92, 255), width=2)
    d.arc([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], 200, 340, fill=(70, 78, 92, 255), width=2)
    d.arc([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], 20, 160, fill=(70, 78, 92, 255), width=2)


def compose_match_card(match, kind="end"):
    """يرسم بطاقة المباراة مطابقة لقالب HTML الزجاجي الداكن (RTL) ويعيد بايتات PNG،
    أو None عند فشل الرسم.
    kind: 'start' (تنبيه بدء) أو 'end' (ملخص نهاية مع الهدافين)."""
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
    s = 2.25  # مقياس التحويل من قالب 480px → 1080px

    # ── مقاسات ثابتة من القالب (مضروبة في مقياس التحويل) ──
    MARGIN = 30            # هامش حول البطاقة (القالب يعرضها فوق خلفية الصفحة)
    PAD = 54               # حشوة البطاقة الداخلية (24px × 2.25)
    RAD = 40               # زوايا البطاقة الدائرية
    WRAP = int(64 * s) + 26      # 170 قطر الدائرة البيضاء (حلقة رفيعة فقط)
    LOGO = int(64 * s)           # 144 اللوجو يكاد يملأها
    inner_x0 = MARGIN + PAD
    inner_x1 = W - MARGIN - PAD
    cx_home = inner_x1 - WRAP // 2          # يمين (RTL أول عمود = المضيف)
    cx_away = inner_x0 + WRAP // 2          # يسار
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

    # ── خلفية الصفحة: تدرج داكن + توهجات شعاعية (مثل body في القالب) ──
    top_c = (5, 7, 13)       # #05070d
    mid_c = (12, 18, 32)     # #0c1220
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
    gd.ellipse([int(W * 0.10), -160, int(W * 0.55), 320], fill=(232, 184, 75, 26))     # ذهبي أعلى يسار
    gd.ellipse([int(W * 0.55), -120, W + 80, 360], fill=(59, 90, 180, 40))             # أزرق أعلى يمين
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img, "RGBA")

    # ── البطاقة الزجاجية نفسها (مثل .card) ──
    d.rounded_rectangle([MARGIN, MARGIN, W - MARGIN, H - MARGIN], radius=RAD,
                        fill=(18, 26, 46, 140), outline=(255, 255, 255, 20), width=2)

    # توهج ذهبي خلف اللوجوهين (مثل .card::before)
    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g2 = ImageDraw.Draw(glow2)
    g2.ellipse([W / 2 - 430, 40, W / 2 + 430, 40 + 620], fill=(232, 184, 75, 22))
    img = Image.alpha_composite(img, glow2)
    d = ImageDraw.Draw(img, "RGBA")

    # ── الألوان من القالب ──
    GOLD = (232, 184, 75, 255)
    GOLD_SOFT = (246, 223, 160, 255)
    TEXT_HI = (245, 247, 251, 255)
    TEXT_MID = (170, 178, 197, 255)
    TEXT_LOW = (106, 116, 136, 255)
    LINE = (255, 255, 255, 20)

    # ── شارة البطولة (مثل .badge) ──
    badge_font = _font(30, bold=True)
    if league:
        ls = _shape(league)
        ld = _text_direction(ls)
        lw = d.textlength(ls, font=badge_font, direction=ld)
        star_r = 17
        bw = lw + star_r * 2 + 20 + 90      # نص + نجمة + فجوة + حشوة (45+45)
        bx = W / 2 - bw / 2
        by = badge_y
        bh = badge_h
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh / 2,
                            fill=(232, 184, 75, 30), outline=(232, 184, 75, 90), width=2)
        # RTL: النجمة على يمين النص
        star_cx = bx + 45 + star_r
        text_x = star_cx + star_r + 20
        _draw_star(d, star_cx, by + bh / 2, star_r, GOLD)
        d.text((text_x, by + (bh - badge_font.size) / 2), ls, font=badge_font,
               fill=GOLD_SOFT, direction=ld)

    # ── صف الفريقين (RTL: المضيف يمين، الضيف يسار) ──
    home_logo = _load_team_logo(match.get('homeLogo'), home, league=league, size=LOGO)
    away_logo = _load_team_logo(match.get('awayLogo'), away, league=league, size=LOGO)
    for cx, lg in ((cx_home, home_logo), (cx_away, away_logo)):
        # دائرة بيضاء خلف اللوجو (مثل .team-logo-wrap)
        d.ellipse([cx - WRAP / 2, cy_logo - WRAP / 2, cx + WRAP / 2, cy_logo + WRAP / 2],
                  fill=(255, 255, 255, 255), outline=(255, 255, 255, 20), width=2)
        img.alpha_composite(lg, (int(cx - LOGO / 2), int(cy_logo - LOGO / 2)))
    d = ImageDraw.Draw(img, "RGBA")

    # أسماء الفرق + شريط لوني مميز (مثل .team-name / .team-accent)
    name_font = _font(36, bold=True)
    name_y = cy_logo + WRAP / 2 + 27
    _draw_centered(d, cx_home, name_y, home, name_font, TEXT_HI, 380)
    _draw_centered(d, cx_away, name_y, away, name_font, TEXT_HI, 380)
    hc = _team_color(home)
    ac = _team_color(away)
    accent_y = name_y + 50 - 9
    d.rounded_rectangle([cx_home - 50, accent_y, cx_home + 50, accent_y + 7], radius=4, fill=hc + (255,))
    d.rounded_rectangle([cx_away - 50, accent_y, cx_away + 50, accent_y + 7], radius=4, fill=ac + (255,))

    # ── لوحة النتيجة/الوقت (مثل .score-panel) ──
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
            # RTL: المضيف (يمين) نتيجته على اليمين والضيف (يسار) نتيجته على اليسار
            # العدد الأول = المضيف، الثاني = الضيف → نرسم الضيف يساراً والمضيف يميناً
            d.text((x0, baseline), parts[1], font=score_style, fill=TEXT_HI)
            d.text((x0 + w2, baseline + (score_style.size - dash.size) / 2), " – ", font=dash, fill=GOLD)
            d.text((x0 + w2 + wdash, baseline), parts[0], font=score_style, fill=TEXT_HI)
        else:
            _draw_centered(d, W // 2, py + 20, score_or_time, score_style, TEXT_HI, panel_w - 30)
    else:
        _draw_centered(d, W // 2, py + 18, score_or_time, _font(72, bold=True),
                       GOLD if not is_score else TEXT_HI, panel_w - 30)

    # ── شارة الحالة (مثل .status-pill) ──
    if status == "انتهت":
        st_color, st_bg, st_border = (5, 7, 13, 255), (34, 197, 94, 255), False
    elif status == "لم تبدأ":
        st_color, st_bg, st_border = (30, 22, 0, 255), (232, 184, 75, 255), False
    else:  # مباشر — حدود حمراء وخلفية شفافة
        st_color, st_bg, st_border = (239, 68, 68, 255), None, True
    st_cy = accent_y + 7 + 40 + 36
    _draw_status_pill(d, W // 2, st_cy, status or "—", st_color, st_bg, st_border)

    # ── فاصل (مثل .divider) ──
    div_y = st_cy + 36 + 45 + 4
    d.line([inner_x0, div_y, inner_x1, div_y], fill=LINE, width=1)

    # ── عنوان الهدافين (مثل .scorers-title) ──
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

    # ── شبكة الهدافين (مثل .scorers-grid) — عمودان بفاصل عمودي مركزي ──
    if kind == "end" and (hs or aw):
        grid_top = title_y + 44 + 31
        col_gap = 22
        div_x = W / 2
        col_w = (inner_x1 - inner_x0 - col_gap * 2 - 2) / 2
        x_home = inner_x1 - col_w          # عمود المضيف (يمين)
        x_away = inner_x0                  # عمود الضيف (يسار)

        # فاصل عمودي مركزي
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
                    # عمود الضيف: يبدأ من الحافة اليسرى، وترتيب RTL: كرة ثم اسم ثم شريحة
                    chip_left = cx0
                    nx = chip_left + mw + chip_pad * 2 + gap
                    name_x = nx
                    ball_cx = name_x + nw + gap + ball_r
                else:
                    # عمود المضيف: يلتصق بالحافة اليمنى، ترتيب RTL: كرة ثم اسم ثم شريحة
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

    # ── الشريط السفلي: القنوات (بدء المباراة فقط) ──
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
    """تنسيق القنوات كقائمة نقطية مرتبة (كل قناة في سطر) — أو رسالة إن لم تُحدد قناة."""
    ch = [c for c in (channels or []) if c]
    if not ch:
        return "📺 القنوات:\n• لم يتم تحديد قناة بعد"
    lines = ["📺 القنوات:"]
    for c in ch:
        lines.append(f"• {c}")
    return "\n".join(lines)


def _run_telegram_notifications(final_list, state):
    """تنبيه بدء المباراة + ملخص نهاية المباراة — كارت مصور احترافي (لوجو + النتيجة + الهدافون لكل فريق + القنوات)."""
    now = datetime.now(TZ)
    sent = []
    for m in final_list:
        key = "_".join(sorted([clean_name(m['homeTeam']), clean_name(m['awayTeam'])]))
        prev = state.get('prev_status', {}).get(key)
        status = m['status']
        state.setdefault('prev_status', {})[key] = status
        started = state.setdefault('started_notified', {})
        ended = state.setdefault('ended_notified', {})

        # ---- تنبيه بدء المباراة ----
        if TELEGRAM.get("send_start_alerts", True) and status == "لم تبدأ" and not started.get(key):
            time_str = m['scoreOrTime']
            if ':' in time_str and '-' not in time_str:
                try:
                    hm = time_str.replace('م', '').replace('ص', '').strip()
                    start_dt = datetime.combine(now.date(), datetime.strptime(hm, '%H:%M').time()).replace(tzinfo=TZ)
                    window = timedelta(minutes=TELEGRAM.get("start_alert_minutes", 15))
                    if now >= start_dt - window and now < start_dt:
                        caption = (f"🔔 تبدأ قريباً\n\n"
                                   f"🏆 {m['league']}\n"
                                   f"⚽ {m['homeTeam']} 🆚 {m['awayTeam']}\n"
                                   f"⏰ {m['scoreOrTime']}\n\n"
                                   f"{_format_channels(m['channels'])}")
                        card = compose_match_card(m, 'start')
                        ok = send_telegram_photo(card, caption) if card else False
                        if not ok:
                            text = (f"🔔 تبدأ قريباً\n\n"
                                    f"🏆 {m['league']}\n"
                                    f"⚽ {m['homeTeam']} 🆚 {m['awayTeam']}\n"
                                    f"⏰ {m['scoreOrTime']}\n\n"
                                    f"{_format_channels(m['channels'])}")
                            ok = send_telegram(text)
                        if ok:
                            started[key] = True
                            sent.append(f"start:{m['homeTeam']} vs {m['awayTeam']}")
                except Exception:
                    pass

        # ---- ملخص نهاية المباراة ----
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
                scorers = m.get('scorers') or {"home": [], "away": []}
                text = (f"🏁 انتهت المباراة\n\n"
                        f"🏆 {m['league']}\n"
                        f"⚽ {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']}\n")
                home_sc = scorers.get('home') or []
                away_sc = scorers.get('away') or []
                if home_sc or away_sc:
                    text += "\n⚽ الهدافون:\n"
                    if home_sc:
                        text += f"  {m['homeTeam']}: " + "، ".join(f"{n} {t}" for n, t in home_sc) + "\n"
                    if away_sc:
                        text += f"  {m['awayTeam']}: " + "، ".join(f"{n} {t}" for n, t in away_sc) + "\n"
                text += f"\n\n{_format_channels(m['channels'])}"
                ok = send_telegram(text)
            if ok:
                ended[key] = True
                sent.append(f"end:{m['homeTeam']} vs {m['awayTeam']}")

    if sent:
        print(f"    -> 📨 Telegram notifications sent: {len(sent)}")


# 💡 أداة الجراحة الجديدة: استخراج القنوات بالتعابير النمطية (Regex)
def extract_channels_with_regex(text):
    patterns = [
        r'(beIN\s*SPORTS(?:\s*(?:HD|MAX|Premium|Xtra|FR|EN|ES))?(?:\s*\d+)?)',
        r'(SSC(?:\s*SPORTS)?(?:\s*(?:HD|SD|Extra))?(?:\s*\d+)?)',
        r'(ON\s*Time\s*Sports(?:\s*\d+)?)',
        r'(On\s*Sport(?:\s*Plus)?)',
        r'(أبو\s*ظبي\s*الرياضية(?:\s*(?:HD|Premium))?(?:\s*\d+)?)',
        r'(أبوظبي\s*الرياضية(?:\s*(?:HD|Premium))?(?:\s*\d+)?)',
        r'(الكأس(?:\s*(?:HD|SD))?(?:\s*(?:One|Two|Three|Four|Five|\d+))?)',
        r'(الرابعة(?:\s*الرياضية)?)',
        r'(الرياضية\s*المغربية)',
        r'(السعودية\s*الرياضية)',
        r'(ثمانية\s*\d+)'
    ]
    found_channels = []
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        for match in matches:
            c = str(match).strip()
            if c and c not in found_channels:
                found_channels.append(c)
    return found_channels


def extract_btolat_channels(match_card):
    """قنوات بطولات تعيش في div.match-footer (أخ خارجي للـ match-card).
    النصوص داخل .sc-interp تشمل المعلقين أيضاً، لذلك نأخذ فقط ما تسبقه أيقونة تلفاز (rect)."""
    channels = []
    li = match_card.parent
    if not li:
        return channels
    footer = li.select_one('div.match-footer')
    if not footer:
        return channels
    for pill in footer.select('[data-dc-tpl="42"]'):
        for txt_span in pill.select('[data-dc-tpl="44"] .sc-interp'):
            holder = txt_span.parent
            prev_svg = holder.find_previous_sibling('svg')
            if prev_svg is not None and prev_svg.select_one('[data-dc-tpl="38"]'):
                name = txt_span.get_text(strip=True)
                if name and name not in channels:
                    channels.append(name)
    return channels


def extract_filgoal_scorers(html):
    """أهداف المباراة من صفحة فيلجول التفصيلية (/matches/{id}/coverage).
    نبحث عن كل قوائم ul#goalsHome_* / ul#goalsAway_* ونستخرج من كل li الاسم والدقيقة
    (تتفاوت بنية العناصر: الاسم قبل الدقيقة أو بعدها، وأحياناً الاسم نص عادي دون <a>)."""
    scorers = {"home": [], "away": []}
    soup = BeautifulSoup(html, 'html.parser')
    for side, prefix in (("home", "goalsHome"), ("away", "goalsAway")):
        for ul in soup.find_all('ul'):
            uid = ul.get('id') or ''
            if not uid.startswith(prefix):
                continue
            for li in ul.find_all('li'):
                if li.find('li'):
                    continue
                a = li.find('a')
                span = li.find('span')
                name = a.get_text(strip=True) if a else ""
                mnt = span.get_text(strip=True) if span else ""
                if not name:
                    txt = li.get_text(strip=True)
                    if mnt:
                        name = txt.replace(mnt, "").strip(" -–")
                    else:
                        mm = re.search(r'^(.*?)\s+(\d+\'?)\s*$', txt)
                        name = mm.group(1).strip() if mm else txt
                if not mnt:
                    mm = re.search(r"(\d+['’]?)", li.get_text())
                    mnt = mm.group(1) if mm else ""
                if name:
                    scorers[side].append((name, mnt))
    return scorers


def extract_btolat_scorers(html):
    """أهداف المباراة من صفحة تفاصيل بطولات (/matches/details/{id}).
    بنية الأهداف: <div class="getGoal"> <span class="goalTime clr2">57'</span>
    <span class="goalPlayer">اللاعب</span> </div> — أهداف الأرض داخل getGoalsTeamA والضيف داخل getGoalsTeamB."""
    scorers = {"home": [], "away": []}
    soup = BeautifulSoup(html, 'html.parser')
    for side, cls in (("home", "getGoalsTeamA"), ("away", "getGoalsTeamB")):
        cont = soup.find('div', class_=cls)
        if not cont:
            continue
        for g in cont.find_all('div', class_='getGoal'):
            name = g.find('span', class_='goalPlayer')
            mnt = g.find('span', class_='goalTime')
            n = name.get_text(strip=True) if name else ""
            mnt_s = mnt.get_text(strip=True) if mnt else ""
            if n:
                scorers[side].append((n, mnt_s))
    return scorers


# ================= دوال الاستخراج المساعدة =================
def extract_team_name(team_div):
    if not team_div: return ""
    strong_tag = team_div.find('strong')
    if strong_tag and strong_tag.text.strip(): return " ".join(strong_tag.text.split())
    p_tag = team_div.find('p')
    if p_tag and p_tag.text.strip(): return " ".join(p_tag.text.split())
    span_tag = team_div.find('span')
    if span_tag and span_tag.text.strip(): return " ".join(span_tag.text.split())
    text = " ".join(team_div.text.split())
    if text and not text.isdigit(): return text
    img = team_div.find('img')
    if img and img.get('alt'):
        alt_text = img.get('alt').strip()
        if alt_text and not alt_text.isdigit(): return alt_text
    return ""

def get_logo(img_tag, base_url=""):
    if not img_tag: return ""
    logo = img_tag.get('data-src') or img_tag.get('src', '')
    if logo.startswith('//'): logo = 'https:' + logo
    elif logo and not logo.startswith('http') and base_url: logo = base_url + logo
    return logo

def _norm_key(s):
    """تطبيع نص عربي/إنجليزي للمقارنة (تجاهل الفراغات والشرطات والهمزات)."""
    s = re.sub(r'[\s\-_ـ]+', '', s or '')
    return s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي').lower()


def _is_english_league(raw_league):
    """مباريات الدوري الإنجليزي (الممتاز + التشامبيونشيب يُسمّيان بنفس الاسم في المصادر)."""
    kws = LEAGUES_MAPPING.get("الدوري الإنجليزي", []) or ["إنجليزي", "بريميرليج", "انجلترا"]
    return any(kw in raw_league for kw in kws)


def _is_top_league_match(m, official_name):
    """هل المباراة بين ناديين من الدرجة الأولى لهذه البطولة؟

    المصادر تسمّي الدرجة الأولى والثانية بنفس الاسم (الدوري الإنجليزي/الإيطالي/...).
    إذا كانت البطولة لها قائمة بيضاء (TOP_LEAGUE_TEAMS) فكلاهما يجب أن يكونا من أنديتها؛
    وإلا تُقبل المباراة كما هي (لا توجد قائمة بيضاء للبطولة)."""
    whitelist = TOP_LEAGUE_TEAMS.get(official_name)
    if not whitelist:
        return True
    home, away = _norm_key(m['homeTeam']), _norm_key(m['awayTeam'])
    teams = [_norm_key(t) for t in whitelist]
    return (any(t and (t in home or home in t) for t in teams) and
            any(t and (t in away or away in t) for t in teams))


def _is_vip_candidate(m):
    """نفس منطق filter_and_rank للـ VIP — نستخدمه قبل جلب صفحات المباريات التفصيلية
    حتى لا نضيع طلبات على مباريات سيتم استبعادها أصلاً."""
    raw_league = m['league']
    # الكؤوس/البطولات العامة تُفحص أولاً — حتى لا تبتلعها مطابقة الدوري
    if any(v in raw_league for v in GENERAL_VIP_KEYWORDS):
        return True
    for official_name, keywords in LEAGUES_MAPPING.items():
        if any(kw in raw_league for kw in keywords):
            # البطولات ذات القوائم البيضاء (مثل الدوري الإنجليزي/الإيطالي): الدرجة الأولى فقط
            # لأن المصادر تسمّي الأولى والثانية بنفس الاسم
            if not _is_top_league_match(m, official_name):
                return False
            return True
    return any(t in m['homeTeam'] or t in m['awayTeam'] for t in VIP_TEAMS)


# ================= محرك التخفي والاتصال =================
class GhostScraper:
    def __init__(self):
        self.proxy_index = 0

    def _get_identity(self):
        session = requests.Session(impersonate=random.choice(BROWSERS))
        if PROXIES_LIST:
            if self.proxy_index >= len(PROXIES_LIST):
                self.proxy_index = 0
                return session, "Local IP"
            current_proxy = PROXIES_LIST[self.proxy_index]
            session.proxies = {"http": current_proxy, "https": current_proxy}
            self.proxy_index += 1
            return session, f"Proxy-{self.proxy_index}"
        return session, "Local IP"

    def fetch(self, url, source_name):
        session, ip_type = self._get_identity()
        time.sleep(random.uniform(GLOBAL_DELAY[0], GLOBAL_DELAY[1]))
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                return response.text
            print(f"    ⚠️ [{ip_type}] {source_name} blocked request (Status: {response.status_code})")
            return None
        except Exception as e:
            print(f"    ❌ [{ip_type}] Failed on {source_name}. Reason: {e}")
            return None

    # ================= يالاكورة =================
    def scrape_yalla(self, date_str):
        print(f"-> [Source 1] Yallakora ({date_str})...")
        # 💡 الحل الجذري لتغير روابط يلا كورة: توفير بديل في حال الفشل
        url = f"https://www.yallakora.com/match-center/?date={date_str}"
        html = self.fetch(url, "Yallakora (match-center)")
        if not html or 'matchCard' not in html:
            url = f"https://www.yallakora.com/matches-center?date={date_str}"
            html = self.fetch(url, "Yallakora (matches-center)")
            
        matches = []
        if not html: return matches

        soup = BeautifulSoup(html, 'html.parser')
        for card in soup.find_all('div', class_='matchCard'):
            league_tag = card.find('h2')
            league = " ".join(league_tag.text.split()) if league_tag else "بطولة غير معروفة"
            if any(b in league for b in BLOCKLIST): continue

            items = card.find_all(lambda tag: tag.name == 'div' and 'item' in tag.get('class', []))
            for item in items:
                try:
                    teams_data = item.find('div', class_='teamsData')
                    if not teams_data: continue

                    t_a = teams_data.find('div', class_='teamA')
                    t_b = teams_data.find('div', class_='teamB')
                    if not t_a or not t_b: continue

                    team1 = extract_team_name(t_a)
                    team2 = extract_team_name(t_b)
                    if not team1 or not team2: continue
                    logo1 = get_logo(t_a.find('img'))
                    logo2 = get_logo(t_b.find('img'))

                    score = "-:-"
                    mresult = teams_data.find('div', class_='MResult')
                    if mresult:
                        score_spans = mresult.find_all('span', class_='score')
                        time_span = mresult.find('span', class_='time')
                        if len(score_spans) >= 2 and score_spans[0].text.strip() not in ('-', ''):
                            score = f"{score_spans[0].text.strip()} - {score_spans[1].text.strip()}"
                        elif time_span:
                            score = time_span.text.strip()

                    status_tag = item.find('div', class_='matchStatus')
                    status = " ".join(status_tag.text.split()) if status_tag else "غير محدد"

                    ch_div = item.find('div', class_='channel')
                    channels = [c.strip() for c in ch_div.text.split('/') if c.strip()] if ch_div else []

                    comm_div = item.find('div', class_='icon-commentator')
                    comm = comm_div.parent.text.replace('معلق:', '').strip() if comm_div and comm_div.parent else ""

                    matches.append({
                        "league": league, "homeTeam": team1, "homeLogo": logo1,
                        "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                        "status": status, "channels": channels, "commentator": comm,
                        "source": "Yallakora"
                    })
                except Exception:
                    continue
        return matches

    # ================= فيلجول =================
    def _parse_filgoal_viewmodel(self, html):
        """استخراج نص JSON لمتغير viewModelData (يحوي TvCoverage) من صفحة المباراة."""
        m = re.search(r'var viewModelData\s*=\s*', html)
        if not m:
            return None
        start = m.end()
        depth, in_str, esc = 0, False, False
        for k in range(start, len(html)):
            ch = html[k]
            if in_str:
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == '{': depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return html[start:k + 1]
        return None

    def _fetch_filgoal_detail(self, match_id, status="", force=False):
        """القنوات والمعلقون والأهداف من صفحة المباراة التفصيلية (/coverage).
        مع كاش في filgoal_cache.json حتى لا نعيد الجلب كل 10 دقائق (توفير رصيد GitHub).
        نعيد الجلب فقط إذا انتهت صلاحية الكاش أو تغيّرت حالة المباراة (مثلاً انتهت → نحتاج الهدافين).
        force=True يتجاوز الكاش (يُستخدم في خطوة التعبئة اللاحقة للمباريات المنتهية)."""
        cached = FILGOAL_CACHE.get(match_id)
        now = time.time()
        if cached and not force and (now - cached.get('at', 0)) / 60.0 < FILGOAL_CACHE_TTL and cached.get('status') == status:
            return {
                "channels": list(cached.get('channels', [])),
                "commenters": list(cached.get('commenters', [])),
                "scorers": dict(cached.get('scorers', {"home": [], "away": []})),
            }
        url = f"https://www.filgoal.com/matches/{match_id}/coverage"
        html = self.fetch(url, f"FilGoal (match {match_id})")
        result = {"channels": [], "commenters": [], "scorers": {"home": [], "away": []}}
        if not html:
            if cached:
                result["channels"] = list(cached.get('channels', []))
                result["commenters"] = list(cached.get('commenters', []))
                result["scorers"] = dict(cached.get('scorers', {"home": [], "away": []}))
            return result
        try:
            raw = self._parse_filgoal_viewmodel(html)
            if raw:
                data = json.loads(raw)
                for tv in (data.get('TvCoverage') or []):
                    name = (tv.get('TvChannelName') or '').strip()
                    if name and name not in result["channels"]:
                        result["channels"].append(name)
                    comm = (tv.get('CommenterName') or '').strip()
                    if comm and comm not in result["commenters"]:
                        result["commenters"].append(comm)
        except Exception:
            pass
        result["scorers"] = extract_filgoal_scorers(html)
        FILGOAL_CACHE[match_id] = {
            "at": now, "status": status,
            "channels": result["channels"], "commenters": result["commenters"],
            "scorers": result["scorers"],
        }
        return result

    def _parse_filgoal_jsonld(self, html, seen):
        """مباريات اليوم الكاملة موجودة في JSON-LD — السلايدر لا يعرضها كلها (إنتر×بيتيس مثلًا).
        نحل رقم كل مباراة بربط أسماء الفريقين بروابط /matches/{id} في الصفحة."""
        links = {}
        for m in re.finditer(r'/matches/(\d+)/([^"\' ]+)', html):
            links.setdefault(m.group(1), m.group(2))
        events = []
        for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
            try:
                data = json.loads(m.group(1).strip())
            except Exception:
                continue
            stack = [data]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if node.get('@type') == 'SportsEvent':
                        events.append(node)
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
        for ev in events:
            home = (ev.get('homeTeam') or {}).get('name') or ''
            away = (ev.get('awayTeam') or {}).get('name') or ''
            if not home or not away:
                continue
            match_id = None
            for mid, slug in links.items():
                sn = _norm_key(slug)
                if _norm_key(home) in sn and _norm_key(away) in sn:
                    match_id = mid
                    break
            key = match_id if match_id else f"ld-{_norm_key(home)}_{_norm_key(away)}"
            if key in seen:
                continue
            league = ""
            desc = ev.get('description') or ev.get('name') or ''
            lm = re.search(r'في بطولة\s+(.+)', desc)
            if lm:
                league = " ".join(lm.group(1).split())
            if any(b in league for b in BLOCKLIST):
                continue
            start = ev.get('startDate') or ''
            time_str = start[11:16] if len(start) >= 16 else ""
            seen[key] = {
                "league": league, "homeTeam": home, "homeLogo": "",
                "awayTeam": away, "awayLogo": "", "scoreOrTime": time_str,
                "status": "لم تبدأ", "channels": [], "commentator": "",
                "source": "FilGoal", "_match_id": match_id
            }
        return seen

    def scrape_filgoal(self, date_str):
        print(f"-> [Source 2] FilGoal ({date_str})...")
        url = f"https://www.filgoal.com/matches/?date={date_str}"
        html = self.fetch(url, "FilGoal")
        if not html: return []

        soup = BeautifulSoup(html, 'html.parser')
        seen = {}  # ديدوب حسب data-match-id (الصفحة تعرض الكارت مرتين في بعض السلايدرات)
        for li in soup.find_all('li', class_='match-header-holder'):
            try:
                match_id = li.get('data-match-id')
                if not match_id or match_id in seen:
                    continue

                h6 = li.find('h6')
                league = " ".join(h6.text.split()) if h6 else "بطولة غير معروفة"
                if any(b in league for b in BLOCKLIST): continue

                home_b = li.find('b', class_='home-score')
                away_b = li.find('b', class_='away-score')
                if not home_b or not away_b: continue

                team1 = extract_team_name(home_b.parent)
                team2 = extract_team_name(away_b.parent)
                if not team1 or not team2: continue
                logo1 = get_logo(home_b.parent.find('img'))
                logo2 = get_logo(away_b.parent.find('img'))

                score1 = home_b.get_text(strip=True)
                score2 = away_b.get_text(strip=True)
                status_tag = li.find('span', class_='status')
                status = status_tag.text.strip() if status_tag else "غير محدد"

                if score1.isdigit() and score2.isdigit():
                    score = f"{score1} - {score2}"
                else:
                    time_tag = li.find('span', class_='time')
                    score = time_tag.text.strip() if time_tag and time_tag.text.strip() else "-:-"

                # 💡 استخدام الرادار الجديد لجلب القنوات والمعلقين من نصوص فيلجول
                full_text = li.text.replace('\n', ' ')
                channels = extract_channels_with_regex(full_text)
                
                comm = ""
                comm_match = re.search(r'(?:معلق|المعلق|بصوت)\s*:?\s*([أ-يa-zA-Z\s]+)', full_text)
                if comm_match:
                    c = comm_match.group(1).split('-')[0].split('|')[0].strip()
                    if len(c) < 30 and c not in ['غير محدد', 'لا يوجد']: comm = c

                if not comm:
                    for icon in li.find_all(['i', 'svg', 'img']):
                        icon_class = " ".join(icon.get('class', [])).lower()
                        if 'mic' in icon_class or 'commentator' in icon_class:
                            parent = icon.parent
                            if parent:
                                txt = parent.text.replace('معلق:', '').strip()
                                if txt and len(txt) < 30: comm = txt

                seen[match_id] = {
                    "league": league, "homeTeam": team1, "homeLogo": logo1,
                    "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                    "status": status, "channels": channels, "commentator": comm,
                    "source": "FilGoal", "_match_id": match_id
                }
            except Exception:
                continue

        # 💡 السلايدر لا يعرض كل مباريات اليوم (مثل إنتر×ريال بيتيس)
        # نكمل من JSON-LD (القائمة الكاملة) بربط الأسماء بأرقام المباريات
        self._parse_filgoal_jsonld(html, seen)

        # 💡 القنوات والمعلقون والأهداف من صفحة كل مباراة تفصيلية (/coverage)
        for m in seen.values():
            match_id = m.get('_match_id')
            if not match_id or not _is_vip_candidate(m):
                continue
            detail = self._fetch_filgoal_detail(match_id, status=m['status'])
            if detail['channels']:
                m['channels'] = dedup_channels([c for c in m['channels'] + detail['channels'] if c])
            if detail['commenters'] and not m['commentator']:
                m['commentator'] = ' / '.join(detail['commenters'])
            # الأهداف نهمها فقط للمباريات المنتهية (في بعض ids يعيد فيلجول مباراة قديمة منتهية)
            # لكن نحتفظ برقم المباراة دائماً حتى تعيد التعبئة اللاحقة جلب الأهداف بعد انتهائها
            if m['status'] == "انتهت":
                m['scorers'] = detail['scorers']
            m['_filgoal_id'] = match_id

        return list(seen.values())

    # ================= بطولات =================
    def scrape_btolat(self):
        print("-> [Source 3] Btolat...")
        # 💡 الحل الجذري لتغير روابط بطولات: توفير بديل في حال الفشل
        url = "https://www.btolat.com/matches"
        html = self.fetch(url, "Btolat (/matches)")
        if not html or 'match-card' not in html:
             url = "https://www.btolat.com/matches-score"
             html = self.fetch(url, "Btolat (/matches-score)")
             
        matches = []
        if not html: return matches

        soup = BeautifulSoup(html, 'html.parser')
        for m in soup.find_all('div', class_='match-card'):
            try:
                teams = m.find_all(lambda tag: tag.name == 'a' and 'team' in tag.get('class', []))
                if len(teams) < 2: continue

                team1 = extract_team_name(teams[0])
                team2 = extract_team_name(teams[1])
                if not team1 or not team2: continue
                logo1 = get_logo(teams[0].find('img'))
                logo2 = get_logo(teams[1].find('img'))

                score = "-:-"
                score_div = m.find('div', class_='scoreRresult')
                if score_div:
                    s1 = score_div.find('div', class_='team1Score')
                    s2 = score_div.find('div', class_='team2Score')
                    s1_text = s1.text.strip() if s1 else ""
                    s2_text = s2.text.strip() if s2 else ""
                    if s1_text or s2_text:
                        score = f"{s1_text or '0'} - {s2_text or '0'}"

                if score == "-:-":
                    time_tag = m.find('span', class_='match-time')
                    if time_tag and time_tag.text.strip():
                        score = time_tag.text.strip()

                status_tag = m.find('span', class_='status-badge')
                status = status_tag.text.strip() if status_tag else "غير محدد"

                league_card = m.find_parent('div', class_='mleague-card')
                league_tag = league_card.find(['h2', 'h3']) if league_card else None
                league = " ".join(league_tag.text.split()) if league_tag else "بطولة غير معروفة"

                # 💡 استخدام الرادار الجديد + الـ footer لبطولات (القنوات في أخ خارجي للمباراة)
                full_text = m.text.replace('\n', ' ')
                channels = dedup_channels(extract_btolat_channels(m) + extract_channels_with_regex(full_text))
                
                comm = ""
                comm_match = re.search(r'(?:معلق|المعلق|بصوت)\s*:?\s*([أ-يa-zA-Z\s]+)', full_text)
                if comm_match:
                    c = comm_match.group(1).split('-')[0].split('|')[0].strip()
                    if len(c) < 30 and c not in ['غير محدد', 'لا يوجد']: comm = c

                if not comm:
                    for icon in m.find_all(['i', 'svg', 'img']):
                        icon_class = " ".join(icon.get('class', [])).lower()
                        if 'mic' in icon_class or 'commentator' in icon_class:
                            parent = icon.parent
                            if parent:
                                txt = parent.text.replace('معلق:', '').strip()
                                if txt and len(txt) < 30: comm = txt

                # 💡 رابط صفحة التفاصيل لاستخراج أسماء الهدافين (المباريات المنتهية فقط)
                details_url = ""
                state_link = m.find('a', class_='match-state')
                if state_link and state_link.get('href'):
                    details_url = "https://www.btolat.com" + state_link['href']

                match_item = {
                    "league": league, "homeTeam": team1, "homeLogo": logo1,
                    "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                    "status": status, "channels": channels, "commentator": comm,
                    "source": "Btolat"
                }
                if details_url:
                    match_item["_btolat_details"] = details_url
                matches.append(match_item)
            except Exception:
                continue

        # 💡 أسماء الهدافين من صفحة تفاصيل بطولات (للمباريات المنتهية فقط — مثل فيلجول)
        for match_item in matches:
            du = match_item.pop('_btolat_details', None)
            if not du:
                continue
            if self._btolat_is_ended(match_item):
                match_item['scorers'] = self._fetch_btolat_scorers(du, match_item)
            # 💡 نحتفظ برابط التفاصيل دائماً (منتهية أو حيّة): إذا كانت المباراة حيّة لحظة المسح
            #    وبقيت الأهداف فارغة، خطوة التعبئة اللاحقة تعيد الجلب بعد انتقالها إلى "انتهت"
            match_item['_btolat_details'] = du
        return matches

    # ================= LiveSoccerTV (قنوات + مواعيد فقط) =================
    def scrape_livesoccertv(self):
        """مصدر رابع: جدول اليوم من LiveSoccerTV — قنوات ممتازة + مواعيد + حالة.
        لا يوفر النتيجة ولا الهدافين (صفحات التفاصيل محجوبة 403)، لذا نستخدمه للتكميل.
        أسماء الفرق/البطولات بالإنجليزية تُترجم إلى العربية حتى تندمج مع المصادر العربية."""
        print("-> [Source 4] LiveSoccerTV...")
        url = "https://www.livesoccertv.com/"
        html = self.fetch(url, "LiveSoccerTV (schedule)")
        matches = []
        if not html:
            return matches
        soup = BeautifulSoup(html, 'html.parser')
        for row in soup.select('tr.matchrow'):
            try:
                prev = row.find_previous('tr', class_='sortable_comp')
                league_raw = prev.get_text(strip=True) if prev else ""
                lname = league_raw.strip('▴ ›»').strip()
                if ' - ' in lname:
                    lname = lname.split(' - ', 1)[1]
                league = _ls_lookup(_LS_LEAGUE_EN_AR, lname)

                name_el = row.select_one('div.match-name-col a')
                title = name_el.get_text(strip=True) if name_el else ""
                parts = re.split(r'\s+vs\s+', title, flags=re.I)
                if len(parts) != 2:
                    continue
                h_ar = _ls_lookup(_LS_TEAM_EN_AR, parts[0].strip())
                a_ar = _ls_lookup(_LS_TEAM_EN_AR, parts[1].strip())
                if not h_ar or not a_ar:
                    continue

                # نحتفظ بالصف فقط إذا كان من بطولة VIP أو فيه فريق VIP (الباقي سيرفضه الفلتر)
                if not league and not (_is_vip_team_name(h_ar) or _is_vip_team_name(a_ar)):
                    continue

                ts_el = row.select_one('span.ts')
                time_str = ts_el.get_text(strip=True) if ts_el else ""
                inprog_el = row.select_one('span.inprogress')
                ip = inprog_el.get_text(strip=True) if inprog_el else ""
                if ip == 'FT':
                    status = 'انتهت'
                elif ip and 'live' not in ip.lower():
                    status = ip  # مثل "70'" أو "HT"
                else:
                    status = 'لم تبدأ'

                channels = []
                for a in row.select('div.mchannels a.homech'):
                    t = a.get_text(strip=True)
                    if t and t not in channels:
                        channels.append(t)

                matches.append({
                    "league": league or lname, "homeTeam": h_ar, "homeLogo": "",
                    "awayTeam": a_ar, "awayLogo": "", "scoreOrTime": time_str,
                    "status": status, "channels": dedup_channels(channels),
                    "commentator": "", "source": "LiveSoccerTV"
                })
            except Exception:
                continue
        return matches

    def _btolat_is_ended(self, m):
        st = (m.get('status') or '').strip()
        sc = m.get('scoreOrTime', '')
        return 'انتهت' in st or 'نهاية' in st or ('-' in sc and ':' not in sc)

    def _fetch_btolat_scorers(self, details_url, match_item, force=False):
        """أهداف المباراة من صفحة تفاصيل بطولات مع كاش محلي (TTL) لتوفير الطلبات.
        force=True يتجاوز الكاش (يُستخدم في خطوة التعبئة اللاحقة للمباريات المنتهية)."""
        cached = BTOLAT_DETAIL_CACHE.get(details_url)
        now = time.time()
        if cached and not force and (now - cached.get('at', 0)) / 60.0 < BTOLAT_DETAIL_TTL:
            return dict(cached.get('scorers', {"home": [], "away": []}))
        html = self.fetch(details_url, f"Btolat (details {details_url.rsplit('/', 1)[-1]})")
        scorers = extract_btolat_scorers(html) if html else {"home": [], "away": []}
        BTOLAT_DETAIL_CACHE[details_url] = {"at": now, "scorers": scorers}
        return scorers

# 💡 توحيد الاختلافات الشائعة في كتابة أسماء الفرق (نفس الفريق بصيغتين)
# ================= LiveSoccerTV: ترجمة أسماء البطولات/الفرق من الإنجليزية =================
# المفاتيح تُنظَّم عبر _norm_key (بدون فراغات/شرطات، أحرف صغيرة) عند البحث
_LS_LEAGUE_EN_AR = {
    "UEFA Champions League": "دوري أبطال أوروبا",
    "Champions League": "دوري أبطال أوروبا",
    "UEFA Europa League": "الدوري الأوروبي",
    "Europa League": "الدوري الأوروبي",
    "UEFA Conference League": "دوري المؤتمر الأوروبي",
    "Conference League": "دوري المؤتمر الأوروبي",
    "Premier League": "الدوري الإنجليزي",
    "EFL Championship": "الدوري الإنجليزي",
    "Championship": "الدوري الإنجليزي",
    "LaLiga": "الدوري الإسباني",
    "La Liga": "الدوري الإسباني",
    "Serie A": "الدوري الإيطالي",
    "Serie B": "الدوري الإيطالي",
    "Bundesliga": "الدوري الألماني",
    "2. Bundesliga": "الدوري الألماني",
    "Ligue 1": "الدوري الفرنسي",
    "Ligue 2": "الدوري الفرنسي",
    "Saudi Pro League": "الدوري السعودي",
    "Roshn Saudi League": "الدوري السعودي",
    "Saudi First Division": "الدوري السعودي",
    "Iraqi Premier League": "الدوري العراقي",
    "Iraq Stars League": "الدوري العراقي",
    "Egyptian Premier League": "الدوري المصري",
    "Botola Pro": "الدوري المغربي",
    "UAE Pro League": "الدوري الإماراتي",
    "Qatar Stars League": "الدوري القطري",
    "CAF Champions League": "دوري أبطال أفريقيا",
    "African Champions League": "دوري أبطال أفريقيا",
    "AFC Champions League": "دوري أبطال آسيا",
    "Asian Champions League": "دوري أبطال آسيا",
    "FIFA World Cup": "كأس العالم",
    "Copa America": "كوبا أمريكا",
    "African Cup of Nations": "كأس أمم أفريقيا",
    "European Championship": "كأس أمم أوروبا",
    "Club Friendly": "ودية",
    "Friendly": "ودية",
    "International Friendly": "ودية دولية",
    "Eredivisie": "الدوري الهولندي",
    "Primeira Liga": "الدوري البرتغالي",
    "Belgian Pro League": "الدوري البلجيكي",
    "Scottish Premiership": "الدوري الاسكتلندي",
    "Super Lig": "الدوري التركي",
    "Greek Super League": "الدوري اليوناني",
    "Brasileirao Serie A": "الدوري البرازيلي",
    "Copa Libertadores": "كوبا ليبرتادوريس",
    "FA Cup": "كأس الاتحاد الإنجليزي",
    "DFB-Pokal": "كأس ألمانيا",
    "Copa del Rey": "كأس إسبانيا",
    "Coppa Italia": "كأس إيطاليا",
}

_LS_TEAM_EN_AR = {
    # ===== أوروبا — أندية كبرى =====
    "Real Madrid": "ريال مدريد",
    "Real Madrid II": "ريال مدريد",
    "Barcelona": "برشلونة",
    "Atletico Madrid": "أتلتيكو",
    "Atlético Madrid": "أتلتيكو",
    "Athletic Bilbao": "أتلتيك بلباو",
    "Athletic Club": "أتلتيك بلباو",
    "Bayern Munich": "بايرن ميونيخ",
    "Bayern München": "بايرن ميونيخ",
    "Bayer Leverkusen": "باير ليفركوزن",
    "Borussia Dortmund": "بوروسيا دورتموند",
    "Dortmund": "بوروسيا دورتموند",
    "RB Leipzig": "لايبزيج",
    "Leipzig": "لايبزيج",
    "Paris Saint-Germain": "باريس سان جيرمان",
    "PSG": "باريس سان جيرمان",
    "Marseille": "أولمبيك مارسيليا",
    "Olympique Lyonnais": "أولمبيك ليون",
    "Lyon": "أولمبيك ليون",
    "Monaco": "موناكو",
    "Lille": "ليل",
    "Rennes": "رين",
    "Nice": "نيس",
    "Lens": "لانس",
    "Nantes": "نانت",
    "Toulouse": "تولوز",
    "Reims": "رانس",
    "Strasbourg": "ستراسبورغ",
    "Montpellier": "مونبلييه",
    "Brest": "بريست",
    "Auxerre": "أوكسير",
    "Le Havre": "لوهافر",
    "Angers": "أنجيه",
    "Saint-Etienne": "سانت إتيان",
    "Manchester City": "مانشستر سيتي",
    "Manchester United": "مانشستر يونايتد",
    "Liverpool": "ليفربول",
    "Arsenal": "أرسنال",
    "Chelsea": "تشيلسي",
    "Tottenham": "توتنهام",
    "Newcastle United": "نيوكاسل",
    "Aston Villa": "أستون فيلا",
    "West Ham United": "وست هام يونايتد",
    "Brighton": "برايتون",
    "Fulham": "فولهام",
    "Everton": "إيفرتون",
    "Wolves": "ولفرهامبتون",
    "Wolverhampton": "ولفرهامبتون",
    "Leicester": "ليستر سيتي",
    "Leeds": "ليدز",
    "Nottingham Forest": "نوتينغهام فورست",
    "Crystal Palace": "كريستال بالاس",
    "Brentford": "برينتفورد",
    "Bournemouth": "بورنموث",
    "Southampton": "ساوثهامبتون",
    "Ipswich": "إيبسويتش",
    "Juventus": "يوفنتوس",
    "AC Milan": "ميلان",
    "Milan": "ميلان",
    "Inter Milan": "إنتر ميلان",
    "AS Roma": "روما",
    "Roma": "روما",
    "Napoli": "نابولي",
    "Lazio": "لاتسيو",
    "Atalanta": "أتالانتا",
    "Fiorentina": "فيورنتينا",
    "Bologna": "بولونيا",
    "Genoa": "جنوى",
    "Udinese": "أودينيزي",
    "Torino": "تورينو",
    "Verona": "فيرونا",
    "Parma": "بارما",
    "Empoli": "إمبولي",
    "Como": "كومو",
    "Lecce": "ليتشي",
    "Cagliari": "كالياري",
    "Sassuolo": "ساسولو",
    "Sampdoria": "سامبدوريا",
    "Ajax": "أياكس",
    "PSV": "بي إس في",
    "Feyenoord": "فينورد",
    "NEC": "نيك",
    "Sporting CP": "سبورتينغ لشبونة",
    "Benfica": "بنفيكا",
    "Porto": "بورتو",
    "Anderlecht": "أندرلخت",
    "Club Brugge": "كلوب بروج",
    "Celtic": "سلتيك",
    "Rangers": "رينجرز",
    "Galatasaray": "غلطة سراي",
    "Fenerbahçe": "فنربخشة",
    "Fenerbahce": "فنربخشة",
    "Besiktas": "بشكتاش",
    "Olympiacos": "أولمبياكوس",
    "PAOK": "باوك",
    "AEK Athens": "أيك أثينا",
    "Panathinaikos": "باناثينايكوس",
    "Dinamo Zagreb": "دينامو زغرب",
    "Red Star Belgrade": "النجم الأحمر",
    "Shakhtar Donetsk": "شاختار دونيتسك",
    "Shakhtar": "شاختار دونيتسك",
    # ===== أندية عالمية =====
    "São Paulo": "ساو باولو",
    "Sao Paulo": "ساو باولو",
    "Flamengo": "فلامنغو",
    "Palmeiras": "بالميراس",
    "Corinthians": "كورينثيانز",
    "Fluminense": "فلومينينسي",
    "River Plate": "ريفر بليت",
    "Boca Juniors": "بوكا جونيورز",
    "Estudiantes": "إستوديانتيس",
    "Racing Club": "راسينغ",
    "Racing": "راسينغ",
    "Colo-Colo": "كولو كولو",
    "Penarol": "بينارول",
    "Nacional Montevideo": "ناسيونال مونتيفيديو",
    "Bolívar": "بوليفار",
    "Bolivar": "بوليفار",
    "LDU Quito": "ليغا دو كيتو",
    "Barcelona SC": "برشلونة الإكوادوري",
    "Independiente del Valle": "إنديبندينتي ديل فاليه",
    "Deportes Tolima": "ديبورتيس توليما",
    "Universidad Católica": "جامعة كاتوليكا",
    "Universidad Catolica": "جامعة كاتوليكا",
    # ===== سعودية =====
    "Al-Hilal": "الهلال",
    "Al-Nassr": "النصر",
    "Al-Ittihad": "الاتحاد",
    "Al-Ahli": "الأهلي",
    "Al-Shabab": "الشباب",
    "Al-Taawoun": "التعاون",
    "Al-Fateh": "الفتح",
    "Al-Ettifaq": "الاتفاق",
    "Al-Okhdood": "الأخدود",
    "Al-Khaleej": "الخليج",
    "Al-Qadsiah": "القادسية",
    "Al-Wehda": "الوحدة",
    "Al-Riyadh": "الرياض",
    "Al-Fayha": "الفيحاء",
    "Al-Kholood": "الخلود",
    "Al-Najma": "النجمة",
    "Al-Faisaly": "الفيصلي",
    "Al-Jabalain": "الجبلين",
    "Al-Raed": "الرائد",
    "Al-Tai": "الطائي",
    "Damac": "ضمك",
    "NEOM": "نيوم",
    "Al-Diriyah": "الدرعية",
    # ===== عراقية =====
    "Al-Zawraa": "الزوراء",
    "Al-Quwa Al-Jawiya": "القوة الجوية",
    "Al-Shorta": "الشرطة",
    "Al-Talaba": "الطلبة",
    "Erbil": "أربيل",
    "Al-Najaf": "النجف",
    "Al-Minaa": "الميناء",
    "Al-Karkh": "الكرخ",
    "Naft Al-Basra": "نفط البصرة",
    "Duhok": "دهوك",
    "Karbala": "كربلاء",
    "Al-Naft": "نفط",
    "Al-Hudood": "الحدود",
    "Al-Qasim": "القاسم",
    "Al-Diwaniya": "الديوانية",
    "Naft Maysan": "نفط ميسان",
    "Naft Al-Wasat": "نفط الوسط",
    "Al-Sinaa": "الصناعة",
    "Al-Kahrabaa": "الكهرباء",
    "Amanat Baghdad": "أمانة بغداد",
    "Zakho": "زاخو",
    "Newroz": "نوروز",
    # ===== مصرية =====
    "Al Ahly": "الأهلي",
    "Zamalek": "الزمالك",
    "Pyramids": "بيراميدز",
    "Ismaily": "الإسماعيلي",
    "Al Masry": "المصري",
    "El Gouna": "الجونة",
    "Ceramica Cleopatra": "سيراميكا كليوباترا",
    "Smouha": "سموحة",
    "Enppi": "إنبي",
    "Pharco": "فاركو",
    "Tala'a El Gaish": "طلائع الجيش",
    "Bank Al Ahly": "البنك الأهلي",
    "Al Mokawloon": "المقاولون العرب",
    "Haras El Hodood": "حرس الحدود",
    "Al Ittihad Alexandria": "الاتحاد السكندري",
    "Future": "مودرن فيوتشر",
    # ===== مغربية =====
    "Wydad": "الوداد",
    "Wydad AC": "الوداد",
    "Raja": "الرجاء",
    "Raja Casablanca": "الرجاء",
    "FAR Rabat": "الجيش الملكي",
    "RSB Berkane": "نهضة بركان",
    "Hassania Agadir": "حسنية أكادير",
    "Moghreb Tetouan": "المغرب التطواني",
    "Difaâ El Jadida": "الداخلة",
    "Olympic Safi": "أولمبيك أسفي",
    "Maghreb Fez": "المغرب الفاسي",
    # ===== تونسية =====
    "Esperance": "الترجي",
    "Esperance Tunis": "الترجي",
    "Espérance de Tunis": "الترجي",
    "Club Africain": "النادي الإفريقي",
    "Etoile du Sahel": "النجم الساحلي",
    "CS Sfaxien": "النادي الصفاقسي",
    "US Monastir": "اتحاد المنستير",
    "Stade Tunisien": "الملعب التونسي",
    # ===== جزائرية =====
    "MC Alger": "مولودية الجزائر",
    "USM Alger": "اتحاد الجزائر",
    "CR Belouizdad": "شباب بلوزداد",
    "ES Setif": "وفاق سطيف",
    "JS Kabylie": "شبيبة القبائل",
    "CS Constantine": "شباب قسنطينة",
    "JS Saoura": "شبيبة الساورة",
    "MC Oran": "مولودية وهران",
    # ===== إماراتية =====
    "Al Ain": "العين",
    "Al Wahda": "الوحدة",
    "Al Wasl": "الوصل",
    "Shabab Al Ahli": "شباب الأهلي",
    "Sharjah": "الشارقة",
    "Ajman": "عجمان",
    "Baniyas": "بن ياس",
    "Al Nasr Dubai": "النصر الإماراتي",
    "Al Jazira": "الجزيرة الإماراتي",
    "Al Bataeh": "البطائح",
    "Kalba": "كلباء",
    "Khor Fakkan": "خورفكان",
    "Al Dhafra": "الظفرة",
    # ===== قطرية =====
    "Al Sadd": "السد",
    "Al Duhail": "الدحيل",
    "Al Rayyan": "الريان",
    "Al Gharafa": "الغرافة",
    "Al Arabi": "العربي القطري",
    "Al Wakrah": "الوكرة",
    "Al Ahli Doha": "الأهلي القطري",
    "Umm Salal": "أم صلال",
    "Qatar SC": "قطر",
    "Al Shamal": "الشمال",
    "Al Markhiya": "المرخية",
    # ===== كويتية =====
    "Kuwait SC": "الكويت",
    "Al Qadsia": "القادسية الكويتي",
    "Al Arabi Kuwait": "العربي الكويتي",
    "Al Salmiya": "السالمية",
    "Al Fahaheel": "الفحيحيل",
    # ===== أردنية =====
    "Al Wehdat": "الوحدات",
    "Al Faisaly Jordan": "الفيصلي الأردني",
    "Al Hussein": "الحسين إربد",
    # ===== أخرى من الصفحات =====
    "Viking": "فايكنغ",
    "Levski Sofia": "ليفسكي صوفيا",
    "Persib": "برسيب",
    "Bali United": "بالي يونايتد",
    "Heidenheim": "هايدنهايم",
    "LASK Linz": "لاسك لينز",
    "Bodø / Glimt": "بودو غليمت",
    "Hapoel Be'er Sheva": "هبوعيل بئر السبع",
    "Sabah": "صباح",
    "Elche": "إلتشي",
    "Villarreal": "فياريال",
    "Real Betis": "ريال بيتيس",
    "Real Sociedad": "ريال سوسيداد",
    "Sevilla": "إشبيلية",
    "Valencia": "فالنسيا",
    "Girona": "جيرونا",
    "Getafe": "خيتافي",
    "Mallorca": "مايوركا",
    "Las Palmas": "لاس بالماس",
    "Osasuna": "أوساسونا",
    "Celta Vigo": "سيلتا فيغو",
    "Espanyol": "إسبانيول",
    "Rayo Vallecano": "رايو فاييكانو",
    "Leganes": "ليغانيس",
    "Alaves": "ألافيس",
    "Freiburg": "فرايبورغ",
    "Stuttgart": "شتوتغارت",
    "Hoffenheim": "هوفنهايم",
    "Mainz": "ماينز",
    "Werder Bremen": "فيردر بريمن",
    "Wolfsburg": "فولفسبورغ",
    "Borussia Monchengladbach": "بوروسيا مونشنغلادباخ",
    "Gladbach": "بوروسيا مونشنغلادباخ",
    "Augsburg": "أوغسبورغ",
    "Union Berlin": "يونيون برلين",
    "Koln": "كولن",
    "FC Koln": "كولن",
    "St. Pauli": "سانت باولي",
    "Eintracht Frankfurt": "آينتراخت فرانكفورت",
    "Hamburg": "هامبورغ",
    "Hertha Berlin": "هرتا برلين",
}


def _ls_lookup(mapping, name):
    """بحث في قواميس الترجمة: جرب الاسم كما هو ثم بصيغته المُنظَّمة (_norm_key)"""
    return mapping.get(name) or mapping.get(_norm_key(name))


def _is_vip_team_name(name):
    """هل اسم الفريق يطابق أحد فرق VIP؟ (نفس منطق filter_and_rank)"""
    return any(t in name for t in VIP_TEAMS)


_SPELLING_FIXES = {
    "بروسيا": "بوروسيا",
    "لايبزج": "لايبزيج",
    "ميونخ": "ميونيخ",
    "ميدلسبروه": "ميدلسبره",
    "إنتر ميلان": "إنتر",
    "النصر السعودي": "النصر",
    "اتحاد جدة": "الاتحاد",
    "شباب الأهلي دبي": "شباب الأهلي",
    "شالكه 04": "شالكه",
    "الميناء البصرة": "الميناء",
    "غاز الشمال": "Ghaz Al Shamal",
    "فايكينج": "فايكنغ",
    "فايكينغ": "فايكنغ",
    "فناربخشة": "فنربخشة",
    "آيك أثينا": "أيك أثينا",
    "سيلتك": "سلتيك",
    "نيميجين": "نيك",
    "نيميخن": "نيك",
    "هايدينهايم": "هايدنهايم",
    "بودو/جليمت": "بودو غليمت",
    "بودو / جليمت": "بودو غليمت",
}

# ================= دالة صناعة "بصمة الفريق" للدمج =================
def clean_name(name):
    name = name.strip()
    for src, dst in _SPELLING_FIXES.items():
        name = name.replace(src, dst)
    name = name.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي").replace("يي", "ي")
    for w in ["نادي", "فريق", "هوتسبر", "fc", "sc", "ديبورتيفو", "اتلتيكو", "ايه سي", "سي اف", "كلوب"]:
        name = name.lower().replace(w, "")
    return name.strip().replace(" ", "")

# ================= توحيد أسماء القنوات (عربي/إنجليزي) للدمج =================
def _channel_key(name):
    s = name.strip()
    s = s.replace('بى ان سبورت', 'beIN SPORTS').replace('بين سبورت', 'beIN SPORTS').replace('بي ان سبورت', 'beIN SPORTS').replace('بىن سبورت', 'beIN SPORTS')
    s = s.replace('اون سبورت', 'On Sport').replace('أون سبورت', 'On Sport')
    s = s.replace('أون تايم سبورتس', 'ON Time Sports').replace('اون تايم سبورتس', 'ON Time Sports')
    s = s.replace('أبو ظبي', 'أبوظبي').replace('ابو ظبي', 'أبوظبي').replace('ابوظبي', 'أبوظبي')
    s = s.replace('ماكس', 'MAX').replace('بلس', 'PLUS').replace('بريميوم', 'Premium')
    s = re.sub(r'\s*HD\s*$', '', s, flags=re.IGNORECASE)
    s = s.lower()
    return re.sub(r'\s+', '', s)

def _channel_priority(name):
    # الأسماء المكتوبة بالإنجليزية الأصيلة تُفضل على الترجمة العربية عند العرض
    return 0 if re.search(r'[a-zA-Z]', name) and not re.search(r'[\u0600-\u06ff]', name) else 1

# ================= فلتر القنوات: الشرق الأوسط وشمال أفريقيا فقط =================
# المصادر (خاصة LiveSoccerTV) تعيد قنوات عالمية (DAZN, Paramount+, CBS...) لا يريدها المستخدم.
# القاعدة: كل قناة عربية = MENA دائماً. القناة الإنجليزية مقبولة فقط إن كانت علامة معروفة
# في المنطقة (beIN / TOD / SSC / ON Time / OSN / Starzplay...) أو من قناة عربية إنجليزية الاسم
# (Abu Dhabi / Dubai / Alkass / Kuwait Sports...)؛ أي إنجليزية أخرى تُحذف.
_NON_MENA_CHANNELS_RE = re.compile(
    r'^(dazn|paramount|cbs|espn|skysports|skyitalia|skygermany|skysportde|'
    r'btsport|tntsports|supersport|elevensports|foxsports|nbcsports|univision|'
    r'telemundo|movistar|viaplay|rmcsport|canal\+|rtl|prosieben|starhub|'
    r'pptv|goltv|laligatv|premiersports|arenasport|sportklub|sportsnet|tsn|'
    r'televisa|azteca|beinsports?(fr|usa|us|au|aus|australia|es|spain|'
    r'de|germany|it|italy|uk|th|hk|malaysia|singapore|indonesia|turkey|latin|'
    r'brazil|mexico|argentina|india|pakistan|vietnam|japan|korea))'
)
_MENA_ENGLISH_CHANNELS = re.compile(
    r'^(bein|tod|ssc|stc|osn|starzplay|shahid|art|alkass|adsports|abudhabi|'
    r'dubai|ajj|ajsport|ontime|saudisport|kfsport|kuwaitsport|qatar|iraq|'
    r'jordan|mbc|nilesport|on\.?time|sportssaudi|sauditv)'
)


def _is_mena_channel(name):
    """هل القناة من الشرق الأوسط/شمال أفريقيا؟
    عربية دائماً نعم؛ إنجليزية فقط إذا كانت علامة معروفة في المنطقة (ولا تطابق قائمة أجنبية)."""
    if re.search(r'[\u0600-\u06ff]', name):
        return True
    k = _channel_key(name)
    if _NON_MENA_CHANNELS_RE.match(k):
        return False
    return bool(_MENA_ENGLISH_CHANNELS.match(k))

def dedup_channels(channels):
    seen, order = {}, []
    for c in channels:
        c = c.strip()
        if not c or not _is_mena_channel(c):
            continue
        k = _channel_key(c)
        if k in seen:
            if _channel_priority(c) < _channel_priority(seen[k]):
                seen[k] = c
            continue
        seen[k] = c
        order.append(k)
    return [seen[k] for k in order]

# ================= الفلترة والتوحيد والتصنيف الذكي =================
def filter_and_rank(matches_list):
    filtered = []
    for m in matches_list:
        raw_league = m['league']
        std_league = raw_league
        is_vip_league = False
        league_rank = 999 

        # أولاً: الكؤوس/البطولات العامة (مثل "كأس إيطاليا") — فحصها قبل البطولات
        # حتى لا تبتلعها مطابقة الدوري (مثال: "إيطالي" موجودة في "كأس إيطاليا").
        if any(v in raw_league for v in GENERAL_VIP_KEYWORDS):
            is_vip_league = True
            league_rank = 50
        else:
            for idx, (official_name, keywords) in enumerate(LEAGUES_MAPPING.items()):
                if any(kw in raw_league for kw in keywords):
                    std_league = official_name
                    is_vip_league = True
                    league_rank = idx  
                    break

        # البطولات ذات القوائم البيضاء: الدرجة الأولى فقط — المصادر تسمّي الأولى والثانية بنفس الاسم
        if is_vip_league and not _is_top_league_match(m, std_league):
            continue

        is_vip_team = False
        for t in VIP_TEAMS:
            if t in m['homeTeam'] or t in m['awayTeam']:
                is_vip_team = True
                break

        if is_vip_league or is_vip_team:
            m['league'] = std_league
            m['league_rank'] = league_rank if is_vip_league else 100
            m['team_rank'] = 0 if is_vip_team else 1
            filtered.append(m)

    filtered.sort(key=lambda x: (
        0 if "دقيقة" in x['status'] or "شوط" in x['status'] else 1, 
        x['league_rank'], 
        x['team_rank']
    ))

    for m in filtered:
        m.pop('league_rank', None)
        m.pop('team_rank', None)
        m.pop('priority', None)

    return filtered

# ================= دالة استخراج وقت أقرب مباراة للدرع الذكي =================
def extract_first_match_time(matches_list):
    earliest_time = None
    for m in matches_list:
        if m.get('status') == "انتهت": continue
        
        score_val = m.get('scoreOrTime', '')
        if ':' in score_val and '-' not in score_val:
            try:
                time_str = score_val.strip().replace('م', '').replace('ص', '').strip()
                match_time = datetime.strptime(time_str, '%H:%M').time()
                if earliest_time is None or match_time < earliest_time:
                    earliest_time = match_time
            except Exception:
                continue
    return earliest_time

# ================= العقل المدبر والتشغيل =================
scraper_engine = GhostScraper()

def _backfill_scorers(matches):
    """تعبئة الأهداف للمباريات المنتهية التي لم تصلنا أهدافها بعد (تأخر حالة المصدر لحظة
    المسح). نعيد جلب صفحة تفاصيل بطولات/فيلجول بتجاهل الكاش لأن حالة النهاية نهائية."""
    import random as _rnd
    for m in matches:
        sc = m.get('scorers') or {}
        if sc.get('home') or sc.get('away'):
            continue
        score = m.get('scoreOrTime', '')
        ended = m.get('status') == "انتهت" or ('-' in score and ':' not in score)
        if not ended:
            continue
        du = m.get('_btolat_details')
        if du:
            got = scraper_engine._fetch_btolat_scorers(du, m, force=True)
            if got.get('home') or got.get('away'):
                m['scorers'] = got
                continue
            time.sleep(_rnd.uniform(GLOBAL_DELAY[0], GLOBAL_DELAY[1]))
        fid = m.get('_filgoal_id') or m.get('_match_id')
        if fid:
            det = scraper_engine._fetch_filgoal_detail(fid, status=m.get('status'), force=True)
            if det['scorers'] and (det['scorers'].get('home') or det['scorers'].get('away')):
                m['scorers'] = det['scorers']


def execute_full_cycle():
    global FILGOAL_CACHE, BTOLAT_DETAIL_CACHE
    FILGOAL_CACHE = _load_filgoal_cache()
    BTOLAT_DETAIL_CACHE = _load_btolat_detail_cache()
    now = datetime.now(TZ)
    yalla_date = now.strftime('%m/%d/%Y')
    fil_date = now.strftime('%Y-%m-%d')

    today_str = yalla_date
    print(f"\n-> Fetching Matches for Date: {today_str}...")

    all_raw = []
    if SITES_CFG.get("yallakora", {}).get("enabled", True):
        yalla = scraper_engine.scrape_yalla(yalla_date)
        print(f"    -> يالاكورة: {len(yalla)} مباراة")
        all_raw += yalla
    if SITES_CFG.get("filgoal", {}).get("enabled", True):
        fil = scraper_engine.scrape_filgoal(fil_date)
        print(f"    -> فيلجول: {len(fil)} مباراة")
        all_raw += fil
    if SITES_CFG.get("btolat", {}).get("enabled", True):
        bto = scraper_engine.scrape_btolat()
        print(f"    -> بطولات: {len(bto)} مباراة")
        all_raw += bto
    if SITES_CFG.get("livesoccertv", {}).get("enabled", False):
        lsv = scraper_engine.scrape_livesoccertv()
        print(f"    -> لايف سوكر تي في: {len(lsv)} مباراة")
        all_raw += lsv

    print(f"\n-> [Debug] Total Raw Matches Extracted: {len(all_raw)}")

    merged = {}
    for m in all_raw:
        # 💡 مفتاح الدمج: زوج الفريقين مفرّزاً (ميلان×مانشستر = مانشستر×ميلان)
        home_key = clean_name(m['homeTeam'])
        away_key = clean_name(m['awayTeam'])
        key = "_".join(sorted([home_key, away_key]))
        
        if key not in merged:
            merged[key] = m
        else:
            # 1. دمج القنوات بذكاء (توحيد الصيغ العربية/الإنجليزية وإزالة التكرار)
            combined_channels = merged[key]['channels'] + m['channels']
            merged[key]['channels'] = dedup_channels(combined_channels)
            
            # 2. دمج المعلقين
            curr_comm = merged[key]['commentator']
            new_comm = m['commentator']
            if not curr_comm and new_comm:
                merged[key]['commentator'] = new_comm
            elif curr_comm and new_comm and new_comm not in curr_comm:
                merged[key]['commentator'] = f"{curr_comm} / {new_comm}"

            # 3. توثيق المصدر
            if m['source'] not in merged[key]['source']: 
                merged[key]['source'] += f" + {m['source']}"
                
            # 4. 💡 التحديث الشامل: نقل الشعارات المفقودة
            if not merged[key]['homeLogo'] and m['homeLogo']: merged[key]['homeLogo'] = m['homeLogo']
            if not merged[key]['awayLogo'] and m['awayLogo']: merged[key]['awayLogo'] = m['awayLogo']
            
            # 5. 💡 التحديث الشامل: إحلال النتيجة الحية بدلاً من وقت المباراة
            old_score = merged[key]['scoreOrTime']
            new_score = m['scoreOrTime']
            old_status = merged[key]['status']
            new_status = m['status']
            
            old_is_not_started = ('-' not in old_score and ':' in old_score) or old_status in ["لم تبدأ", "غير محدد", ""]
            new_is_live_or_done = ('-' in new_score and ':' not in new_score) or any(s in new_status for s in ['دقيقة', 'شوط', 'انتهت', 'نهاية'])
            
            if old_is_not_started and new_is_live_or_done:
                merged[key]['scoreOrTime'] = new_score
                merged[key]['status'] = new_status

            # 6. 💡 نقل الهدافين إن غابوا (للملخص النهائي في تيليجرام)
            merged_sc = merged[key].get('scorers') or {}
            m_sc = m.get('scorers') or {}
            if not (merged_sc.get('home') or merged_sc.get('away')) and (m_sc.get('home') or m_sc.get('away')):
                merged[key]['scorers'] = m_sc

            # 7. 💡 نقل مفاتيح التفاصيل الخاصة (رابط بطولات / رقم فيلجول)
            #    حتى تصل لخطوة التعبئة اللاحقة للأهداف لو بقيت فارغة
            for pk in ('_btolat_details', '_filgoal_id', '_match_id'):
                if not merged[key].get(pk) and m.get(pk):
                    merged[key][pk] = m[pk]

    final_list = filter_and_rank(list(merged.values()))

    # 💡 خطوة التعبئة اللاحقة: مباراة انتهت ولم تصلنا أهدافها (تأخر حالة بطولات مثلاً)
    #    نعيد جلب صفحة التفاصيل الآن — مع تجاهل الكاش الفارغ لأن النتيجة النهائية مستقرة
    _backfill_scorers(final_list)

    # 💡 إزالة المفاتيح الداخلية قبل الحفظ والإشعارات
    for m in final_list:
        m.pop('_btolat_details', None)
        m.pop('_filgoal_id', None)

    print("\n-> VIP Matches Extracted & Standardized:")
    if not final_list:
        print("   [No VIP matches found!]")
    else:
        for m in final_list:
            print(f"   ✅ [{m['league']}] {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']} | {m['status']} | {', '.join(m['channels'])}")

    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=4)

    print(f"\n-> [OK] Smart-Filtered & Saved {len(final_list)} matches to matches.json.")

    # 💡 إشعارات تيليجرام (بدء المباراة + ملخص النهاية بالهدافين) — تعتمد على الحالة المحفوظة
    state = _load_state()
    _run_telegram_notifications(final_list, state)
    _save_state(state)

    # 💡 حفظ كاش فيلجول لاستخدامه في الدورة القادمة
    _save_filgoal_cache()

    # 💡 حفظ كاش تفاصيل بطولات (أهداف المباريات المنتهية)
    _save_btolat_detail_cache()

    return final_list

if __name__ == "__main__":
    try:
        print("-> GitHub Actions Cycle Triggered...")
        now = datetime.now(TZ)
        
        is_midnight_sync = (now.hour == 0 or now.hour == 1 or not os.path.exists(MATCHES_FILE))
        
        if not is_midnight_sync:
            with open(MATCHES_FILE, "r", encoding="utf-8") as f:
                try:
                    saved_matches = json.load(f)
                    first_time = extract_first_match_time(saved_matches)
                    
                    if first_time:
                        match_dt = datetime.combine(now.date(), first_time).replace(tzinfo=TZ)
                        wake_dt = match_dt - timedelta(minutes=15)
                        
                        if now < wake_dt:
                            print(f"-> 🌙 أقرب مباراة ستكون الساعة {first_time}. الوقت لا يزال مبكراً.")
                            print(f"-> 💤 السكربت سيتوقف فوراً لتوفير رصيد GitHub. لن يتم سحب أي بيانات الآن.")
                            sys.exit(0)
                except Exception:
                    pass 
        
        execute_full_cycle()

    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\n🛑 System stopped by user.")
    except Exception as e:
        print(f"\n🛑 System stopped due to error: {e}")
