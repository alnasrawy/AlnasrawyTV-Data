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

TELEGRAM = _CFG.get("telegram", {}) or {}
SITES_CFG = _CFG.get("sites", {}) or {}
GLOBAL_DELAY = _CFG.get("global_delay", [1.0, 2.0]) or [1.0, 2.0]
FILGOAL_CACHE_TTL = float(_CFG.get("filgoal_cache_ttl_minutes", 30))

# ================= كاش فيلجول (يُحفظ في filgoal_cache.json ويعاد رفعه في كل دورة) =================
FILGOAL_CACHE_FILE = "filgoal_cache.json"
FILGOAL_CACHE = {}

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
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat, "caption": caption},
            files={"photo": ("match_card.png", png_bytes, "image/png")},
            timeout=60,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"    ❌ Telegram sendPhoto failed: {e}")
        return False


# ================= مولّد بطاقة المباراة (صورة احترافية) =================
_FONT_CACHE = {}
_LOGO_CACHE = {}

_ARABIC_FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Regular.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal/Tajawal-Bold.ttf",
]

_SYSTEM_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _font_path(kind):
    p = os.path.join(tempfile.gettempdir(), f"card_font_{kind}.ttf")
    if os.path.exists(p) and os.path.getsize(p) > 5000:
        return p
    url = _ARABIC_FONT_URLS[0 if kind == "regular" else 1]
    try:
        r = requests.get(url, timeout=20, impersonate="chrome120")
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
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _shape(text):
    """إعادة تشكيل النص العربي + الاتجاه من اليمين لليسار للعرض الصحيح داخل الصورة."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)


def _draw_centered(draw, cx, y, text, font, fill, max_w):
    s = _shape(text)
    w = draw.textlength(s, font=font)
    if w <= max_w:
        draw.text((cx - w / 2, y), s, font=font, fill=fill)
        return
    words = s.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=font)
        draw.text((cx - lw / 2, y + i * (font.size + 6)), ln, font=font, fill=fill)


def _draw_right(draw, xr, y, text, font, fill, max_w):
    s = _shape(text)
    w = draw.textlength(s, font=font)
    if w <= max_w:
        draw.text((xr - w, y), s, font=font, fill=fill)
        return
    words = s.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=font)
        draw.text((xr - lw, y + i * (font.size + 6)), ln, font=font, fill=fill)


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


def _load_team_logo(url, team_name, size=210):
    """تحميل لوجو الفريق من رابط المسح، وإن فشل نرسم دائرة ملونة بأول حرف من اسم الفريق."""
    key = (url, team_name, size)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    img = None
    if url:
        try:
            r = requests.get(url, timeout=15, impersonate="chrome120",
                             headers={"Referer": "https://www.filgoal.com/"})
            if r.status_code == 200 and len(r.content) > 100:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
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
        lw = d.textlength(letter, font=f)
        d.text(((size - lw) / 2, (size - f.size) / 2), letter, font=f, fill=(255, 255, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    canvas.putalpha(mask)
    _LOGO_CACHE[key] = canvas
    return canvas


def compose_match_card(match, kind="end"):
    """يرسم بطاقة المباراة الاحترافية ويعيد بايتات PNG، أو None عند فشل الرسم.
    kind: 'start' (تنبيه بدء) أو 'end' (ملخص نهاية مع الهدافين)."""
    if Image is None or ImageDraw is None:
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
    n_lines = max(len(hs), len(aw), 1)
    H = (680 + min(n_lines, 6) * 52) if kind == "end" else 540
    W = 1080
    img = Image.new("RGBA", (W, H), (13, 18, 42, 255))
    d = ImageDraw.Draw(img, "RGBA")

    # خلفية متدرجة داكنة
    top_c = (24, 34, 68)
    bot_c = (10, 13, 30)
    for y in range(H):
        t = y / H
        c = tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)

    GOLD = (245, 197, 66, 255)
    WHITE = (255, 255, 255, 255)
    MUTED = (170, 180, 210, 255)
    RED = (255, 120, 120, 255)
    GREEN = (80, 220, 150, 255)

    # شريط ذهبي علوي
    d.rectangle([0, 0, W, 10], fill=GOLD)

    # اسم البطولة
    _draw_centered(d, W // 2, 30, league, _font(42, bold=True), GOLD, W - 120)

    # المنتصف: لوجو أرض | النتيجة/الوقت | لوجو ضيف
    cx_h, cx_a = 240, W - 240
    cy_mid = 210
    home_logo = _load_team_logo(match.get('homeLogo'), home)
    away_logo = _load_team_logo(match.get('awayLogo'), away)
    img.alpha_composite(home_logo, (cx_h - home_logo.width // 2, cy_mid - home_logo.height // 2))
    img.alpha_composite(away_logo, (cx_a - away_logo.width // 2, cy_mid - away_logo.height // 2))

    center_txt = score_or_time if kind == "start" or not is_score else score_or_time
    if kind == "end" and is_score:
        parts = [p.strip() for p in score_or_time.split('-')]
        score_style = _font(120, bold=True)
        if len(parts) == 2:
            w1 = d.textlength(parts[0], font=score_style)
            w2 = d.textlength(parts[1], font=score_style)
            dash = _font(90, bold=True)
            wdash = d.textlength(" – ", font=dash)
            total = w1 + w2 + wdash
            x0 = W / 2 - total / 2
            d.text((x0, cy_mid - 64), parts[0], font=score_style, fill=WHITE)
            d.text((x0 + w1, cy_mid - 46), " – ", font=dash, fill=GOLD)
            d.text((x0 + w1 + wdash, cy_mid - 64), parts[1], font=score_style, fill=WHITE)
        else:
            _draw_centered(d, W // 2, cy_mid - 64, score_or_time, score_style, WHITE, 400)
    else:
        _draw_centered(d, W // 2, cy_mid - 60, score_or_time, _font(110, bold=True),
                       GOLD if not is_score else WHITE, 420)

    # أسماء الفرق أسفل اللوجوهات (في المنتصف لكل عمود)
    _draw_centered(d, cx_h, cy_mid + 118, home, _font(36, bold=True), WHITE, 300)
    _draw_centered(d, cx_a, cy_mid + 118, away, _font(36, bold=True), WHITE, 300)

    # شارة الحالة
    st_color = GREEN if status == "انتهت" else (GOLD if status == "لم تبدأ" else (255, 180, 90, 255))
    _draw_centered(d, W // 2, cy_mid + 168, status, _font(28, bold=True), st_color, 400)

    # أقسام الهدافين (للملخص النهائي فقط): كل فريق وهدافيه منفصلين
    y_sc = cy_mid + 215
    if kind == "end" and (hs or aw):
        d.line([60, y_sc - 6, W - 60, y_sc - 6], fill=(60, 80, 140, 255), width=2)
        _draw_centered(d, W // 2, y_sc, "الهدافون", _font(34, bold=True), GOLD, 300)
        y_col = y_sc + 52
        for side, cx, team, lst in (("home", 300, home, hs), ("away", W - 300, away, aw)):
            _draw_centered(d, cx, y_col, team, _font(30, bold=True), GOLD, 420)
            iy = y_col + 46
            for name, minute in lst[:6]:
                line = f"• {name}  {minute}"
                _draw_centered(d, cx, iy, line, _font(28), WHITE, 440)
                iy += 44
            if len(lst) > 6:
                _draw_centered(d, cx, iy, f"+{len(lst) - 6}", _font(26), MUTED, 100)

    # الشريط السفلي: أيقونة الشاشة + القنوات (أو رسالة إن لم تُحدد قناة)
    bar_y = H - 110
    d.rounded_rectangle([40, bar_y, W - 40, H - 20], radius=18, fill=(18, 26, 54, 235), outline=(60, 80, 140, 255), width=2)
    _draw_tv_icon(d, 120, bar_y + 45, GOLD)
    if channels:
        _draw_right(d, W - 70, bar_y + 22, " • ".join(channels), _font(32, bold=True), WHITE, W - 300)
    else:
        _draw_right(d, W - 70, bar_y + 22, "لم يتم تحديد قناة بعد", _font(32, bold=True), (255, 150, 80, 255), W - 300)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


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
                        caption = f"🔔 تبدأ قريباً | {m['league']}"
                        card = compose_match_card(m, 'start')
                        ok = send_telegram_photo(card, caption) if card else False
                        if not ok:
                            text = (f"🔔 تبدأ قريباً\n\n"
                                    f"🏆 {m['league']}\n"
                                    f"{m['homeTeam']} 🆚 {m['awayTeam']}\n"
                                    f"⏰ {m['scoreOrTime']}\n"
                                    f"📺 {', '.join(m['channels']) or 'لم يتم تحديد قناة بعد'}")
                            ok = send_telegram(text)
                        if ok:
                            started[key] = True
                            sent.append(f"start:{m['homeTeam']} vs {m['awayTeam']}")
                except Exception:
                    pass

        # ---- ملخص نهاية المباراة ----
        if TELEGRAM.get("send_end_summary", True) and status == "انتهت" and not ended.get(key) and prev != "انتهت":
            caption = f"🏁 انتهت المباراة | {m['league']}"
            card = compose_match_card(m, 'end')
            ok = send_telegram_photo(card, caption) if card else False
            if not ok:
                scorers = m.get('scorers') or {"home": [], "away": []}
                text = (f"🏁 انتهت المباراة\n\n"
                        f"🏆 {m['league']}\n"
                        f"{m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']}\n")
                home_sc = scorers.get('home') or []
                away_sc = scorers.get('away') or []
                if home_sc or away_sc:
                    text += "\n⚽ الهدافون:\n"
                    if home_sc:
                        text += f"  {m['homeTeam']}: " + "، ".join(f"{n} {t}" for n, t in home_sc) + "\n"
                    if away_sc:
                        text += f"  {m['awayTeam']}: " + "، ".join(f"{n} {t}" for n, t in away_sc) + "\n"
                text += f"\n📺 {', '.join(m['channels']) or 'لم يتم تحديد قناة بعد'}"
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
    s = re.sub(r'[\s\-_]+', '', s or '')
    return s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي').lower()


def _is_vip_candidate(m):
    """نفس منطق filter_and_rank للـ VIP — نستخدمه قبل جلب صفحات المباريات التفصيلية
    حتى لا نضيع طلبات على مباريات سيتم استبعادها أصلاً."""
    raw_league = m['league']
    for keywords in LEAGUES_MAPPING.values():
        if any(kw in raw_league for kw in keywords):
            return True
    if any(v in raw_league for v in GENERAL_VIP_KEYWORDS):
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

                matches.append({
                    "league": league, "homeTeam": team1, "homeLogo": logo1,
                    "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                    "status": status, "channels": channels, "commentator": comm,
                    "source": "Btolat"
                })
            except Exception:
                continue
        return matches

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

        for idx, (official_name, keywords) in enumerate(LEAGUES_MAPPING.items()):
            if any(kw in raw_league for kw in keywords):
                std_league = official_name
                is_vip_league = True
                league_rank = idx  
                break

        if not is_vip_league:
            if any(v in raw_league for v in GENERAL_VIP_KEYWORDS):
                is_vip_league = True
                league_rank = 50  

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
    global FILGOAL_CACHE
    FILGOAL_CACHE = _load_filgoal_cache()
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
            if not merged[key].get('scorers') and m.get('scorers'):
                merged[key]['scorers'] = m['scorers']

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
