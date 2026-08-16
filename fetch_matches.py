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
def _load_config(path="config.json"):
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
FILGOAL_CACHE_FILE = "filgoal_cache.json"
FILGOAL_CACHE = {}

# ================= كاش تفاصيل بطولات (أهداف المباريات المنتهية) =================
BTOLAT_DETAIL_CACHE_FILE = "btolat_detail_cache.json"
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
STATE_FILE = "state.json"

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
                img.thumbnail((size, size), Image.LANCZOS)
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


def _draw_ball_icon(d, cx, cy, r, color):
    """كرة قدم بسيطة: دائرة ذهبية بحدود وخطوط — تُستخدم بدل إيموجي ⚽ (لا يُرسم بالخط العربي)."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 200), width=2)
    d.arc([cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7], 210, 330, fill=(255, 255, 255, 180), width=2)


def compose_match_card(match, kind="end"):
    """يرسم بطاقة المباراة الاحترافية (تصميم HTML زجاجي داكن) ويعيد بايتات PNG،
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
    # ارتفاع ثابت + مساحة الهدافين (عمود أطول عدد اسماء × ارتفاع الصف)
    scorer_rows = min(max(len(hs), len(aw), 0), 6)
    H = 620 if kind == "start" else 700 + max(0, scorer_rows) * 46
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # ── خلفية متدرجة داكنة (زجاجية) + توهج ذهبي مركزي ──
    top_c = (18, 24, 44)
    bot_c = (8, 11, 24)
    for y in range(H):
        t = y / H
        c = tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W / 2 - 380, -40, W / 2 + 380, -40 + 640], fill=(232, 184, 75, 22))
    gd.ellipse([-100, -80, 420, 560], fill=(59, 90, 180, 26))
    gd.ellipse([W - 420, -80, W + 100, 560], fill=(59, 90, 180, 26))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img, "RGBA")

    GOLD = (232, 184, 75, 255)
    GOLD_SOFT = (246, 223, 160, 255)
    WHITE = (245, 247, 251, 255)
    TEXT_MID = (170, 178, 197, 255)
    TEXT_LOW = (106, 116, 136, 255)
    LINE = (255, 255, 255, 22)

    # ── شارة نوع المباراة (اسم البطولة) أعلى البطاقة ──
    badge_font = _font(30, bold=True)
    if league:
        ls = _shape(league)
        ld = _text_direction(ls)
        lw = d.textlength(ls, font=badge_font, direction=ld)
        bw = lw + 64
        bx = W / 2 - bw / 2
        d.rounded_rectangle([bx, 30, bx + bw, 86], radius=28, fill=(232, 184, 75, 30), outline=(232, 184, 75, 90), width=2)
        # أيقونة نجمة ذهبية صغيرة يسار النص (بدل إيموجي 🏆)
        d.polygon([(bx + 36, 48), (bx + 42, 62), (bx + 57, 63), (bx + 45, 73), (bx + 49, 88),
                   (bx + 36, 80), (bx + 23, 88), (bx + 27, 73), (bx + 15, 63), (bx + 30, 62)], fill=GOLD)
        d.text((W / 2 - lw / 2 + 4, 44), ls, font=badge_font, fill=GOLD_SOFT, direction=ld)

    # ── صف الفريقين + النتيجة ──
    L = 170                       # حجم اللوجو
    cx_h, cx_a = 250, W - 250
    cy_logo = 250
    home_logo = _load_team_logo(match.get('homeLogo'), home, league=league, size=L)
    away_logo = _load_team_logo(match.get('awayLogo'), away, league=league, size=L)
    for cx, lg in ((cx_h, home_logo), (cx_a, away_logo)):
        # هالة/دائرة بيضاء خلف اللوجو (مثل .team-logo-wrap)
        ring = L + 24
        halo = Image.new("RGBA", (ring, ring), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        hd.ellipse([0, 0, ring, ring], fill=(255, 255, 255, 255), outline=(255, 255, 255, 20), width=2)
        img.alpha_composite(halo, (cx - ring // 2, cy_logo - ring // 2))
        img.alpha_composite(lg, (cx - L // 2, cy_logo - L // 2))

    # أسماء الفرق + شريط لوني مميز
    name_font = _font(34, bold=True)
    _draw_centered(d, cx_h, cy_logo + ring // 2 + 18, home, name_font, WHITE, 300)
    _draw_centered(d, cx_a, cy_logo + ring // 2 + 18, away, name_font, WHITE, 300)
    hc = _team_color(home)
    ac = _team_color(away)
    name_bot = cy_logo + ring // 2 + 18 + 52
    d.rounded_rectangle([cx_h - 34, name_bot, cx_h + 34, name_bot + 5], radius=3, fill=hc + (255,))
    d.rounded_rectangle([cx_a - 34, name_bot, cx_a + 34, name_bot + 5], radius=3, fill=ac + (255,))

    # ── لوحة النتيجة/الوقت المركزية ──
    panel_w, panel_h = 330, 128
    px, py = W / 2 - panel_w / 2, cy_logo - panel_h / 2
    d.rounded_rectangle([px, py, px + panel_w, py + panel_h], radius=20, fill=(255, 255, 255, 14),
                        outline=(232, 184, 75, 100), width=2)

    if kind == "end" and is_score:
        parts = [p.strip() for p in score_or_time.split('-')]
        score_style = _font(96, bold=True)
        if len(parts) == 2:
            w1 = d.textlength(parts[0], font=score_style)
            w2 = d.textlength(parts[1], font=score_style)
            dash = _font(70, bold=True)
            wdash = d.textlength(" – ", font=dash)
            total = w1 + w2 + wdash
            x0 = W / 2 - total / 2
            baseline = py + (panel_h - score_style.size) / 2 - 2
            d.text((x0, baseline), parts[0], font=score_style, fill=WHITE)
            d.text((x0 + w1, baseline + (score_style.size - dash.size) / 2), " – ", font=dash, fill=GOLD)
            d.text((x0 + w1 + wdash, baseline), parts[1], font=score_style, fill=WHITE)
        else:
            _draw_centered(d, W // 2, py + 16, score_or_time, score_style, WHITE, panel_w - 30)
    else:
        _draw_centered(d, W // 2, py + 14, score_or_time, _font(92, bold=True),
                       GOLD if not is_score else WHITE, panel_w - 30)

    # ── شارة الحالة (مثل .status-pill) ──
    if status == "انتهت":
        st_color, st_bg = (8, 26, 16, 255), (34, 197, 94, 255)
    elif status == "لم تبدأ":
        st_color, st_bg = (30, 22, 0, 255), (232, 184, 75, 255)
    else:  # مباشر — حدود حمراء وخلفية شفافة
        st_color, st_bg = (239, 68, 68, 255), None
    st_y = name_bot + 24
    _draw_badge(d, W // 2, st_y, status or "—", _font(26, bold=True), st_color, st_bg)

    # ── الهدافون (للملخص النهائي فقط) ──
    if kind == "end":
        y_sep = st_y + 40
        d.line([70, y_sep, W - 70, y_sep], fill=LINE, width=2)
        # عنوان "الهدافون" ذهبي
        _draw_centered(d, W // 2, y_sep + 16, "الهدافون", _font(30, bold=True), GOLD_SOFT, 300)

        if hs or aw:
            col_top = y_sep + 64
            # عمودا الهدافين: أيمن تحت الفريق الأيمن، أيسر تحت الفريق الأيسر
            # أعمدة متساوية العرض بفاصل عمودي مركزي
            col_w = 470
            col_h_x = W / 2 - 40 - col_w      # عمود الفريق المضيف (يسار البطاقة RTL)
            col_a_x = W / 2 + 40              # عمود الفريق الضيف (يمين البطاقة)
            # أسماء الأعمدة بلون الفريق
            hf = _font(26, bold=True)
            _draw_centered(d, col_h_x + col_w / 2, col_top, home, hf, hc + (255,), col_w)
            _draw_centered(d, col_a_x + col_w / 2, col_top, away, hf, ac + (255,), col_w)
            # فاصل عمودي مركزي
            div_y1 = col_top - 4
            div_y2 = col_top + 6 + max(len(hs), len(aw), 1) * 46
            d.line([W / 2, div_y1, W / 2, div_y2], fill=(255, 255, 255, 30), width=2)

            scorer_font = _font(26)
            minute_font = _font(21, bold=True)
            for cx0, team, lst, is_away in ((col_h_x, home, hs, False), (col_a_x, away, aw, True)):
                iy = col_top + 46
                for name, minute in lst[:6]:
                    # محاذاة الأسماء: الفريق المضيف إلى اليمين (بداية من يمين عموده)،
                    # والضيف إلى اليسار — ليتقابل الخطان نحو الفاصل المركزي.
                    if is_away:
                        x_start = cx0
                    else:
                        x_start = cx0 + col_w
                    sn = _shape(name)
                    snd = _text_direction(sn)
                    nw = d.textlength(sn, font=scorer_font, direction=snd)
                    # دائرة كرة ذهبية قبل الاسم
                    ball_r = 11
                    if is_away:
                        bx = x_start + ball_r + 6
                    else:
                        bx = x_start - ball_r - 6
                    _draw_ball_icon(d, bx, iy, ball_r, GOLD)
                    # دقيقة في شريحة صغيرة بجانب الاسم
                    mtxt = _shape(str(minute))
                    md = _text_direction(mtxt)
                    mw = d.textlength(mtxt, font=minute_font, direction=md)
                    chip_pad = 10
                    if is_away:
                        # الاسم ثم الشريحة بعدها (يميناً لليسار)
                        nx = bx + ball_r + 10
                        name_top = iy - scorer_font.size / 2
                        d.text((nx, name_top), sn, font=scorer_font, fill=WHITE, direction=snd)
                        cx_chip = nx + nw + chip_pad + mw / 2
                        d.rounded_rectangle([cx_chip - mw / 2 - chip_pad, iy - 18, cx_chip + mw / 2 + chip_pad, iy + 18],
                                            radius=9, fill=(255, 255, 255, 14))
                        d.text((cx_chip - mw / 2, name_top + (scorer_font.size - minute_font.size) / 2),
                               mtxt, font=minute_font, fill=TEXT_LOW, direction=md)
                    else:
                        # الشريحة ثم الاسم (يساراً لليمين نحو الفاصل)
                        cx_chip = bx - ball_r - 10 - mw / 2
                        d.rounded_rectangle([cx_chip - mw / 2 - chip_pad, iy - 18, cx_chip + mw / 2 + chip_pad, iy + 18],
                                            radius=9, fill=(255, 255, 255, 14))
                        name_top = iy - scorer_font.size / 2
                        d.text((cx_chip - mw / 2, name_top + (scorer_font.size - minute_font.size) / 2),
                               mtxt, font=minute_font, fill=TEXT_LOW, direction=md)
                        d.text((cx_chip + mw / 2 + chip_pad, name_top), sn, font=scorer_font, fill=WHITE, direction=snd)
                    iy += 46
                if len(lst) > 6:
                    _draw_centered(d, cx0 + col_w / 2, iy, f"+{len(lst) - 6}", _font(22), TEXT_MID, 100)
        else:
            _draw_centered(d, W // 2, y_sep + 62, "لا توجد أهداف مسجّلة", _font(26), TEXT_LOW, 500)

    # ── الشريط السفلي: القنوات (بدء المباراة فقط) ──
    if kind == "start":
        ch_text = " • ".join(channels) if channels else "لم يتم تحديد قناة بعد"
        ch_font = _font(30, bold=True)
        ch_lines = _wrap_lines(d, ch_text, ch_font, W - 300)
        bar_h = max(92, 26 + len(ch_lines) * 44)
        bar_y = H - bar_h - 16
        d.rounded_rectangle([40, bar_y, W - 40, H - 12], radius=20, fill=(18, 26, 54, 235), outline=(60, 80, 140, 255), width=2)
        _draw_tv_icon(d, 120, bar_y + bar_h / 2 - 6, GOLD)
        if channels:
            _draw_right(d, W - 70, bar_y + 16, ch_text, ch_font, WHITE, W - 300)
        else:
            _draw_right(d, W - 70, bar_y + 16, ch_text, ch_font, (255, 150, 80, 255), W - 300)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
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
    بنية أهداف الأرض: <a>اللاعب</a> <span>الدقيقة</span> (والضيف بالعكس) — نستخرج الاثنين معاً."""
    scorers = {"home": [], "away": []}
    for side in ("home", "away"):
        for ul in re.finditer(r'<ul id="goals' + side.title() + r'_\d+"[^>]*>(.*?)</ul>', html, re.S):
            for li in re.finditer(r'<li[^>]*>(.*?)</li>', ul.group(1), re.S):
                name = re.search(r'<a[^>]*>([^<]+)</a>', li.group(1))
                minute = re.search(r'<span>\s*([^<]+)</span>', li.group(1))
                if name:
                    n = name.group(1).strip()
                    mnt = minute.group(1).strip() if minute else ""
                    scorers[side].append((n, mnt))
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

    def _fetch_filgoal_detail(self, match_id, status=""):
        """القنوات والمعلقون والأهداف من صفحة المباراة التفصيلية (/coverage).
        مع كاش في filgoal_cache.json حتى لا نعيد الجلب كل 10 دقائق (توفير رصيد GitHub).
        نعيد الجلب فقط إذا انتهت صلاحية الكاش أو تغيّرت حالة المباراة (مثلاً انتهت → نحتاج الهدافين)."""
        cached = FILGOAL_CACHE.get(match_id)
        now = time.time()
        if cached and (now - cached.get('at', 0)) / 60.0 < FILGOAL_CACHE_TTL and cached.get('status') == status:
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
            match_id = m.pop('_match_id', None)
            if not match_id or not _is_vip_candidate(m):
                continue
            detail = self._fetch_filgoal_detail(match_id, status=m['status'])
            if detail['channels']:
                m['channels'] = dedup_channels([c for c in m['channels'] + detail['channels'] if c])
            if detail['commenters'] and not m['commentator']:
                m['commentator'] = ' / '.join(detail['commenters'])
            # الأهداف نهمها فقط للمباريات المنتهية (في لبعض ids يعيد فيلجول مباراة قديمة منتهية)
            if m['status'] == "انتهت":
                m['scorers'] = detail['scorers']

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
            if not du or not self._btolat_is_ended(match_item):
                continue
            match_item['scorers'] = self._fetch_btolat_scorers(du, match_item)
        return matches

    def _btolat_is_ended(self, m):
        st = (m.get('status') or '').strip()
        sc = m.get('scoreOrTime', '')
        return 'انتهت' in st or 'نهاية' in st or ('-' in sc and ':' not in sc)

    def _fetch_btolat_scorers(self, details_url, match_item):
        """أهداف المباراة من صفحة تفاصيل بطولات مع كاش محلي (TTL) لتوفير الطلبات."""
        cached = BTOLAT_DETAIL_CACHE.get(details_url)
        now = time.time()
        if cached and (now - cached.get('at', 0)) / 60.0 < BTOLAT_DETAIL_TTL:
            return dict(cached.get('scorers', {"home": [], "away": []}))
        html = self.fetch(details_url, f"Btolat (details {details_url.rsplit('/', 1)[-1]})")
        scorers = extract_btolat_scorers(html) if html else {"home": [], "away": []}
        BTOLAT_DETAIL_CACHE[details_url] = {"at": now, "scorers": scorers}
        return scorers

# 💡 توحيد الاختلافات الشائعة في كتابة أسماء الفرق (نفس الفريق بصيغتين)
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

def dedup_channels(channels):
    seen, order = {}, []
    for c in channels:
        c = c.strip()
        if not c:
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

    final_list = filter_and_rank(list(merged.values()))

    print("\n-> VIP Matches Extracted & Standardized:")
    if not final_list:
        print("   [No VIP matches found!]")
    else:
        for m in final_list:
            print(f"   ✅ [{m['league']}] {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']} | {m['status']} | {', '.join(m['channels'])}")

    with open("matches.json", "w", encoding="utf-8") as f:
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
        
        is_midnight_sync = (now.hour == 0 or now.hour == 1 or not os.path.exists("matches.json"))
        
        if not is_midnight_sync:
            with open("matches.json", "r", encoding="utf-8") as f:
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
