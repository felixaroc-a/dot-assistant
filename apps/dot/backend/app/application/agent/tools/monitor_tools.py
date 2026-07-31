"""Tools de monitoreo - scraper real + herramientas sin API."""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.monitor")
_MONITORS_JSON = "~/Desktop/DOT Trabajos/monitors.json"
_ERR_DOLLAR = "No pude obtener la tasa ahora. Intenta en unos minutos."
_ERR_NEWS = "No pude obtener noticias ahora. Intenta en unos minutos."
_ERR_JOBS = "No pude consultar ofertas de empleo ahora. Intenta en unos minutos."

def _load(): return json.loads(Path(_MONITORS_JSON).expanduser().read_text(encoding="utf-8")) if Path(_MONITORS_JSON).expanduser().exists() else {"alerts":[]}
def _save(d):
    try: p=Path(_MONITORS_JSON).expanduser(); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); return True
    except: return False

def _fetch_dollar_rates():
    from worker.scraper import scrape_dollar_rate
    d = scrape_dollar_rate()
    return d.get("rates", {}), d.get("source", "?")


def get_dollar_rate_handler(uid, args):
    """Consulta la tasa del dólar paralelo en Venezuela (scraping gratuito)."""
    try:
        rates, src = _fetch_dollar_rates()
        if not rates:
            log.warning("get_dollar_rate uid=%s: scraper sin datos", uid[:8])
            return ToolResult(ok=False, output="", error=_ERR_DOLLAR)
        lines = [f"Tasa del dólar ({src}):"]
        for k, v in rates.items():
            lines.append(f"  {k}: {v:.2f} VES/USD")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("get_dollar_rate uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=_ERR_DOLLAR)


def monitor_dollar_rate_handler(uid, args):
    try:
        thr = float(args.get("threshold") or 0)
        rates, src = _fetch_dollar_rates()
        if not rates:
            log.warning("monitor_dollar_rate uid=%s: scraper sin datos", uid[:8])
            return ToolResult(ok=False, output="", error=_ERR_DOLLAR)
        lines = [f"Dolar paralelo ({src}):"]
        for k, v in rates.items():
            lines.append(f"  {k}: {v:.2f} VES/USD {'ALERTA' if thr and v > thr else ''}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("monitor_dollar_rate uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=_ERR_DOLLAR)

def monitor_price_drop_handler(uid,args):
    try:
        url=str(args.get("url")or"").strip(); target=float(args.get("target_price")or 0)
        if not url: return ToolResult(ok=False,output="",error="Falta URL")
        from worker.scraper import scrape_price_from_url
        p=scrape_price_from_url(url)
        if p is None: return ToolResult(ok=True,output=f"No se pudo extraer precio de {url[:60]}. Verifica URL de producto.")
        if target: return ToolResult(ok=True,output=f"Precio: {p:.2f} | Objetivo: {target:.2f} | {'ALERTA' if p<=target else 'OK'}")
        return ToolResult(ok=True,output=f"Precio: {p:.2f}")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_job_opening_handler(uid,args):
    try:
        q=str(args.get("query")or args.get("cargo")or"").strip(); city=str(args.get("city")or"").strip(); lim=min(int(args.get("limit")or 10),20)
        if not q: return ToolResult(ok=False,output="",error="Falta cargo")
        from worker.scraper import scrape_jobs
        jobs=scrape_jobs(q,city,lim)
        if jobs is None:
            return ToolResult(ok=False, output="", error=_ERR_JOBS)
        if not jobs: return ToolResult(ok=True,output=f"No se encontraron ofertas para '{q}' en Computrabajo.")
        lines=[f"Ofertas Computrabajo ({len(jobs)}):"]
        for j in jobs: lines.append(f"  {j['title']} | {j['company']} | {j['location']} | {j.get('salary','')}"); lines.append(f"    {j.get('link','')}")
        return ToolResult(ok=True,output="\n".join(lines))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_news_keyword_handler(uid,args):
    try:
        kw=str(args.get("keyword")or"").strip(); lim=min(int(args.get("limit")or 5),15)
        if not kw: return ToolResult(ok=False,output="",error="Falta keyword")
        from worker.scraper import scrape_news
        arts=scrape_news(kw,lim)
        if arts is None:
            return ToolResult(ok=False, output="", error=_ERR_NEWS)
        if not arts:
            return ToolResult(ok=True, output=f"No se encontraron noticias sobre '{kw}'.")
        lines=[f"Noticias '{kw}':"]
        for a in arts: lines.append(f"  {a['title']} | {a['source']} | {a['date']}")
        return ToolResult(ok=True,output="\n".join(lines))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_website_change_handler(uid,args):
    try:
        url=str(args.get("url")or"").strip()
        if not url: return ToolResult(ok=False,output="",error="Falta URL")
        from worker.scraper import check_website_change
        r=check_website_change(url)
        if r.get("changed"): return ToolResult(ok=True,output=f"CAMBIO en {url[:60]} ({r.get('size',0)} bytes)")
        return ToolResult(ok=True,output=f"Sin cambios en {url[:60]} (status: {r.get('status','?')})")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_social_mentions_handler(uid,args):
    try:
        brand=str(args.get("brand")or args.get("keyword")or"").strip(); lim=min(int(args.get("limit")or 10),20)
        if not brand: return ToolResult(ok=False,output="",error="Falta marca/keyword")
        from worker.scraper import scrape_twitter_mentions
        tweets=scrape_twitter_mentions(brand,lim)
        if not tweets:
            from app.services.provider_router import route_chat
            return ToolResult(ok=True,output=route_chat(f"Menciones recientes de {brand}",provider_id="deepseek",system_prompt="breve").strip()[:600])
        lines=[f"Menciones '{brand}':"]
        for t in tweets: lines.append(f"  @{t['user']}: {t['text'][:120]}")
        return ToolResult(ok=True,output="\n".join(lines))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_stock_market_handler(uid,args):
    try:
        s=str(args.get("symbol")or"").strip()
        if not s: return ToolResult(ok=False,output="",error="Falta simbolo")
        from worker.scraper import scrape_stock_price
        d=scrape_stock_price(s)
        if d.get("error"): return ToolResult(ok=True,output=f"No se pudo obtener {s}: {d['error']}")
        ch=d.get("change",0)or 0; pct=d.get("change_percent",0)or 0; a="+" if ch>0 else ""
        return ToolResult(ok=True,output=f"{d['symbol']}: ${d.get('price','N/A')} {d.get('currency','USD')} ({a}{ch}/{a}{pct}%)")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def monitor_flight_price_handler(uid,args):
    try:
        fr=str(args.get("from")or"").strip(); to=str(args.get("to")or"").strip()
        if not fr or not to: return ToolResult(ok=False,output="",error="Falta origen y destino")
        return ToolResult(ok=True,output=f"Busca vuelos {fr}->{to}: https://www.google.com/travel/flights?q=Vuelos+a+{to.replace(' ','+')}+desde+{fr.replace(' ','+')}")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))
