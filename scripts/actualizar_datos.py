"""
Robot de datos para Cobre.
Se ejecuta desde GitHub Actions (no desde el navegador), por eso no hay
problema de CORS: las fuentes se consultan servidor-a-servidor.

Fuentes:
- mindicador.cl  -> dólar, UF, UTM, libra de cobre (espeja datos del Banco Central de Chile)
- Yahoo Finance (endpoint no oficial) -> IPSA y precios de acciones chilenas (sufijo .SN)

Si una fuente falla, el script sigue adelante con lo que sí pudo obtener
y deja registro del aviso, para que un solo dato caído no rompa la actualización completa.
"""

import json
import os
from datetime import datetime, timezone

import requests
import feedparser

RUTA_TICKERS = os.path.join(os.path.dirname(__file__), "..", "data", "tickers.json")
RUTA_SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "mercado.json")

HEADERS_YAHOO = {"User-Agent": "Mozilla/5.0 (compatible; CobreBot/1.0; +personal use)"}

FEEDS_NOTICIAS = [
    ("Cooperativa · Bolsas", "https://www.cooperativa.cl/noticias/site/tax/port/all/rss_6_84__1.xml", None),
    ("Cooperativa · Empresas", "https://www.cooperativa.cl/noticias/site/tax/port/all/rss_6_71__1.xml", None),
    ("Cooperativa · Economía", "https://www.cooperativa.cl/noticias/site/tax/port/all/rss_6___1.xml", None),
    ("Diario Financiero", "https://www.df.cl/noticias/site/list/port/rss.xml",
     {"mercado", "empresa", "economía", "econom", "negocio", "financ", "bolsa", "invers", "startup"}),
]
MAX_POR_FEED = 4


def obtener_noticias():
    """Lee titulares desde RSS públicos y devuelve título + link + fuente (nunca el artículo completo)."""
    noticias = []
    for nombre, url, palabras_clave in FEEDS_NOTICIAS:
        try:
            feed = feedparser.parse(url)
            encontradas = 0
            for entrada in feed.entries:
                if encontradas >= MAX_POR_FEED:
                    break
                titulo = entrada.get("title", "").strip()
                if not titulo:
                    continue
                if palabras_clave is not None:
                    categoria = (entrada.get("category") or "").strip().lower()
                    if not any(palabra in categoria for palabra in palabras_clave):
                        continue  # nos saltamos política, deportes, internacional, etc.
                fecha_iso = None
                if entrada.get("published_parsed"):
                    fecha_iso = datetime(*entrada.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                noticias.append({
                    "fuente": nombre,
                    "texto": titulo,
                    "link": entrada.get("link", ""),
                    "fecha": entrada.get("published", "")[:16] if entrada.get("published") else "",
                    "fechaISO": fecha_iso,
                })
                encontradas += 1
        except Exception as e:
            print(f"Aviso: no se pudo leer el feed {nombre} -> {e}")
    return noticias


def obtener_mindicador():
    """Obtiene dólar, UF, UTM y libra de cobre desde mindicador.cl (gratis, sin llave)."""
    try:
        r = requests.get("https://mindicador.cl/api", timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            "dolar": data.get("dolar", {}).get("valor"),
            "uf": data.get("uf", {}).get("valor"),
            "utm": data.get("utm", {}).get("valor"),
            "cobre": data.get("libra_cobre", {}).get("valor"),
        }
    except Exception as e:
        print(f"Aviso: no se pudo obtener mindicador.cl -> {e}")
        return {}


def obtener_precio_yahoo(ticker_yahoo):
    """Consulta precio actual, cierre anterior y rango de 52 semanas de un ticker."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_yahoo}"
    try:
        r = requests.get(url, headers=HEADERS_YAHOO, params={"interval": "1d", "range": "5d"}, timeout=15)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        meta = result["meta"]
        precio = meta.get("regularMarketPrice")
        anterior = meta.get("previousClose") or meta.get("chartPreviousClose")
        alto52 = meta.get("fiftyTwoWeekHigh")
        bajo52 = meta.get("fiftyTwoWeekLow")
        return precio, anterior, alto52, bajo52
    except Exception as e:
        print(f"Aviso: no se pudo obtener {ticker_yahoo} -> {e}")
        return None, None, None, None


def actualizar_historial(acciones):
    """Guarda un punto de precio por día por acción, para poder graficar la evolución."""
    ruta_historial = os.path.join(os.path.dirname(__file__), "..", "data", "historial.json")
    try:
        with open(ruta_historial, encoding="utf-8") as f:
            historial = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        historial = {}

    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for ticker, datos in acciones.items():
        if datos.get("precio") is None:
            continue
        historial.setdefault(ticker, {})
        historial[ticker][hoy] = datos["precio"]  # si corre varias veces el mismo día, sobreescribe (no duplica)
        fechas = sorted(historial[ticker].keys())
        if len(fechas) > 180:  # conservamos ~6 meses, para que el archivo no crezca indefinidamente
            for f_vieja in fechas[:-180]:
                del historial[ticker][f_vieja]

    with open(ruta_historial, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)


def main():
    with open(RUTA_TICKERS, encoding="utf-8") as f:
        tickers = json.load(f)

    macro = obtener_mindicador()

    ipsa_precio, ipsa_anterior, _, _ = obtener_precio_yahoo("^IPSA")
    if ipsa_precio is not None:
        macro["ipsa"] = round(ipsa_precio, 2)
        if ipsa_anterior:
            macro["ipsaChg"] = round((ipsa_precio - ipsa_anterior) / ipsa_anterior * 100, 2)
    if macro.get("dolar") is not None:
        macro["dolar"] = round(macro["dolar"], 1)

    acciones = {}
    for app_ticker, yahoo_ticker in tickers.items():
        precio, anterior, alto52, bajo52 = obtener_precio_yahoo(yahoo_ticker)
        if precio is not None:
            acciones[app_ticker] = {
                "precio": round(precio, 2),
                "anterior": round(anterior, 2) if anterior is not None else None,
                "alto52": round(alto52, 2) if alto52 is not None else None,
                "bajo52": round(bajo52, 2) if bajo52 is not None else None,
            }

    actualizar_historial(acciones)

    salida = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "macro": macro,
        "acciones": acciones,
        "noticias": obtener_noticias(),
    }

    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)
    with open(RUTA_SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print("Actualización completa:")
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
