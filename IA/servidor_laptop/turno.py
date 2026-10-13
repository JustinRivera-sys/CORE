"""
Procesa UN turno de conversación completo: recibe el texto ya transcrito,
decide qué hacer (comando directo o respuesta normal del modelo), y
devuelve el resultado. Es la misma lógica de decisiones que tenía
asistente_voz.py (comandos de calculadora, recordatorios, etc.) pero
separada de la interfaz gráfica, para poder llamarla desde el servidor.
"""

import re
import threading
from datetime import datetime

import memoria
import logica_asistente
import ollama_client
import tiempo as tiempo_parser
import calculadora
import internet

FRECUENCIA_PREGUNTAS = 5

# Estado de seguimiento de recordatorios, por sesión de cliente (un solo
# asistente físico por ahora, pero se deja preparado por si acaso).
_pendiente_en_seguimiento = {"valor": None}


def _limpiar_expresion_de_tiempo(texto):
    """Quita frases de tiempo ('en 5 minutos', 'a las 6:30 pm', 'mañana',
    etc.) de un texto, dejando solo el contenido real de la tarea.
    Compartida por el recordatorio directo y el pendiente explícito."""
    minuscula = " " + texto.lower().strip() + " "
    minuscula = tiempo_parser.convertir_numeros_a_digitos(minuscula)

    patrones_tiempo = [
        r"\ben\s+\d+\s*(minutos?|mins?|horas?|hrs?)\b",
        r"\ba las\s+\d{1,2}\s*horas?(\s*con\s*\d{1,2}\s*minutos?)?\b",
        r"\ba las\s+\d{1,2}(?::\d{2})?\s*(de la mañana|de la tarde|de la noche|am|pm)?\b",
        r"\bel\s+\d{1,2}\s+de\s+\w+\b",
        r"\bmañana\b",
    ]
    for patron in patrones_tiempo:
        minuscula = re.sub(patron, " ", minuscula)

    return re.sub(r"\s+", " ", minuscula).strip(" ,.!?¿¡")


def _extraer_contenido_recordatorio(texto):
    minuscula = " " + texto.lower().strip() + " "
    disparadores = [
        "hazme un recordatorio de que", "hazme un recordatorio de", "hazme un recordatorio para que",
        "hazme un recordatorio para", "hazme un recordatorio",
        "dame un recordatorio de que", "dame un recordatorio de", "dame un recordatorio",
        "recuérdame que", "recuérdame de que", "recuérdame",
        "recuerdame que", "recuerdame de que", "recuerdame",
        "recuerda me que", "recuerda me de que", "recuerda me",
        "avísame que", "avisame que", "avísame", "avisame",
    ]
    for disparador in disparadores:
        if disparador in minuscula:
            minuscula = minuscula.replace(disparador, " ", 1)
            break

    minuscula = _limpiar_expresion_de_tiempo(minuscula)

    for conector in ("de que", "que", "para", "de"):
        if minuscula.startswith(conector + " "):
            minuscula = minuscula[len(conector) + 1:]
            break

    minuscula = re.sub(r"\s+", " ", minuscula).strip(" ,.!?¿¡")
    return minuscula or "tu recordatorio"


_PATRON_BUSQUEDA = re.compile(r"\b(busc\w*|busqu\w*|investig\w*|averigu\w*)\b|\bnoticias?\b")


