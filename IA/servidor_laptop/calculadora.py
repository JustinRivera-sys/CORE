"""
Detección y resolución de operaciones aritméticas simples dichas en voz.

Existe porque un modelo de 3B parámetros comete errores de aritmética con
frecuencia. Para sumas, restas, multiplicaciones y divisiones, es mejor
resolverlas con código real (100% exacto) que dejárselo al modelo.
"""

import re

_CONECTORES = [
    (r"\bmás\b", "+"),
    (r"\bmas\b", "+"),
    (r"\bmenos\b", "-"),
    (r"\bpor\b", "*"),
    (r"\bdividido\s+entre\b", "/"),
    (r"\bdividido\s+por\b", "/"),
    (r"\bentre\b", "/"),
    (r"\bx\b", "*"),
]

_DISPARADORES = [
    "cuánto es", "cuanto es", "cuánto son", "cuanto son", "cuánto da", "cuanto da",
    "resuelve", "calcula", "cuál es el resultado de", "cual es el resultado de",
]

# Solo caracteres de una expresión aritmética válida — cualquier otra cosa
# en el texto significa que esto NO es (solo) una operación matemática.
_PATRON_EXPRESION = re.compile(r"^[\d\.\+\-\*\/\(\)\s]+$")
_TIENE_OPERADOR_Y_NUMERO = re.compile(r"\d.*[\+\-\*\/].*\d|\d.*[\+\-\*\/]")


def _normalizar(texto):
    texto = texto.lower()
    for patron, simbolo in _CONECTORES:
        texto = re.sub(patron, f" {simbolo} ", texto)
    return texto


def intentar_resolver(texto_usuario):
    """Si el mensaje del usuario es (o contiene claramente) una operación
    aritmética, la resuelve y devuelve un string de respuesta lista para
    hablar. Si no, devuelve None (no era una pregunta de matemáticas)."""
    texto = _normalizar(texto_usuario)

    tiene_disparador = any(d in texto for d in _DISPARADORES)

    # Nos quedamos solo con los caracteres válidos de una expresión, para
    # aislarla del resto de la frase ("cuánto es 25 más 17" -> "25 + 17")
    candidata = re.sub(r"[^\d\.\+\-\*\/\(\)\s]", " ", texto).strip()
    candidata = re.sub(r"\s+", " ", candidata)

    if not candidata or not _PATRON_EXPRESION.match(candidata):
        return None
    if not re.search(r"\d", candidata) or not re.search(r"[\+\-\*\/]", candidata):
        return None
    if not tiene_disparador and len(candidata) < 3:
        return None  # evita falsos positivos con un solo número suelto

    try:
        resultado = eval(candidata, {"__builtins__": {}}, {})
    except ZeroDivisionError:
        return "Esa no la puedo hacer — es una división entre cero."
    except Exception:
        return None

    if isinstance(resultado, float) and resultado.is_integer():
        resultado = int(resultado)
    elif isinstance(resultado, float):
        resultado = round(resultado, 4)

    return f"{candidata.strip()} = {resultado}"
