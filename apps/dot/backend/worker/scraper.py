"""Motor de scraping interno DOT - sin APIs externas."""
from __future__ import annotations
import hashlib, json, logging, re, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
import httpx

log = logging.getLogger("dot.scraper")
UA = "Mozilla/5.0"
TIMEOUT = 15
CDIR = Path(__file__).resolve().parents[1] / "data" / "scraper_cache"
CTT = 3600

def _cp(k): CDIR.mkdir(parents=True,exist_ok=True); return CDIR / f"{hashlib.md5(k.encode()).hexdigest()[:16]}.json"
def _cg(k):
    p=_cp(k)
    if not p.exists(): return None
    try:
        d=json.loads(p.read_text(encoding="utf-8"))
        return d if time.time()-d.get("_ts",0)<CTT else None
    except: return None
def _cs(k,d):
    try:
        d["_ts"]=time.time(); _cp(k).write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
    except: pass
def _fetch(url,**kw):
    return httpx.get(url,headers={"User-Agent":UA},timeout=TIMEOUT,follow_redirects=True,**kw)

def scrape_dollar_rate():
    c=_cg("dr")
    if c: return c
    r={"source":"scraper","rates":{},"ts":datetime.now(timezone.utc).isoformat()}
    try:
        from bs4 import BeautifulSoup
        resp=_fetch("https://monitordolarvenezuela.com/")
        if resp.status_code==200:
            soup=BeautifulSoup(resp.text,"html.parser")
            for row in soup.select("tr"):
                cells=row.find_all("td")
                if len(cells)>=2:
                    name=cells[0].get_text(strip=True).lower()
                    try: r["rates"][name]=float(cells[1].get_text(strip=True).replace(",",".").replace("Bs","").strip())
                    except: pass
            if r["rates"]: r["source"]="monitordolarvenezuela.com"
    except Exception as e: log.warning("Monitor Dolar: %s",e)
    if not r["rates"]:
        try:
            resp=_fetch("https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",params={"asset":"USDT","fiat":"VES","tradeType":"SELL","page":1,"rows":3},headers={"Accept":"application/json"})
            if resp.status_code==200:
                ads=resp.json().get("data",[])
                rates=[float(a.get("adv",{}).get("price",0)) for a in ads if a.get("adv",{}).get("price")]
                if rates: r["rates"]["binance_p2p"]=round(sum(rates)/len(rates),2); r["source"]="binance_p2p"
        except Exception as e2: log.warning("Binance: %s",e2)
    _cs("dr",r); return r

def scrape_price_from_url(url,css=None):
    try:
        from bs4 import BeautifulSoup
        resp=_fetch(url)
        if resp.status_code!=200: return None
        t=resp.text.lower()
        for pat,grp in [(r'(?:bs|usd|\$)\s*(\d[\d.,]+)',1),(r'(?:precio|price)\s*[:$]?\s*(\d[\d.,]+)',1)]:
            m=re.search(pat,t,re.IGNORECASE)
            if m:
                try: return float(m.group(grp).replace(",",""))
                except: continue
        return None
    except: return None

def scrape_jobs(query,city="",max_results=10):
    try:
        from bs4 import BeautifulSoup
        s=f"{query} {city}".strip()
        url=f"https://ve.computrabajo.com/trabajo-de-{quote_plus(s.replace(' ','-'))}"
        resp=_fetch(url)
        if resp.status_code!=200:
            log.warning("scrape_jobs HTTP %s para %s", resp.status_code, url)
            return None
        soup=BeautifulSoup(resp.text,"html.parser")
        jobs=[]
        for card in soup.select(".iO")[:max_results]:
            t=card.select_one("h2 a") or card.select_one("h1 a")
            c=card.select_one(".dIB"); l=card.select_one(".mr15"); s_el=card.select_one(".fs13")
            title=t.get_text(strip=True) if t else ""
            link=t.get("href","") if t else ""
            jobs.append({"title":title,"company":c.get_text(strip=True) if c else "","location":l.get_text(strip=True) if l else city,"salary":s_el.get_text(strip=True) if s_el else "","link":f"https://ve.computrabajo.com{link}" if link and not link.startswith("http") else link})
        return jobs[:max_results]
    except Exception as e: log.warning("scrape_jobs: %s",e); return None

def scrape_news(keyword,max_results=5):
    try:
        from xml.etree import ElementTree
        url=f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl=es-419&gl=VE&ceid=VE:es-419"
        resp=_fetch(url)
        if resp.status_code!=200:
            log.warning("scrape_news HTTP %s para %s", resp.status_code, keyword)
            return None
        root=ElementTree.fromstring(resp.text)
        items=[]
        for item in root.findall(".//item")[:max_results]:
            items.append({"title":(item.findtext("title","") or "").rsplit(" - ",1)[0].strip(),"source":(item.findtext("source","") or "").strip(),"date":(item.findtext("pubDate","") or "").strip(),"link":(item.findtext("link","") or "").strip()})
        return items
    except Exception as e: log.warning("scrape_news: %s",e); return None

_SNAPS={}
def check_website_change(url):
    try:
        resp=_fetch(url)
        if resp.status_code!=200: return {"changed":False,"error":f"HTTP {resp.status_code}"}
        cur=hashlib.sha256(resp.text.encode()).hexdigest()
        prev=_SNAPS.get(url)
        if prev is None: _SNAPS[url]=cur; return {"changed":False,"status":"first_snapshot","size":len(resp.text)}
        _SNAPS[url]=cur; return {"changed":cur!=prev,"status":"changed" if cur!=prev else "unchanged","size":len(resp.text)}
    except Exception as e: return {"changed":False,"error":str(e)}

def scrape_twitter_mentions(query,max_results=10):
    try:
        from bs4 import BeautifulSoup
        for inst in ["https://nitter.net","https://nitter.poast.org"]:
            try:
                resp=_fetch(f"{inst}/search?f=tweets&q={quote_plus(query)}")
                if resp.status_code!=200: continue
                soup=BeautifulSoup(resp.text,"html.parser")
                tweets=[]
                for tw in soup.select(".timeline-item")[:max_results]:
                    c=tw.select_one(".tweet-content"); u=tw.select_one(".username"); d=tw.select_one(".tweet-date a")
                    tweets.append({"text":c.get_text(strip=True)[:200] if c else "","user":u.get_text(strip=True) if u else "","date":d.get("title","") if d else ""})
                if tweets: return tweets
            except: continue
        return []
    except Exception as e: log.warning("scrape_twitter: %s",e); return []

def scrape_stock_price(symbol):
    try:
        sym=symbol.upper().strip()
        resp=_fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",params={"range":"1d","interval":"1d"})
        if resp.status_code!=200: return {"symbol":sym,"error":f"HTTP {resp.status_code}"}
        meta=resp.json().get("chart",{}).get("result",[{}])[0].get("meta",{})
        p=meta.get("regularMarketPrice"); prev=meta.get("previousClose")
        return {"symbol":sym,"price":p,"currency":meta.get("currency","USD"),"previous_close":prev,"change":round(p-prev,4) if p and prev else None,"change_percent":round((p-prev)/prev*100,2) if p and prev and prev else None}
    except Exception as e: log.warning("scrape_stock %s: %s",symbol,e); return {"symbol":symbol.upper().strip(),"error":str(e)}