def billing_payment_link_handler(uid,args):
    try:
        amt=float(args.get("amount")or 0); concept=str(args.get("concept")or"Pago").strip(); method=str(args.get("method")or"pago_movil").strip().lower()
        if amt<=0: return ToolResult(ok=False,output="",error="Falta monto")
        m={"pago_movil":"PagoMovil: envia al telefono/cedula del comercio. Confirma ultimos 4 digitos.","zelle":"Zelle: envia al correo registrado. Incluye concepto en nota.","transferencia":"Transferencia bancaria: usa datos del comercio. Guarda comprobante.","binance":"Binance Pay: envia USDT al ID. Confirma TXID.","paypal":"PayPal: envia al correo. Usa 'Pagar por bienes o servicios'."}
        return ToolResult(ok=True,output=f"INSTRUCCIONES DE PAGO\n{'='*30}\nConcepto: {concept}\nMonto: ${amt:.2f}\nMetodo: {m.get(method,method.upper())}\n{'='*30}\n\nConfirma manualmente al recibir.")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def logistics_delivery_tracker_handler(uid,args):
    try:
        trk=str(args.get("tracking")or args.get("guide")or"").strip(); carrier=str(args.get("carrier")or"").strip().lower()
        if not trk: return ToolResult(ok=False,output="",error="Falta numero de guia")
        links={"domesa":f"https://www.domesa.com/rastreo/?guia={trk}","mrw":f"https://www.mrw.com.ve/rastreo/?guia={trk}","zoom":f"https://www.zoom.com.ve/rastreo/?guia={trk}","tealca":f"https://www.tealca.com/rastreo/?guia={trk}"}
        if carrier in links: return ToolResult(ok=True,output=f"Rastrea {trk} ({carrier.upper()}): {links[carrier]}")
        return ToolResult(ok=True,output=f"Guia: {trk}\n\n"+ "\n".join(f"  {c.upper()}: {l}" for c,l in links.items()))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def legal_passport_appointment_handler(uid,args):
    try:
        from worker.scraper import scrape_news
        news=scrape_news("SAIME citas pasaporte",3)
        lines=["CITAS SAIME - sin API oficial.","1. Revisa https://www.saime.gob.ve diariamente","2. DOT monitorea noticias via Google News RSS"]
        if news:
            lines.append("\nNoticias recientes:")
            for n in news: lines.append(f"  {n['title']} | {n['date']}")
        return ToolResult(ok=True,output="\n".join(lines))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def ecom_order_fulfillment_real_handler(uid,args):
    try:
        oid=str(args.get("order_id")or args.get("order")or"").strip(); client=str(args.get("client")or"").strip(); addr=str(args.get("address")or"").strip(); carrier=str(args.get("carrier")or"domesa").strip().lower()
        if not oid or not client: return ToolResult(ok=False,output="",error="Falta order_id y client")
        return ToolResult(ok=True,output=f"FULFILLMENT {oid}\n{'='*30}\nCliente: {client}\nDireccion: {addr}\nTransportista: {carrier.upper()}\n{'='*30}\n\n1. Genera etiqueta en web de {carrier.upper()}\n2. Notifica al cliente con numero de guia\n3. Usa logistics_delivery_tracker")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def billing_whatsapp_payment_handler(uid,args):
    try:
        amt=float(args.get("amount")or 0); concept=str(args.get("concept")or"").strip()
        from app.application.whatsapp.inbound_service import get_message_store
        msgs=get_message_store().list_for_uid(uid,limit=20)
        candidates=[m for m in msgs if "pago" in (m.text or"").lower() or "comprobante" in (m.text or"").lower()]
        if not candidates: return ToolResult(ok=True,output="No se encontraron comprobantes recientes en WA.")
        lines=["Comprobantes WA:"]
        for m in candidates[:5]: lines.append(f"  [{m.timestamp[:19]}] {m.from_phone[-10:]}: {m.text[:120]}")
        lines.append(f"\nVerifica coincidencia con monto ${amt:.2f} concepto '{concept}'.")
        return ToolResult(ok=True,output="\n".join(lines))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def schedule_recurring_handler(uid, args):
    """Delega a cron_schedule_routine (persistencia real en Firestore)."""
    try:
        from app.application.agent.tools.cron_tools import cron_schedule_routine_handler

        msg = str(args.get("message") or "").strip()
        freq = str(args.get("frequency") or "daily").strip().lower()
        at = str(args.get("at") or "09:00").strip()
        channel = str(args.get("channel") or "notify").strip().lower()
        if not msg:
            return ToolResult(ok=False, output="", error="Falta message")

        freq_map = {
            "daily": f"todos los días a las {at}",
            "weekly": f"cada lunes a las {at}",
            "monthly": f"cada mes a las {at}",
        }
        schedule_nl = str(args.get("schedule") or freq_map.get(freq, f"todos los días a las {at}"))
        return cron_schedule_routine_handler(
            uid,
            {
                "message": msg,
                "schedule": schedule_nl,
                "name": str(args.get("name") or msg[:40]),
                "channel": channel,
            },
        )
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))