def _intentar_busqueda_internet(texto, proyecto_id):
    """El modelo LOCAL siempre compone la respuesta — internet solo se usa
    para traer datos frescos que el modelo no puede saber (noticias,
    hechos recientes). Nunca se devuelve el resultado crudo de la
    búsqueda tal cual.

    Usa un patrón flexible (no frases exactas) porque Whisper a veces
    transcribe mal la conjugación del verbo ('busca' -> 'busses',
    'buscan', 'buscáis') y una frase exacta se perdía esos casos."""
    minuscula = texto.lower()
    coincidencia = _PATRON_BUSQUEDA.search(minuscula)
    if coincidencia is None:
        return None

    # La consulta es el texto completo menos la parte del patrón que matcheó
    consulta = (minuscula[:coincidencia.start()] + " " + minuscula[coincidencia.end():]).strip(" ,.!?¿¡")
    consulta = re.sub(r"\s+", " ", consulta) or texto
    tiene_internet = internet.hay_internet()
    snippets = internet.buscar_en_internet(consulta) if tiene_internet else []
    print(f"[búsqueda] consulta={consulta!r} | tiene_internet={tiene_internet} | resultados encontrados={len(snippets)}")

    if snippets:
        contexto = "\n".join(f"- {s}" for s in snippets)
        system = (
            f"El usuario pidió investigar esto en internet: '{consulta}'. Aquí tienes resultados "
            f"reales de una búsqueda ahora mismo:\n{contexto}\n\n"
            "Responde breve y natural (es por VOZ), usando esta información, y menciona que lo "
            "consultaste en internet."
        )
    elif tiene_internet:
        system = (
            f"El usuario pidió investigar '{consulta}' en internet. SÍ TIENES INTERNET, pero esta "
            "búsqueda específica no trajo resultados útiles (puede pasar). NUNCA digas que no "
            "tienes internet — eso sería falso. En vez de eso, dile que esta búsqueda en particular "
            "no encontró nada útil, y responde con lo que ya sabes tú del tema, aclarando que "
            "podría estar desactualizado."
        )
    else:
        system = (
            f"El usuario pidió investigar '{consulta}' en internet, pero ahora mismo de verdad NO "
            "hay conexión. Dile eso honestamente primero, y luego responde con lo que ya sabes, "
            "aclarando que podría estar desactualizado."
        )

    historial = memoria.obtener_historial_reciente(proyecto_id, limite=4)
    try:
        respuesta = ollama_client.chat(system, historial + [{"role": "user", "content": consulta}], max_tokens=220)
    except Exception:
        respuesta = "No pude conectarme al modelo para responder eso."

    animo = logica_asistente.detectar_animo(respuesta)
    return {"tipo": "respuesta", "texto": respuesta, "animo": animo, "accion": None}


def _intentar_hora_fecha(texto):
    minuscula = texto.lower()
    disparadores = [
        "qué hora es", "que hora es", "dime la hora", "sabes qué hora es",
        "qué día es", "que día es", "qué fecha es", "que fecha es", "dime la fecha",
    ]
    if not any(d in minuscula for d in disparadores):
        return None
    texto_respuesta = internet.obtener_hora_para_hablar()
    return {"tipo": "respuesta", "texto": texto_respuesta, "animo": "neutral", "accion": None}


def _intentar_calculadora(texto):
    resultado = calculadora.intentar_resolver(texto)
    if resultado is None:
        return None
    return {"tipo": "respuesta", "texto": resultado, "animo": "neutral", "accion": None}


def _intentar_calendario(texto):
    minuscula = texto.lower()
    disparadores_abrir = [
        "abre mi calendario", "abre el calendario", "ábreme el calendario", "abreme el calendario",
        "muéstrame mi calendario", "muestrame mi calendario", "muéstrame el calendario", "muestrame el calendario",
        "ver mis pendientes", "muéstrame mis pendientes", "muestrame mis pendientes", "abre mis pendientes",
    ]
    disparadores_cerrar = [
        "cierra mi calendario", "cierra el calendario", "cierra mis pendientes", "ciérrame el calendario",
    ]
    if any(d in minuscula for d in disparadores_cerrar):
        return {"tipo": "respuesta", "texto": "Listo, cerré el calendario.", "animo": "neutral", "accion": "cerrar_calendario"}
    if any(d in minuscula for d in disparadores_abrir):
        return {"tipo": "respuesta", "texto": "Listo, ahí tienes tu calendario.", "animo": "neutral", "accion": "abrir_calendario"}
    return None


