import json
import random
import time
from datetime import datetime, timedelta, timezone
from curl_cffi import requests
from bs4 import BeautifulSoup

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
    "الدوري الإنجليزي": ["إنجليزي", "الإنجليزي", "بريميرليج", "البريميرليج", "انجلترا", "الممتاز"],
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

# ================= دوال الاستخراج المساعدة =================
def extract_team_name(team_div):
    if not team_div: return ""
    strong_tag = team_div.find('strong')
    if strong_tag and strong_tag.text.strip():
        return " ".join(strong_tag.text.split())
    p_tag = team_div.find('p')
    if p_tag and p_tag.text.strip():
        return " ".join(p_tag.text.split())
    span_tag = team_div.find('span')
    if span_tag and span_tag.text.strip():
        return " ".join(span_tag.text.split())
    text = " ".join(team_div.text.split())
    if text and not text.isdigit():
        return text
    img = team_div.find('img')
    if img and img.get('alt'):
        alt_text = img.get('alt').strip()
        if alt_text and not alt_text.isdigit():
            return alt_text
    return ""

def get_logo(img_tag, base_url=""):
    if not img_tag:
        return ""
    logo = img_tag.get('data-src') or img_tag.get('src', '')
    if logo.startswith('//'):
        logo = 'https:' + logo
    elif logo and not logo.startswith('http') and base_url:
        logo = base_url + logo
    return logo

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
        url = f"https://www.yallakora.com/match-center/?date={date_str}"
        html = self.fetch(url, "Yallakora")
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

                    team1, team2 = extract_team_name(t_a), extract_team_name(t_b)
                    if not team1 or not team2: continue
                    logo1, logo2 = get_logo(t_a.find('img')), get_logo(t_b.find('img'))

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
    def scrape_filgoal(self, date_str):
        print(f"-> [Source 2] FilGoal ({date_str})...")
        url = f"https://www.filgoal.com/matches/?date={date_str}"
        html = self.fetch(url, "FilGoal")
        matches = []
        if not html: return matches

        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.find_all('li', class_='match-header-holder'):
            try:
                h6 = li.find('h6')
                league = " ".join(h6.text.split()) if h6 else "بطولة غير معروفة"
                if any(b in league for b in BLOCKLIST): continue

                home_b = li.find('b', class_='home-score')
                away_b = li.find('b', class_='away-score')
                if not home_b or not away_b: continue

                team1, team2 = extract_team_name(home_b.parent), extract_team_name(away_b.parent)
                if not team1 or not team2: continue
                logo1, logo2 = get_logo(home_b.parent.find('img')), get_logo(away_b.parent.find('img'))

                score1 = home_b.get_text(strip=True)
                score2 = away_b.get_text(strip=True)
                status_tag = li.find('span', class_='status')
                status = status_tag.text.strip() if status_tag else "غير محدد"

                if score1.isdigit() and score2.isdigit():
                    score = f"{score1} - {score2}"
                else:
                    time_tag = li.find('span', class_='time')
                    score = time_tag.text.strip() if time_tag and time_tag.text.strip() else "-:-"

                # ----- استخراج القنوات بذكاء من فيلجول -----
                channels = []
                for span in li.find_all('span'):
                    # البحث عن أيقونات التلفاز أو كلاسات القنوات
                    if span.find('i', class_=lambda c: c and ('tv' in c.lower() or 'screen' in c.lower() or 'television' in c.lower())):
                        txt = span.text.strip()
                        if txt: channels = [txt]
                        break

                # ----- استخراج المعلق بذكاء من فيلجول -----
                comm = ""
                for span in li.find_all('span'):
                    if span.find('i', class_=lambda c: c and ('mic' in c.lower() or 'microphone' in c.lower())):
                        comm = span.text.replace('معلق:', '').strip()
                        break

                matches.append({
                    "league": league, "homeTeam": team1, "homeLogo": logo1,
                    "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                    "status": status, "channels": channels, "commentator": comm,
                    "source": "FilGoal"
                })
            except Exception:
                continue
        return matches

    # ================= بطولات =================
    def scrape_btolat(self):
        print("-> [Source 3] Btolat...")
        html = self.fetch("https://www.btolat.com/matches", "Btolat")
        matches = []
        if not html: return matches

        soup = BeautifulSoup(html, 'html.parser')
        for m in soup.find_all('div', class_='match-card'):
            try:
                teams = m.find_all(lambda tag: tag.name == 'a' and 'team' in tag.get('class', []))
                if len(teams) < 2: continue

                team1, team2 = extract_team_name(teams[0]), extract_team_name(teams[1])
                if not team1 or not team2: continue
                logo1, logo2 = get_logo(teams[0].find('img')), get_logo(teams[1].find('img'))

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

                # ----- استخراج القنوات من بطولات -----
                channels = []
                ch_elems = m.find_all(lambda tag: tag.name in ['span', 'div', 'p'] and tag.get('class') and any('channel' in c.lower() or 'tv' in c.lower() for c in tag.get('class', [])))
                for ch in ch_elems:
                    channels.extend([c.strip() for c in ch.text.split('/') if c.strip()])

                # ----- استخراج المعلق من بطولات -----
                comm = ""
                comm_elem = m.find(lambda tag: tag.name in ['span', 'div', 'p'] and tag.get('class') and any('commentator' in c.lower() or 'mic' in c.lower() for c in tag.get('class', [])))
                if comm_elem:
                    comm = comm_elem.text.replace('معلق:', '').strip()

                matches.append({
                    "league": league, "homeTeam": team1, "homeLogo": logo1,
                    "awayTeam": team2, "awayLogo": logo2, "scoreOrTime": score,
                    "status": status, "channels": channels, "commentator": comm,
                    "source": "Btolat"
                })
            except Exception:
                continue
        return matches


