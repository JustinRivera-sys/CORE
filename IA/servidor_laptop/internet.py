"""
Verifica si hay internet, y si lo hay, obtiene la hora/fecha real según la
ubicación (por IP pública) usando un servicio gratuito. Si no hay internet
o el servicio falla, cae de vuelta al reloj del propio equipo — siempre
avisando cuál de las dos fuentes se usó, nunca fingiendo.

Nota honesta: worldtimeapi.org es un servicio gratuito de terceros, no de
Anthropic ni tuyo — puede estar caído o cambiar en cualquier momento. Si
deja de funcionar, esta función simplemente cae al reloj local sin romper
nada (está diseñada para fallar en silencio), pero puede que en algún
momento haya que cambiarla por otro servicio equivalente.
"""

import requests
from datetime import datetime

import logica_asistente

TIMEOUT_SEGUNDOS = 4


def hay_internet():
    try:
        requests.get("https://www.google.com", timeout=TIMEOUT_SEGUNDOS)
        return True
    except requests.exceptions.RequestException:
        return False


def obtener_hora_real_por_ip():
    """Devuelve un dict {"texto": ..., "timezone": ...} con la hora/fecha
    real según la IP pública, o None si no se pudo obtener (sin internet,
    servicio caído, o respuesta inesperada)."""
    try:
        r = requests.get("https://worldtimeapi.org/api/ip", timeout=TIMEOUT_SEGUNDOS)
        r.raise_for_status()
        datos = r.json()
        momento = datetime.fromisoformat(datos["datetime"])
        texto = logica_asistente.ahora_texto_legible(momento)
        return {"texto": texto, "timezone": datos.get("timezone", "desconocida")}
    except Exception:
        return None


def buscar_en_internet(consulta, max_resultados=4):
    """Busca en DuckDuckGo (sin API key, gratis) y devuelve una lista de
    snippets de texto (título + resumen) para dárselos al modelo LOCAL
    como contexto — el buscador solo trae datos crudos, quien responde
    siempre es Ollama, nunca el resultado crudo de la búsqueda.
    Devuelve lista vacía si falla o no hay resultados (nunca truena),
    pero SIEMPRE imprime el motivo real en la terminal para diagnosticar
    (buscadores como DuckDuckGo a veces bloquean/limitan búsquedas
    automatizadas — no siempre es un problema de tu conexión)."""
    try:
        from ddgs import DDGS
        resultados = DDGS().text(consulta, max_results=max_resultados)
        if not resultados:
            print(f"[búsqueda] DDGS no devolvió NINGÚN resultado para {consulta!r} (sin error, lista vacía)")
        return [f"{r.get('title', '')}: {r.get('body', '')}" for r in resultados if r.get("body")]
    except Exception as e:
        print(f"[búsqueda] DDGS falló con una excepción real: {type(e).__name__}: {e}")
        return []


def obtener_hora_para_hablar():
    """Punto de entrada único para el comando de voz 'qué hora es' /
    'qué fecha es'. Siempre dice la verdad de qué pasó: si de verdad no
    hay internet, o si SÍ hay internet pero el servicio de hora específico
    falló (son cosas distintas, y decir 'no tengo internet' cuando sí lo
    hay es engañoso)."""
    if not hay_internet():
        texto_local = logica_asistente.ahora_texto_legible()
        return f"No tengo internet ahorita, así que te doy la hora de este equipo: {texto_local}."

    resultado = obtener_hora_real_por_ip()
    if resultado:
        return f"Según internet, en tu zona horaria ({resultado['timezone']}) es {resultado['texto']}."

    texto_local = logica_asistente.ahora_texto_legible()
    return (
        f"Sí tengo internet, pero el servicio que consulto para la hora exacta no respondió. "
        f"Te doy la hora de este equipo en su lugar: {texto_local}."
    )