def data_pivot_table_handler(uid,args):
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path=str(args.get("path")or"").strip(); row=str(args.get("row")or"").strip(); col=str(args.get("column")or"").strip(); val=str(args.get("value")or"").strip()
        if not path or not row: return ToolResult(ok=False,output="",error="Falta path y row")
        raw=execute_local_tool_via_bridge("readFile",path=path)
        if not raw.get("ok"): return ToolResult(ok=False,output="",error=raw.get("error"))
        import csv,io
        rows=list(csv.DictReader(io.StringIO(str(raw.get("content","")))))
        pivot={}
        for r in rows:
            rk=str(r.get(row,""))[:30]; ck=str(r.get(col,""))[:30] if col else "total"
            try: v=float(str(r.get(val,"1")).replace(",","."))
            except: continue
            pivot.setdefault(rk,{}).setdefault(ck,[]).append(v)
        lines=[f"Pivot ({len(pivot)} filas):"]
        for rk in sorted(pivot):
            parts=[f"{rk}:"]+[f"  {ck}={sum(vals):.2f}" for ck,vals in sorted(pivot[rk].items())]
            lines.append(" ".join(parts))
        return ToolResult(ok=True,output="\n".join(lines[:30]))
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def data_merge_handler(uid,args):
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        p1=str(args.get("path1")or"").strip(); p2=str(args.get("path2")or"").strip(); key=str(args.get("key")or"").strip()
        if not p1 or not p2 or not key: return ToolResult(ok=False,output="",error="Falta path1,path2,key")
        import csv,io
        r1=execute_local_tool_via_bridge("readFile",path=p1); r2=execute_local_tool_via_bridge("readFile",path=p2)
        if not r1.get("ok")or not r2.get("ok"): return ToolResult(ok=False,output="",error="Error lectura")
        rows1=list(csv.DictReader(io.StringIO(str(r1.get("content",""))))); rows2=list(csv.DictReader(io.StringIO(str(r2.get("content","")))))
        lookup={r.get(key,""):r for r in rows2}
        merged=[]
        for r1r in rows1:
            mr=dict(r1r); r2r=lookup.get(r1r.get(key,""),{})
            mr.update({k:v for k,v in r2r.items() if k!=key}); merged.append(mr)
        out=str(Path(p1).with_name(f"{Path(p1).stem}_merged.csv"))
        buf=io.StringIO()
        if merged:
            w=csv.DictWriter(buf,fieldnames=list(merged[0].keys())); w.writeheader(); w.writerows(merged)
            res=execute_local_tool_via_bridge("writeFile",path=out,content=buf.getvalue())
            if res.get("ok"): return ToolResult(ok=True,output=f"Merge: {len(merged)} filas en {out}")
        return ToolResult(ok=False,output="",error="Merge fallo")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

