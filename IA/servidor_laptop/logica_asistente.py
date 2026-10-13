"""
Construye el prompt de personalidad del asistente y extrae información
(hechos personales, pendientes) de los mensajes del usuario.
"""

import json
from datetime import datetime

import ollama_client

NOMBRE_ASISTENTE = "CORE"

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def ahora_texto_legible(momento=None):
    """Fecha/hora actual en español, en formato de 12 horas natural, ej:
    'domingo 30 de agosto de 2026, 2:35 de la tarde'. No depende del
    locale del sistema (evita problemas en Windows)."""
    momento = momento or datetime.now()
    dia_semana = DIAS_SEMANA[momento.weekday()]
    mes = MESES[momento.month - 1]
    hora_12 = momento.hour % 12
    if hora_12 == 0:
        hora_12 = 12
    if momento.hour < 12:
        periodo = "de la madrugada" if momento.hour < 6 else "de la mañana"
    else:
        periodo = "de la tarde" if momento.hour < 19 else "de la noche"
    return f"{dia_semana} {momento.day} de {mes} de {momento.year}, {hora_12}:{momento.minute:02d} {periodo}"


def construir_system_prompt(hechos, pendientes, fragmentos_relevantes, es_primer_mensaje_sesion, nombre_proyecto=None):
    """Arma el prompt de sistema con personalidad + memoria + contexto de documentos."""
    base = (
        f"Te llamas {NOMBRE_ASISTENTE}, el asistente personal y amigo cercano del usuario. "
        "Hablas SIEMPRE en español, cálido y directo, como un amigo real, no como un producto.\n\n"
        "Reglas clave:\n"
        f"- Tu nombre es siempre {NOMBRE_ASISTENTE}, nunca otro. Tú y el usuario son personas "
        "distintas — los hechos de abajo son sobre ÉL, no sobre ti.\n"
        "- Nunca digas frases corporativas ('soy un modelo de IA...') ni niegues tener memoria — "
        "SÍ la tienes, son los hechos listados abajo.\n"
        "- Sé MUY breve (1-3 frases cortas, como hablaría alguien de verdad, no un párrafo "
        "explicativo). Sin listas, markdown, asteriscos, ni efectos de sonido entre asteriscos.\n"
        "- Habla como se habla de verdad: contracciones, frases cortas, sin sonar formal ni "
        "como manual. Responde solo a lo que se te preguntó, sin agregar de más.\n"
        "- Usa lo que sabes de él con naturalidad (nombre, gustos, proyectos), sin repetir siempre "
        "el mismo tema.\n"
        "- Si no sabes algo, dilo directo en vez de inventar.\n"
    )
    if nombre_proyecto:
        base += (
            f"- Ahora mismo están hablando del tema: '{nombre_proyecto}'. Mantén la conversación "
            "enfocada en ese contexto salvo que el usuario cambie de tema explícitamente.\n"
        )

    base += (
        f"\nFECHA Y HORA ACTUAL: {ahora_texto_legible()}. Úsala si te preguntan qué día es, la hora, "
        "o para entender referencias como 'hoy', 'mañana' o 'esta semana'. Es información real y "
        "exacta del sistema, nunca la niegues ni digas que no sabes qué día es.\n"
    )

    if hechos:
        contexto = "\n".join(f"- {h}" for h in hechos)
        base += (
            f"\nTIENES MEMORIA PERSISTENTE REAL de esta persona, guardada de conversaciones "
            f"anteriores. Esto es lo que ya sabes sobre el usuario:\n{contexto}\n"
        )
    else:
        base += "\nAún no sabes nada sobre el usuario. Aprovecha esta conversación para conocerlo genuinamente.\n"

    if pendientes:
        lista_pendientes = "\n".join(f"- {p}" for _, p, _ in pendientes)
        base += (
            f"\nPendientes activos de este proyecto:\n{lista_pendientes}\n"
            "Si es natural en la conversación, pregúntale cómo va con alguno de ellos. "
            "SOLO menciona los que aparecen en esta lista exacta — nunca inventes ni supongas "
            "otras tareas, citas o recordatorios que no estén aquí.\n"
        )
    else:
        base += (
            "\nAhora mismo NO tiene ningún pendiente guardado. NUNCA inventes ni preguntes por "
            "tareas, citas, llamadas o reuniones que no te dijo — eso incluye ejemplos genéricos "
            "como 'llamar a tu mamá' o 'tu reunión' que a veces los asistentes dicen por costumbre. "
            "Si no hay pendientes reales, simplemente no menciones el tema.\n"
        )

    if fragmentos_relevantes:
        contexto_docs = "\n---\n".join(fragmentos_relevantes)
        base += (
            f"\nEstos son fragmentos relevantes de los documentos que el usuario subió a este "
            f"proyecto, úsalos para responder con precisión si vienen al caso:\n{contexto_docs}\n"
        )

    if es_primer_mensaje_sesion and hechos:
        base += (
            "\nEste es el primer mensaje de una nueva sesión de chat. Saluda cálidamente por su "
            "nombre (si lo sabes) y pregúntale genuinamente cómo ha estado, mencionando algo "
            "específico que sepas de su vida.\n"
        )

    return base