# ================= تنظيف الأسماء للدمج =================
def clean_name(name):
    for w in ["نادي", "فريق", "fc", "sc"]: name = name.lower().replace(w, "")
    return name.strip()


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
        key = f"{clean_name(m['homeTeam'])}_{clean_name(m['awayTeam'])}"
        if key not in merged:
            merged[key] = m
        else:
            # ----- الدمج الجراحي الذكي للقنوات -----
            combined_channels = merged[key]['channels'] + m['channels']
            # الحفاظ على القنوات وإزالة أي تكرار
            merged[key]['channels'] = list(dict.fromkeys([c.strip() for c in combined_channels if c.strip()]))
            
            # ----- الدمج الجراحي الذكي للمعلقين -----
            curr_comm = merged[key]['commentator']
            new_comm = m['commentator']
            if not curr_comm and new_comm:
                merged[key]['commentator'] = new_comm
            elif curr_comm and new_comm and new_comm not in curr_comm:
                merged[key]['commentator'] = f"{curr_comm} / {new_comm}"

            # ----- دمج المصادر -----
            if m['source'] not in merged[key]['source']: 
                merged[key]['source'] += f" + {m['source']}"

    final_list = filter_and_rank(list(merged.values()))

    print("\n-> VIP Matches Extracted & Standardized:")
    if not final_list:
        print("   [No VIP matches found!]")
    else:
        for m in final_list:
            print(f"   ✅ [{m['league']}] {m['homeTeam']} {m['scoreOrTime']} {m['awayTeam']} | {m['status']}")

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=4)

    print(f"\n-> [OK] Smart-Filtered & Saved {len(final_list)} matches to matches.json.")
    return final_list


if __name__ == "__main__":
    try:
        print("-> Running single fetch cycle for GitHub Actions...")
        execute_full_cycle()
    except KeyboardInterrupt:
        print("\n🛑 System stopped by user.")
    except Exception as e:
        print(f"\n🛑 System stopped due to error: {e}")