def data_forecast_handler(uid,args):
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path=str(args.get("path")or"").strip(); periods=int(args.get("periods")or 3)
        if not path: return ToolResult(ok=False,output="",error="Falta path")
        import csv,io
        raw=execute_local_tool_via_bridge("readFile",path=path)
        if not raw.get("ok"): return ToolResult(ok=False,output="",error=raw.get("error"))
        rows=list(csv.DictReader(io.StringIO(str(raw.get("content","")))))
        nums=[]
        for r in rows:
            for v in r.values():
                try: nums.append(float(str(v).replace(",","."))); break
                except: continue
        if len(nums)<3: return ToolResult(ok=True,output="Se necesitan >=3 datos")
        avg=sum(nums[-3:])/3; trend=(nums[-1]-nums[0])/max(1,len(nums))
        fc=[round(avg+trend*i,2) for i in range(1,periods+1)]
        return ToolResult(ok=True,output=f"Pronostico {periods} periodos: {fc}. Tendencia: {trend:.2f}/periodo")
    except Exception as e: return ToolResult(ok=False,output="",error=str(e))

TOOLS = [
    ("get_dollar_rate", get_dollar_rate_handler),
    ("monitor_dollar_rate", monitor_dollar_rate_handler),
    ("monitor_price_drop", monitor_price_drop_handler),
    # ⚠️ monitor_job_opening → migrado a real_apis.py (scraper Computrabajo real, mejorado)
    # ⚠️ monitor_news_keyword → migrado a real_apis.py (NewsAPI + Google RSS real, mejorado)
    ("monitor_website_change",monitor_website_change_handler),("monitor_social_mentions",monitor_social_mentions_handler),
    ("monitor_stock_market",monitor_stock_market_handler),
    # ⚠️ monitor_flight_price → migrado a real_apis.py (Amadeus API real)
    ("billing_payment_link",billing_payment_link_handler),("logistics_delivery_tracker",logistics_delivery_tracker_handler),
    ("legal_passport_appointment",legal_passport_appointment_handler),("ecom_order_fulfillment",ecom_order_fulfillment_real_handler),
    ("billing_whatsapp_payment",billing_whatsapp_payment_handler),("schedule_recurring",schedule_recurring_handler),
    ("data_pivot_table",data_pivot_table_handler),("data_merge",data_merge_handler),("data_forecast",data_forecast_handler),
]
