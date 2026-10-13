"""
Servidor de voz de CORE — corre en tu LAPTOP (host). La Raspberry Pi (o
cualquier cliente) le manda un audio grabado, y este servidor:
1. transcribe (Whisper)
2. decide qué hacer y genera la respuesta (misma lógica que ya tenía CORE)
3. sintetiza el audio de la respuesta (Piper)
4. devuelve todo junto: texto, ánimo, acción y el audio en bytes

Arrancar con:
    python -m uvicorn main:app --host 0.0.0.0 --port 8100
"""

import time

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, JSONResponse
import base64

import memoria
import ollama_client
import voz_servidor
import turno

app = FastAPI(title="CORE - Servidor de voz")

memoria.inicializar_db()
PROYECTO_ID = memoria.obtener_id_proyecto_general()


def _empaquetar_respuesta(resultado):
    """Sintetiza el audio y arma la respuesta JSON con el audio en base64
    (más simple de manejar del lado del cliente que multipart)."""
    audio_bytes = None
    if voz_servidor.voz_disponible():
        try:
            audio_bytes = voz_servidor.sintetizar_a_wav_bytes(resultado["texto"], resultado.get("animo", "neutral"))
        except Exception as e:
            print(f"[servidor] Error al sintetizar audio: {e}")

    return {
        "texto": resultado["texto"],
        "animo": resultado.get("animo", "neutral"),
        "accion": resultado.get("accion"),
        "cronometro_segundos": resultado.get("cronometro_segundos"),
        "cronometro_contenido": resultado.get("cronometro_contenido"),
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None,
    }


@app.get("/api/salud")
def salud():
    return {
        "ollama_disponible": ollama_client.esta_disponible(),
        "voz_disponible": voz_servidor.voz_disponible(),
    }


@app.get("/api/saludo_inicial")
def saludo_inicial():
    resultado = turno.generar_saludo_inicial(PROYECTO_ID)
    if resultado is None:
        return {"hay_saludo": False}
    return {"hay_saludo": True, **_empaquetar_respuesta(resultado)}


@app.post("/api/turno")
async def procesar_turno(audio: UploadFile = File(...)):
    if not ollama_client.esta_disponible():
        raise HTTPException(503, "Ollama no está disponible en el servidor.")

    t0 = time.time()
    audio_bytes = await audio.read()
    try:
        texto_usuario = voz_servidor.transcribir_wav_bytes(audio_bytes)
    except Exception as e:
        raise HTTPException(500, f"Error al transcribir: {e}")
    t1 = time.time()
    print(f"[tiempos] transcripción: {t1 - t0:.2f}s -> {texto_usuario!r}")

    if not texto_usuario.strip():
        raise HTTPException(400, "No se detectó ningún texto en el audio.")

    resultado = turno.procesar_turno(texto_usuario, PROYECTO_ID)
    t2 = time.time()
    print(f"[tiempos] lógica + Ollama: {t2 - t1:.2f}s")

    respuesta = _empaquetar_respuesta(resultado)
    t3 = time.time()
    print(f"[tiempos] síntesis de audio: {t3 - t2:.2f}s")
    print(f"[tiempos] TOTAL: {t3 - t0:.2f}s")

    respuesta["texto_usuario"] = texto_usuario
    return respuesta


@app.get("/api/revisar_recordatorios")
def revisar_recordatorios():
    """El cliente llama esto entre turnos (mientras escucha) para saber si
    hay que interrumpir con un recordatorio proactivo."""
    resultado = turno.revisar_recordatorios_pendientes()
    if resultado is None:
        return {"hay_recordatorio": False}
    return {"hay_recordatorio": True, **_empaquetar_respuesta(resultado)}


# ---------- PENDIENTES (para que el cliente muestre su propio calendario) ----------

@app.get("/api/pendientes")
def listar_pendientes():
    pendientes = memoria.obtener_pendientes_activos(PROYECTO_ID)
    return {"pendientes": [{"id": p[0], "contenido": p[1], "fecha_recordatorio": p[2]} for p in pendientes]}


@app.delete("/api/pendientes/{pendiente_id}")
def borrar_pendiente(pendiente_id: int):
    ok = memoria.eliminar_pendiente(pendiente_id)
    if not ok:
        raise HTTPException(404, "Pendiente no encontrado.")
    return {"ok": True}
