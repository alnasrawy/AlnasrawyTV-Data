import os
import sys
import json
import random
import time
import re
from datetime import datetime, timedelta, timezone
from curl_cffi import requests
from bs4 import BeautifulSoup

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
        time.sleep(random.uniform(1.0, 2.0))
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

    def _fetch_filgoal_detail(self, match_id):
        """القنوات والمعلقون لا يظهرون في صفحة القائمة؛ تُجلب من صفحة المباراة التفصيلية."""
        url = f"https://www.filgoal.com/matches/{match_id}"
        html = self.fetch(url, f"FilGoal (match {match_id})")
        channels, commenters = [], []
        if not html:
            return channels, commenters
        try:
            raw = self._parse_filgoal_viewmodel(html)
            if raw:
                data = json.loads(raw)
                for tv in (data.get('TvCoverage') or []):
                    name = (tv.get('TvChannelName') or '').strip()
                    if name and name not in channels:
                        channels.append(name)
                    comm = (tv.get('CommenterName') or '').strip()
                    if comm and comm not in commenters:
                        commenters.append(comm)
        except Exception:
            pass
        return channels, commenters

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

        # 💡 القنوات والمعلقون من صفحة كل مباراة تفصيلية (غير موجودة في صفحة القائمة)
        for m in seen.values():
            match_id = m.pop('_match_id', None)
            if not match_id or not _is_vip_candidate(m):
                continue
            detail_channels, commenters = self._fetch_filgoal_detail(match_id)
            if detail_channels:
                m['channels'] = dedup_channels([c for c in m['channels'] + detail_channels if c])
            if commenters and not m['commentator']:
                m['commentator'] = ' / '.join(commenters)

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
    s = s.replace('بى ان سبورت', 'beIN SPORTS').replace('بين سبورت', 'beIN SPORTS')
    s = s.replace('اون سبورت', 'On Sport').replace('أون سبورت', 'On Sport')
    s = s.replace('أبو ظبي', 'أبوظبي').replace('ابو ظبي', 'أبوظبي').replace('ابوظبي', 'أبوظبي')
    s = s.replace('ماكس', 'MAX').replace('بلس', 'PLUS')
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
    now = datetime.now(TZ)
    yalla_date = now.strftime('%m/%d/%Y')
    fil_date = now.strftime('%Y-%m-%d')

    today_str = yalla_date
    print(f"\n-> Fetching Matches for Date: {today_str}...")

    yalla = scraper_engine.scrape_yalla(yalla_date)
    print(f"    -> يالاكورة: {len(yalla)} مباراة")
    fil = scraper_engine.scrape_filgoal(fil_date)
    print(f"    -> فيلجول: {len(fil)} مباراة")
    bto = scraper_engine.scrape_btolat()
    print(f"    -> بطولات: {len(bto)} مباراة")

    all_raw = yalla + fil + bto
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
