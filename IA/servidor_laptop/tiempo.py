"""
Parseo determinista de expresiones de tiempo en español ("en 5 minutos",
"a las 6:30 pm", "mañana a las 7"). Existe porque pedirle a un modelo
pequeño (3B) que haga aritmética de fechas es poco confiable — esto cubre
los casos más comunes con certeza, y el modelo queda solo como respaldo
para expresiones más raras que esto no reconozca.
"""

import re
from datetime import datetime, timedelta

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_PATRON_RELATIVO_MIN = re.compile(r"\ben\s+(\d+)\s*(minutos?|mins?)\b")
_PATRON_RELATIVO_HORAS = re.compile(r"\ben\s+(\d+)\s*(horas?|hrs?)\b")
_PATRON_HORA = re.compile(
    r"\ba las\s+(\d{1,2})(?::(\d{2}))?\s*(de la mañana|de la tarde|de la noche|am|pm)?\b"
)
_PATRON_HORA_LARGA = re.compile(
    r"\ba las\s+(\d{1,2})\s*horas?(?:\s*con\s*(\d{1,2})\s*minutos?)?\b"
)
_PATRON_MANANA = re.compile(r"\bmañana\b")
_PATRON_FECHA_EXPLICITA = re.compile(
    r"\bel\s+(\d{1,2})\s+de\s+(" + "|".join(_MESES.keys()) + r")\b"
)

# Whisper a veces transcribe números pequeños como palabra ("un minuto") en
# vez de dígito ("1 minuto"), sobre todo el uno/una. Sin esto, "recuérdame en
# un minuto" no coincidía con ningún patrón (\d+ exige un dígito) y el
# comando caía al modelo, que no lo resolvía bien.
_NUMEROS_ES = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciséis": 16, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
}
_NUMEROS_COMPUESTOS_ES = {
    "treinta y cinco": 35, "treinta y uno": 31, "cuarenta y cinco": 45,
    "cuarenta y uno": 41, "cincuenta y cinco": 55, "cincuenta y uno": 51,
}


def convertir_numeros_a_digitos(texto):
    """Versión pública de _convertir_numeros_a_digitos — la usa también
    asistente_voz.py para limpiar la frase de tiempo al extraer el contenido
    de un recordatorio (ej. quitar 'en un minuto', no solo 'en 1 minuto')."""
    return _convertir_numeros_a_digitos(texto)


def _convertir_numeros_a_digitos(texto):
    """Reemplaza números escritos en palabras por dígitos, solo para que los
    patrones de abajo los reconozcan — no toca el texto original del usuario
    (esto trabaja sobre una copia interna)."""
    for frase, numero in sorted(_NUMEROS_COMPUESTOS_ES.items(), key=lambda kv: -len(kv[0])):
        texto = re.sub(rf"\b{frase}\b", str(numero), texto)
    for palabra, numero in sorted(_NUMEROS_ES.items(), key=lambda kv: -len(kv[0])):
        texto = re.sub(rf"\b{palabra}\b", str(numero), texto)
    return texto


def _resolver_hora_con_periodo(hora, minuto, periodo):
    """Convierte una hora en formato de 12h (con 'de la tarde', 'pm', etc.)
    a 24h. Si no hay periodo, asume la interpretación más razonable: horas
    1-7 se asumen PM si no se especifica (para que 'a las 6' entienda 6pm,
    el uso más común hablando de tareas del día), y 8-12 se dejan tal cual."""
    minuto = minuto or 0
    if periodo in ("pm", "de la tarde", "de la noche") and hora < 12:
        hora += 12
    elif periodo in ("am", "de la mañana") and hora == 12:
        hora = 0
    elif periodo is None and 1 <= hora <= 7:
        hora += 12
    return hora, minuto


def intentar_parsear_fecha(texto, ahora=None):
    """Busca un patrón de tiempo explícito y reconocible en el texto.
    Devuelve un datetime, o None si no encontró ningún patrón conocido
    (en ese caso, quien llama puede recurrir al modelo como respaldo)."""
    ahora = ahora or datetime.now()
    texto = _convertir_numeros_a_digitos(texto.lower())
    texto = re.sub(r"(a las\s+\d{1,2})\s+y\s+media\b", r"\1:30", texto)
    texto = re.sub(r"(a las\s+\d{1,2})\s+y\s+cuarto\b", r"\1:15", texto)

    m = _PATRON_RELATIVO_MIN.search(texto)
    if m:
        return ahora + timedelta(minutes=int(m.group(1)))

    m = _PATRON_RELATIVO_HORAS.search(texto)
    if m:
        return ahora + timedelta(hours=int(m.group(1)))

    dia_base = ahora
    if _PATRON_MANANA.search(texto):
        dia_base = ahora + timedelta(days=1)

    m = _PATRON_FECHA_EXPLICITA.search(texto)
    if m:
        dia, mes_texto = int(m.group(1)), m.group(2)
        anio = ahora.year if _MESES[mes_texto] >= ahora.month else ahora.year + 1
        try:
            dia_base = ahora.replace(year=anio, month=_MESES[mes_texto], day=dia)
        except ValueError:
            pass  # fecha inválida (ej. 31 de febrero) — se ignora, cae a otro patrón

    m = _PATRON_HORA_LARGA.search(texto)
    if m:
        # Formato "a las 17 horas con 53 minutos" — ya viene en 24h explícito,
        # no se le aplica la conversión am/pm.
        hora, minuto = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            resultado = dia_base.replace(hour=hora, minute=minuto, second=0, microsecond=0)
            if resultado <= ahora and dia_base.date() == ahora.date():
                resultado += timedelta(days=1)
            return resultado

    m = _PATRON_HORA.search(texto)
    if m:
        hora, minuto = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        hora, minuto = _resolver_hora_con_periodo(hora, minuto, m.group(3))
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            resultado = dia_base.replace(hour=hora, minute=minuto, second=0, microsecond=0)
            # Si la hora resultante ya pasó hoy y no se dijo "mañana" ni una
            # fecha explícita, se asume que es para mañana (nadie pide que le
            # recuerden algo "a las 3pm" que ya pasó hace rato).
            if resultado <= ahora and dia_base.date() == ahora.date():
                resultado += timedelta(days=1)
            return resultado

    if dia_base.date() != ahora.date():
        # Se detectó "mañana" o una fecha explícita pero sin hora — usar
        # una hora por defecto razonable (9am) en vez de descartar el dato.
        return dia_base.replace(hour=9, minute=0, second=0, microsecond=0)

    return None