def extraer_hechos(mensaje_usuario):
    """Extrae SOLO hechos personales duraderos del mensaje del usuario
    (nombre, gustos, trabajo, relaciones, metas, rutinas). Ya NO extrae
    pendientes de aquí — esos solo se guardan cuando el usuario lo pide
    explícitamente ('tengo un pendiente...'), para no adivinar tareas de
    la conversación normal y confundir qué se guardó y qué no.
    Devuelve una lista [(categoria, contenido), ...]."""
    system = (
        "Analiza el mensaje del usuario y extrae datos personales objetivos y duraderos SOBRE "
        "ÉL (nombre, gustos, trabajo, relaciones, metas, rutinas, etc). Ignora saludos, preguntas, "
        "tareas pendientes, o cosas que no revelen nada duradero sobre su vida. NUNCA incluyas "
        "datos sobre el asistente/IA mismo — solo sobre la persona que habla.\n"
        "Responde SOLO con JSON válido, sin texto adicional, con este formato exacto: "
        '{"hechos": [{"categoria": "trabajo", "contenido": "..."}]}. '
        "Si no hay nada nuevo, deja la lista vacía."
    )

    try:
        texto = ollama_client.chat(system, [{"role": "user", "content": mensaje_usuario}], max_tokens=200)
        texto = texto.strip().replace("```json", "").replace("```", "").strip()
        inicio = texto.find("{")
        fin = texto.rfind("}")
        if inicio != -1 and fin != -1:
            texto = texto[inicio:fin + 1]
        datos = json.loads(texto)
        return [(h["categoria"], h["contenido"]) for h in datos.get("hechos", [])]
    except Exception:
        return []


def _validar_fecha_iso(texto_fecha):
    """Confirma que el texto que devolvió el modelo sea realmente una fecha ISO
    parseable. Si no lo es (o es null), devuelve None en vez de guardar basura."""
    if not texto_fecha or not isinstance(texto_fecha, str):
        return None
    try:
        datetime.fromisoformat(texto_fecha)
        return texto_fecha
    except ValueError:
        return None


def detectar_animo(texto_respuesta):
    """Heurística simple para decidir qué expresión mostrar en la cara según
    el texto que el asistente está por decir. No es análisis de sentimiento
    con IA (no vale la pena una llamada extra a Ollama solo para esto) —
    son señales léxicas rápidas de contenido, suficientes para animar la cara."""
    texto = texto_respuesta.lower()

    palabras_sorpresa = ["wow", "vaya", "en serio", "no puedo creer", "increíble", "sorpresa", "!?", "?!"]
    palabras_triste = ["lo siento", "qué pena", "lamento", "triste", "lo lamento", "una lástima"]
    palabras_feliz = ["genial", "qué bien", "excelente", "me alegra", "jaja", "😊", "🎉", "perfecto", "buenísimo"]
    palabras_pensativo = ["no estoy seguro", "no tengo eso guardado", "hmm", "déjame pensar", "no sé"]

    if any(p in texto for p in palabras_sorpresa):
        return "sorprendido"
    if any(p in texto for p in palabras_triste):
        return "triste"
    if any(p in texto for p in palabras_feliz):
        return "feliz"
    if any(p in texto for p in palabras_pensativo):
        return "pensativo"
    if texto.strip().endswith("?") or texto.strip().endswith("¿"):
        return "pensativo"
    return "neutral"


def interpretar_seguimiento_pendiente(respuesta_usuario):
    """Cuando el asistente le preguntó al usuario si ya completó una tarea
    pendiente, esto interpreta su respuesta. Devuelve un dict:
    {"estado": "completado" | "pendiente" | "reprogramado", "fecha_recordatorio": iso_o_None}."""
    system = (
        f"Fecha y hora actual: {ahora_texto_legible()}.\n\n"
        "El asistente le acaba de preguntar al usuario si ya completó una tarea pendiente. "
        "Clasifica la respuesta del usuario en JSON, con este formato EXACTO:\n"
        '{"estado": "completado" | "pendiente" | "reprogramado", "fecha_recordatorio": '
        '"YYYY-MM-DDTHH:MM:SS" | null}\n'
        "- 'completado': si dice que ya lo hizo o terminó.\n"
        "- 'reprogramado': si pide que se lo recuerdes en otro momento (calcula la fecha exacta "
        "a partir de la fecha/hora actual de arriba y ponla en 'fecha_recordatorio').\n"
        "- 'pendiente': si dice que no lo ha hecho pero no pide un nuevo horario.\n"
        "Responde SOLO el JSON, sin texto adicional."
    )
    try:
        texto = ollama_client.chat(system, [{"role": "user", "content": respuesta_usuario}], max_tokens=150)
        texto = texto.strip().replace("```json", "").replace("```", "").strip()
        inicio = texto.find("{")
        fin = texto.rfind("}")
        if inicio != -1 and fin != -1:
            texto = texto[inicio:fin + 1]
        datos = json.loads(texto)
        estado = datos.get("estado")
        if estado not in ("completado", "pendiente", "reprogramado"):
            estado = "pendiente"
        fecha_iso = _validar_fecha_iso(datos.get("fecha_recordatorio"))
        if estado == "reprogramado" and fecha_iso is None:
            estado = "pendiente"  # pidió reprogramar pero no entendimos cuándo; mejor no perder la tarea
        return {"estado": estado, "fecha_recordatorio": fecha_iso}
    except Exception:
        return {"estado": "pendiente", "fecha_recordatorio": None}