def _intentar_borrar_pendiente(texto, proyecto_id):
    minuscula = texto.lower()
    disparadores = [
        "elimina la tarea de", "elimina el pendiente de", "borra la tarea de", "borra el pendiente de",
        "quita la tarea de", "quita el pendiente de", "cancela la tarea de", "cancela el pendiente de",
    ]
    disparador_usado = next((d for d in disparadores if d in minuscula), None)
    if disparador_usado is None:
        return None

    consulta = minuscula.split(disparador_usado, 1)[1].strip(" ,.!?¿¡")
    if not consulta:
        return None

    borrados = memoria.eliminar_pendientes_por_texto(proyecto_id, consulta)
    if borrados:
        texto_respuesta = f"Listo, eliminé: {', '.join(borrados)}."
        animo = "feliz"
    else:
        texto_respuesta = f"No encontré ningún pendiente activo relacionado con '{consulta}'."
        animo = "neutral"
    return {"tipo": "respuesta", "texto": texto_respuesta, "animo": animo, "accion": "refrescar_calendario"}


def _intentar_olvidar_hecho(texto):
    minuscula = texto.lower()
    disparadores = ["olvida que", "olvida lo de", "borra lo que sabes de", "borra de tu memoria"]
    disparador_usado = next((d for d in disparadores if d in minuscula), None)
    if disparador_usado is None:
        return None

    consulta = minuscula.split(disparador_usado, 1)[1].strip(" ,.!?¿¡")
    if not consulta:
        return None

    borrados = memoria.eliminar_hechos_por_texto(consulta)
    texto_respuesta = "Listo, ya no recuerdo eso." if borrados else f"No tenía nada guardado sobre '{consulta}'."
    return {"tipo": "respuesta", "texto": texto_respuesta, "animo": "neutral", "accion": None}


def _hora_corta_12h(fecha):
    """ej: '23/09 a las 2:35 pm' — para confirmaciones breves de recordatorio."""
    hora_12 = fecha.hour % 12
    if hora_12 == 0:
        hora_12 = 12
    periodo = "am" if fecha.hour < 12 else "pm"
    return f"{fecha.strftime('%d/%m')} a las {hora_12}:{fecha.minute:02d} {periodo}"


def _intentar_pendiente_explicito(texto, proyecto_id):
    """Guarda un pendiente SOLO cuando lo dices de forma explícita ('tengo
    un pendiente...'), nunca adivinado de la conversación normal. Si
    además mencionas una hora/fecha, se guarda también (ver tiempo.py);
    si no, se guarda igual pero sin fecha de recordatorio."""
    minuscula = " " + texto.lower().strip() + " "
    disparadores = [
        "tengo un pendiente que es", "tengo un pendiente de que", "tengo un pendiente de",
        "tengo un pendiente:", "tengo un pendiente",
        "tengo una tarea que es", "tengo una tarea de", "tengo una tarea:", "tengo una tarea",
        "anota un pendiente que es", "anota un pendiente de", "anota un pendiente:", "anota un pendiente",
        "agrega un pendiente que es", "agrega un pendiente de", "agrega un pendiente:", "agrega un pendiente",
        "apunta un pendiente que es", "apunta un pendiente de", "apunta un pendiente:", "apunta un pendiente",
        "anota que", "apunta que",
    ]
    disparador_usado = next((d for d in disparadores if d in minuscula), None)
    if disparador_usado is None:
        return None

    contenido = minuscula.split(disparador_usado, 1)[1].strip(" ,.!?¿¡")
    if not contenido:
        return None

    fecha = tiempo_parser.intentar_parsear_fecha(texto)
    contenido = _limpiar_expresion_de_tiempo(contenido) or contenido
    memoria.agregar_pendiente(proyecto_id, contenido, fecha.isoformat() if fecha else None)

    if fecha:
        texto_respuesta = f'Anotado: "{contenido}", te lo recuerdo el {_hora_corta_12h(fecha)}.'
    else:
        texto_respuesta = f'Anotado: "{contenido}".'

    return {"tipo": "respuesta", "texto": texto_respuesta, "animo": "feliz", "accion": "refrescar_calendario"}


