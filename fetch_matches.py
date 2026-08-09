import requests
from bs4 import BeautifulSoup
import json
import time
import random
from datetime import datetime, timedelta, timezone

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

PRIORITY_LEAGUES = [
    "دوري أبطال أوروبا", "الدوري الإنجليزي", "الدوري الإسباني", 
    "الدوري السعودي", "الدوري العراقي", "دوري أبطال آسيا", "مباريات ودية", "كأس"
]

class GhostScraper:
    def __init__(self):
        self.session = requests.Session()
    def get_headers(self, site):
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': f'https://www.google.com/search?q={site}+football+matches',
            'Accept-Language': 'ar,en;q=0.9'
        }
    def fetch(self, url, site):
        time.sleep(random.uniform(2, 4))
        try:
            res = self.session.get(url, headers=self.get_headers(site), timeout=25)
            res.encoding = 'utf-8'
            return res if res.status_code == 200 else None
        except: return None

def normalize(name):
    junk = ["نادي", "فريق", "fc", "f.c", "sc", "u23", "شباب"]
    name = name.lower()
    for w in junk: name = name.replace(w, "")
    return name.strip()

def scrape_yallakora(scraper, date_str, is_tomorrow):
    url = f"https://www.yallakora.com/match-center/?date={date_str}"
    res = scraper.fetch(url, "yallakora")
    if not res: return []
    soup = BeautifulSoup(res.content, 'html.parser')
    matches = []
    for card in soup.find_all('div', class_='matchCard'):
        league = card.find('h2').text.strip()
        league_logo = card.find('img')['src'] if card.find('img') else ""
        for m in card.find_all('div', class_='allMatch'):
            try:
                scores = m.find('span', class_='score').find_all('b')
                s1, s2 = (scores[0].text.strip(), scores[1].text.strip()) if len(scores) > 1 else ("0", "0")
                st_text = m.find('div', class_='matchStatus').text.strip()
                
                # 🚀 استخراج الدقيقة الحالية بذكاء
                live_time = st_text if any(c.isdigit() for c in st_text) else "LIVE"
                
                matches.append({
                    "homeTeam": m.find('div', class_='teamA').find('p').text.strip(),
                    "awayTeam": m.find('div', class_='teamB').find('p').text.strip(),
                    "homeLogo": m.find('div', class_='teamA').find('img')['src'],
                    "awayLogo": m.find('div', class_='teamB').find('img')['src'],
                    "league": league, "leagueLogo": league_logo,
                    "score": f"{s1} - {s2}", "homeScore": s1, "awayScore": s2,
                    "matchTime": m.find('span', class_='time').text.strip(),
                    "status": "LIVE" if "جارية" in st_text else ("ENDED" if "انتهت" in st_text else "UPCOMING"),
                    "liveMinute": live_time if "جارية" in st_text else "",
                    "channelName": m.find('div', class_='channel').text.strip() if m.find('div', class_='channel') else "غير متوفرة",
                    "commentator": m.find('div', class_='icon-commentator').parent.text.strip() if m.find('div', class_='icon-commentator') else "غير محدد",
                    "isTomorrow": is_tomorrow, "source": "yallakora"
                })
            except: continue
    return matches

def scrape_filgoal(scraper, is_tomorrow):
    if is_tomorrow: return []
    url = "https://www.filgoal.com/matches/"
    res = scraper.fetch(url, "filgoal")
    if not res: return []
    soup = BeautifulSoup(res.content, 'html.parser')
    matches = []
    for m in soup.find_all('div', class_='mc-data'):
        try:
            st_txt = m.find('div', class_='match-status').text.strip() if m.find('div', class_='match-status') else ""
            score_div = m.find('div', class_='score')
            s1, s2 = (score_div.find_all('span')[0].text.strip(), score_div.find_all('span')[1].text.strip()) if score_div else ("0", "0")
            matches.append({
                "homeTeam": m.find('div', class_='team-a').find('strong').text.strip(),
                "awayTeam": m.find('div', class_='team-b').find('strong').text.strip(),
                "league": "البطولة الدولية", "leagueLogo": "",
                "homeLogo": "https:" + m.find('div', class_='team-a').find('img')['src'],
                "awayLogo": "https:" + m.find('div', class_='team-b').find('img')['src'],
                "score": f"{s1} - {s2}", "homeScore": s1, "awayScore": s2,
                "matchTime": m.find('div', class_='match-time').text.strip() if m.find('div', class_='match-time') else "--:--",
                "status": "LIVE" if "شغال" in st_txt or "'" in st_txt else ("ENDED" if "انتهت" in st_txt else "UPCOMING"),
                "liveMinute": st_txt.replace("'", "") if "'" in st_txt else "",
                "isTomorrow": False, "source": "filgoal"
            })
        except: continue
    return matches

if __name__ == "__main__":
    iraq_tz = timezone(timedelta(hours=3))
    now = datetime.now(iraq_tz)
    scraper = GhostScraper()
    
    days = [(now, False), (now + timedelta(days=1), True)]
    all_final = []

    for day_dt, is_tmw in days:
        date_str = day_dt.strftime('%m/%d/%Y')
        print(f"⌛ Fetching {date_str}...")
        yalla = scrape_yallakora(scraper, date_str, is_tmw)
        fil = scrape_filgoal(scraper, is_tmw)
        
        day_dict = {}
        for m in yalla + fil:
            key = f"{normalize(m['homeTeam'])}_{normalize(m['awayTeam'])}"
            if key not in day_dict or m['source'] == 'yallakora': day_dict[key] = m
        all_final.extend(list(day_dict.values()))

    for m in all_final:
        m['p_val'] = next((i for i, p in enumerate(PRIORITY_LEAGUES) if p in m['league']), 100)
    all_final.sort(key=lambda x: (x['isTomorrow'], x['p_val'], x['matchTime']))

    if all_final:
        with open("matches.json", "w", encoding="utf-8") as f:
            json.dump(all_final, f, ensure_ascii=False, indent=2)
        print(f"🏁 Success: {len(all_final)} matches updated.")
