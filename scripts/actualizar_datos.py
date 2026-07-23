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

RUTA_TICKERS = os.path.join(os.path.dirname(__file__), "..", "data", "tickers.json")
RUTA_SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "mercado.json")

HEADERS_YAHOO = {"User-Agent": "Mozilla/5.0 (compatible; CobreBot/1.0; +personal use)"}


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
    """Consulta precio actual y cierre anterior de un ticker vía el endpoint de gráficos de Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_yahoo}"
    try:
        r = requests.get(url, headers=HEADERS_YAHOO, params={"interval": "1d", "range": "5d"}, timeout=15)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        meta = result["meta"]
        precio = meta.get("regularMarketPrice")
        anterior = meta.get("previousClose") or meta.get("chartPreviousClose")
        return precio, anterior
    except Exception as e:
        print(f"Aviso: no se pudo obtener {ticker_yahoo} -> {e}")
        return None, None


def main():
    with open(RUTA_TICKERS, encoding="utf-8") as f:
        tickers = json.load(f)

    macro = obtener_mindicador()

    ipsa_precio, ipsa_anterior = obtener_precio_yahoo("^IPSA")
    if ipsa_precio is not None:
        macro["ipsa"] = round(ipsa_precio, 2)
        if ipsa_anterior:
            macro["ipsaChg"] = round((ipsa_precio - ipsa_anterior) / ipsa_anterior * 100, 2)
    if macro.get("dolar") is not None:
        macro["dolar"] = round(macro["dolar"], 1)

    acciones = {}
    for app_ticker, yahoo_ticker in tickers.items():
        precio, anterior = obtener_precio_yahoo(yahoo_ticker)
        if precio is not None:
            acciones[app_ticker] = {
                "precio": round(precio, 2),
                "anterior": round(anterior, 2) if anterior is not None else None,
            }

    salida = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "macro": macro,
        "acciones": acciones,
    }

    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)
    with open(RUTA_SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print("Actualización completa:")
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