def _intentar_recordatorio_directo(texto, proyecto_id):
    minuscula = texto.lower()
    disparadores = ["recuérdame", "recuerdame", "recuerda me", "hazme un recordatorio", "dame un recordatorio", "avísame", "avisame"]
    if not any(d in minuscula for d in disparadores):
        return None

    fecha = tiempo_parser.intentar_parsear_fecha(texto)
    if fecha is None:
        return None

    contenido = _extraer_contenido_recordatorio(texto)
    memoria.agregar_pendiente(proyecto_id, contenido, fecha.isoformat())

    segundos = (fecha - datetime.now()).total_seconds()
    cronometro = segundos if 0 < segundos <= 3600 else None

    texto_respuesta = f'Listo, te recuerdo "{contenido}" el {_hora_corta_12h(fecha)}.'
    return {
        "tipo": "respuesta", "texto": texto_respuesta, "animo": "feliz",
        "accion": "iniciar_cronometro" if cronometro else "refrescar_calendario",
        "cronometro_segundos": cronometro, "cronometro_contenido": contenido if cronometro else None,
    }


def _procesar_seguimiento(texto_usuario):
    pendiente_id = _pendiente_en_seguimiento["valor"]
    _pendiente_en_seguimiento["valor"] = None

    resultado = logica_asistente.interpretar_seguimiento_pendiente(texto_usuario)
    estado = resultado["estado"]

    if estado == "completado":
        memoria.completar_pendiente(pendiente_id)
        texto_respuesta, animo = "Perfecto, la marco como hecha. 🎉", "feliz"
    elif estado == "reprogramado":
        memoria.reprogramar_pendiente(pendiente_id, resultado["fecha_recordatorio"])
        texto_respuesta, animo = "Listo, te lo vuelvo a recordar más tarde.", "neutral"
    else:
        texto_respuesta, animo = "Entendido, sigue pendiente. Te lo vuelvo a preguntar después.", "neutral"

    return {"tipo": "respuesta", "texto": texto_respuesta, "animo": animo, "accion": "refrescar_calendario"}


def _extraer_info_en_segundo_plano(texto_usuario, proyecto_id):
    """Solo extrae HECHOS personales (nombre, gustos, trabajo, etc.) de la
    conversación normal — los pendientes YA NO se adivinan aquí, se
    guardan únicamente cuando el usuario los pide explícitamente
    ('tengo un pendiente...', ver _intentar_pendiente_explicito) para que
    nunca se cuele algo de la conversación como tarea sin que lo pidas."""
    hechos_nuevos = logica_asistente.extraer_hechos(texto_usuario)
    for categoria, contenido in hechos_nuevos:
        memoria.guardar_hecho(categoria, contenido)


def _generar_respuesta_normal(texto_usuario, proyecto_id):
    total_mensajes = memoria.contar_mensajes_usuario(proyecto_id)
    pregunta_sugerida = None
    if total_mensajes % FRECUENCIA_PREGUNTAS == 0:
        import preguntas
        pregunta_sugerida = preguntas.obtener_pregunta_sin_hacer(memoria.pregunta_ya_hecha)

    hechos = memoria.obtener_hechos(limite=15)
    pendientes_activos = memoria.obtener_pendientes_activos(proyecto_id)
    system_prompt = logica_asistente.construir_system_prompt(hechos, pendientes_activos, [], False)
    system_prompt += (
        "\n\nEstás hablando por VOZ en tiempo real, no por chat de texto. Responde de forma "
        "breve y natural, como en una conversación hablada normal (evita listas, markdown, "
        "asteriscos o respuestas largas — máximo 3-4 frases salvo que te pidan explicar algo "
        "a fondo)."
    )
    if pregunta_sugerida:
        system_prompt += f"\n\nAdemás, de forma natural, hazle esta pregunta para conocerlo mejor: \"{pregunta_sugerida}\""

    historial = memoria.obtener_historial_reciente(proyecto_id, limite=6)
    try:
        respuesta = ollama_client.chat(system_prompt, historial, max_tokens=180)
    except Exception:
        respuesta = "No pude conectarme al modelo. Revisa que Ollama esté corriendo."

    if pregunta_sugerida:
        memoria.marcar_pregunta_hecha(pregunta_sugerida)

    threading.Thread(target=_extraer_info_en_segundo_plano, args=(texto_usuario, proyecto_id), daemon=True).start()

    animo = logica_asistente.detectar_animo(respuesta)
    return {"tipo": "respuesta", "texto": respuesta, "animo": animo, "accion": None}


