import requests
from bs4 import BeautifulSoup
import json
import time
import random
from datetime import datetime, timedelta, timezone

# 🕵️ قائمة هويات المتصفحات للتمويه (User-Agent Rotation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
]

PRIORITY_LEAGUES = [
    "دوري أبطال أوروبا", "الدوري الإنجليزي", "الدوري الإسباني", 
    "الدوري السعودي", "الدوري العراقي", "الدوري الألماني", 
    "الدوري الفرنسي", "الدوري الإيطالي", "دوري أبطال آسيا", "مباريات ودية", "كأس"
]

class GhostScraper:
    def __init__(self):
        self.session = requests.Session()

    def get_headers(self, referer):
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ar,en-US;q=0.7,en;q=0.3',
            'Referer': referer,
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
        }

    def safe_get(self, url):
        # 🚶 محاكاة التأخير البشري
        time.sleep(random.uniform(2.5, 5.2))
        try:
            # استخدام جوجل كرابط إحالة للتمويه في الطلب الأول
            ref = "https://www.google.com/search?q=koora+live"
            res = self.session.get(url, headers=self.get_headers(ref), timeout=25)
            res.encoding = 'utf-8'
            return res
        except Exception as e:
            print(f"⚠️ Security Bypass Failed for {url}: {e}")
            return None

def clean_name(name):
    junk = ["نادي", "فريق", "fc", "f.c", "sc", "u23", "شباب", "الأوليمبي"]
    name = name.lower()
    for word in junk: name = name.replace(word, "")
    return name.strip()

def fetch_yallakora(scraper, date_str):
    print("🕵️ Stealth Mode: Accessing YallaKora...")
    url = f"https://www.yallakora.com/match-center/?date={date_str}"
    res = scraper.safe_get(url)
    if not res: return []
    
    soup = BeautifulSoup(res.content, 'html.parser')
    matches = []
    for card in soup.find_all('div', class_='matchCard'):
        league = card.find('h2').text.strip()
        for m in card.find_all('div', class_='allMatch'):
            try:
                t1 = m.find('div', class_='teamA').find('p').text.strip()
                t2 = m.find('div', class_='teamB').find('p').text.strip()
                scores = m.find('span', class_='score').find_all('b')
                s1, s2 = (scores[0].text.strip(), scores[1].text.strip()) if len(scores) > 1 else ("0", "0")
                st = m.find('div', class_='matchStatus').text.strip()
                matches.append({
                    "homeTeam": t1, "awayTeam": t2, "league": league,
                    "homeLogo": m.find('div', class_='teamA').find('img')['src'],
                    "awayLogo": m.find('div', class_='teamB').find('img')['src'],
                    "score": f"{s1} - {s2}", "homeScore": s1, "awayScore": s2,
                    "matchTime": m.find('span', class_='time').text.strip(),
                    "status": "LIVE" if "جارية" in st else ("ENDED" if "انتهت" in st else "UPCOMING"),
                    "channelName": m.find('div', class_='channel').text.strip() if m.find('div', class_='channel') else "غير متوفرة",
                    "commentator": m.find('div', class_='icon-commentator').parent.text.strip() if m.find('div', class_='icon-commentator') else "غير محدد",
                    "source": "yallakora"
                })
            except: continue
    return matches

def fetch_filgoal(scraper):
    print("🕵️ Stealth Mode: Accessing FilGoal...")
    url = "https://www.filgoal.com/matches/"
    res = scraper.safe_get(url)
    if not res: return []
    
    soup = BeautifulSoup(res.content, 'html.parser')
    matches = []
    for m in soup.find_all('div', class_='mc-data'):
        try:
            t1 = m.find('div', class_='team-a').find('strong').text.strip()
            t2 = m.find('div', class_='team-b').find('strong').text.strip()
            score_div = m.find('div', class_='score')
            s1, s2 = "0", "0"
            if score_div:
                pts = score_div.find_all('span')
                if len(pts) > 1: s1, s2 = pts[0].text.strip(), pts[1].text.strip()
            
            st_txt = m.find('div', class_='match-status').text.strip() if m.find('div', class_='match-status') else ""
            matches.append({
                "homeTeam": t1, "awayTeam": t2, "league": "بطولة دولية",
                "homeLogo": "https:" + m.find('div', class_='team-a').find('img')['src'],
                "awayLogo": "https:" + m.find('div', class_='team-b').find('img')['src'],
                "score": f"{s1} - {s2}", "homeScore": s1, "awayScore": s2,
                "matchTime": m.find('div', class_='match-time').text.strip() if m.find('div', class_='match-time') else "--:--",
                "status": "LIVE" if "شغال" in st_txt else ("ENDED" if "انتهت" in st_txt else "UPCOMING"),
                "channelName": "غير متوفرة", "commentator": "غير محدد", "source": "filgoal"
            })
        except: continue
    return matches

if __name__ == "__main__":
    iraq_tz = timezone(timedelta(hours=3))
    now = datetime.now(iraq_tz)
    
    ghost = GhostScraper()
    
    # 🚀 جلب البيانات بحماية قصوى
    all_data = fetch_yallakora(ghost, now.strftime('%m/%d/%Y')) + fetch_filgoal(ghost)
    
    # دمج المكررات بذكاء
    final_matches = {}
    for m in all_data:
        key = f"{clean_name(m['homeTeam'])}_vs_{clean_name(m['awayTeam'])}"
        if key not in final_matches:
            final_matches[key] = m
        elif m['source'] == 'yallakora':
            final_matches[key] = m

    matches_list = list(final_matches.values())
    for m in matches_list:
        m['priority'] = next((i for i, p in enumerate(PRIORITY_LEAGUES) if p in m['league']), 100)
    
    matches_list.sort(key=lambda x: (x['priority'], x['matchTime']))
    
    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(matches_list, f, ensure_ascii=False, indent=2)
        
    print(f"🏁 Stealth Update Complete. Total: {len(matches_list)}")