def procesar_turno(texto_usuario, proyecto_id):
    """Punto de entrada único: dado el texto ya transcrito, decide qué hacer
    y devuelve un dict {tipo, texto, animo, accion, ...}. El servidor HTTP
    solo necesita llamar esto y sintetizar el texto resultante."""
    memoria.guardar_mensaje(proyecto_id, "user", texto_usuario)

    # Los comandos directos van SIEMPRE primero — si el chequeo de
    # seguimiento fuera primero, una vez que sonara un recordatorio
    # CUALQUIER cosa que dijeras después (así fuera "cuánto es 2+2" o
    # simplemente seguir la conversación) quedaría atrapada como
    # respuesta a esa pregunta, para siempre, en toda la sesión.
    resultado = (
        _intentar_hora_fecha(texto_usuario)
        or _intentar_busqueda_internet(texto_usuario, proyecto_id)
        or _intentar_calculadora(texto_usuario)
        or _intentar_calendario(texto_usuario)
        or _intentar_borrar_pendiente(texto_usuario, proyecto_id)
        or _intentar_olvidar_hecho(texto_usuario)
        or _intentar_pendiente_explicito(texto_usuario, proyecto_id)
        or _intentar_recordatorio_directo(texto_usuario, proyecto_id)
    )

    if resultado is None and _pendiente_en_seguimiento["valor"] is not None:
        resultado = _procesar_seguimiento(texto_usuario)
    elif resultado is None:
        resultado = _generar_respuesta_normal(texto_usuario, proyecto_id)
    elif _pendiente_en_seguimiento["valor"] is not None:
        # Un comando distinto se coló en medio de la pregunta pendiente —
        # se deja de esperar esa respuesta en vez de seguir atrapando turnos.
        _pendiente_en_seguimiento["valor"] = None

    memoria.guardar_mensaje(proyecto_id, "assistant", resultado["texto"])
    return resultado


def generar_saludo_inicial(proyecto_id):
    hechos = memoria.obtener_hechos(limite=15)
    if not hechos:
        return None
    system = logica_asistente.construir_system_prompt(hechos, [], [], False)
    system += (
        "\n\nEstás iniciando una nueva sesión de conversación por VOZ. Saluda cálidamente por "
        "su nombre (si lo sabes) y pregúntale genuinamente cómo ha estado, mencionando algo "
        "específico que sepas de su vida. Sé breve (2-3 frases), como un saludo hablado real."
    )
    mensaje_inicial = [{"role": "user", "content": "(Se acaba de abrir la conversación de voz, saluda tú primero)"}]
    try:
        saludo = ollama_client.chat(system, mensaje_inicial, max_tokens=100)
    except Exception:
        saludo = "¡Hola! ¿Cómo has estado?"
    memoria.guardar_mensaje(proyecto_id, "assistant", saludo)
    animo = logica_asistente.detectar_animo(saludo)
    return {"tipo": "respuesta", "texto": saludo, "animo": animo, "accion": None}


def revisar_recordatorios_pendientes():
    """Se llama periódicamente desde el servidor (no desde el cliente): si
    hay un recordatorio vencido, lo devuelve para que el cliente lo hable
    proactivamente. None si no hay ninguno pendiente de avisar."""
    ahora_iso = datetime.now().isoformat()
    recordatorios = memoria.obtener_recordatorios_pendientes_de_notificar(ahora_iso)
    if not recordatorios:
        return None

    pendiente_id, contenido = recordatorios[0]
    memoria.marcar_recordatorio_notificado(pendiente_id)
    _pendiente_en_seguimiento["valor"] = pendiente_id

    texto = f"Oye, te quería recordar: {contenido}. ¿Ya lo hiciste, o te lo recuerdo más tarde?"
    return {"tipo": "respuesta", "texto": texto, "animo": "pensativo", "accion": None}
