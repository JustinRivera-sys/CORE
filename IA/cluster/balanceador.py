"""
Balanceador de carga para el clúster de edge computing (proyecto
universitario). Reparte las peticiones de inferencia por turnos
(round-robin) entre los 2 nodos del clúster: la mini PC (local) y la
Raspberry Pi (por red) — cada uno corriendo su propia instancia de Ollama
con el modelo llama3.2:1b.

Corre ESTE script en la mini PC (es el nodo "cabeza" del clúster).
"""

import json
import time

import requests
from flask import Flask, request, Response, jsonify

import transcripcion

app = Flask(__name__)

# ---- NODOS DEL CLÚSTER ----
NODO_MINI_PC = {"nombre": "mini_pc", "url": "http://127.0.0.1:11434"}
NODO_RASPBERRY_PI = {"nombre": "raspberry_pi", "url": "http://192.168.10.2:11434"}
NODOS = [NODO_MINI_PC, NODO_RASPBERRY_PI]

# ESTRATEGIA: Nodo Maestro (mini PC) siempre primero, Worker (Pi) SOLO
# como respaldo si el maestro falla — no reparto por turnos. La Pi es
# mucho más débil, y para este proyecto la prioridad es tolerancia a
# fallos (que el sistema no se caiga si el maestro falla), no repartir
# carga pareja entre máquinas de capacidad tan distinta. Esto sigue
# cumpliendo "redistribución de tareas" del requisito del documento.
#
# IMPORTANTE: esto es una lista fija, NO un itertools.cycle compartido —
# cada petición nueva vuelve a intentar desde el principio (mini PC
# primero), en vez de "seguir el turno" donde se quedó la petición
# anterior (eso habría hecho que la mitad de las peticiones arrancaran
# directo por la Pi, el mismo problema que queríamos evitar).
_ORDEN_DE_PRIORIDAD = [NODO_MINI_PC, NODO_RASPBERRY_PI]

TIMEOUT_SEGUNDOS = 40


def _consultar_cluster(ruta, metodo="POST", encabezados=None, cuerpo=None, parametros=None):
    """Lógica central de balanceo + tolerancia a fallos, compartida por
    el proxy genérico y el endpoint de voz. Intenta el siguiente nodo en
    el turno (round-robin); si no responde, reintenta automáticamente con
    los demás nodos del clúster antes de rendirse — así el servicio sigue
    entregando inferencia aunque un worker esté caído.

    Devuelve (contenido_bytes, status_code, content_type) si algún nodo
    respondió, o (None, 503, None) si el clúster completo falló."""
    encabezados = encabezados or {}
    errores = []
    # Recorre SIEMPRE en el mismo orden fijo (mini PC primero) — cada
    # petición nueva arranca desde el principio, no desde donde se quedó
    # la anterior.
    for nodo in _ORDEN_DE_PRIORIDAD:
        url_destino = f"{nodo['url']}/api/{ruta}"
        inicio = time.time()
        try:
            resp = requests.request(
                method=metodo,
                url=url_destino,
                headers=encabezados,
                data=cuerpo,
                params=parametros,
                timeout=TIMEOUT_SEGUNDOS,
            )
            duracion = time.time() - inicio
            print(f"[balanceador] {metodo} /api/{ruta} -> {nodo['nombre']} ({duracion:.2f}s, status {resp.status_code})")
            return resp.content, resp.status_code, resp.headers.get("Content-Type")
        except requests.exceptions.RequestException as e:
            print(f"[balanceador] AVISO: {nodo['nombre']} no respondió ({e}) — redirigiendo al siguiente nodo del clúster")
            errores.append(f"{nodo['nombre']}: {e}")

    print("[balanceador] ERROR CRÍTICO: ningún nodo del clúster respondió")
    return json.dumps({"error": "Ningún nodo del clúster respondió", "detalles": errores}).encode(), 503, "application/json"


@app.route("/api/<path:ruta>", methods=["GET", "POST"])
def proxy(ruta):
    """Reenvía la petición al siguiente nodo en el turno (round-robin),
    con tolerancia a fallos (ver _consultar_cluster)."""
    encabezados = {k: v for k, v in request.headers if k.lower() != "host"}
    contenido, status, content_type = _consultar_cluster(
        ruta, metodo=request.method, encabezados=encabezados,
        cuerpo=request.get_data(), parametros=request.args,
    )
    return Response(contenido, status=status, content_type=content_type)


@app.route("/api/consulta_voz", methods=["POST"])
def consulta_voz():
    """Recibe un audio (WAV), lo transcribe EN LA MINI PC (CPU, sin GPU
    por las reglas del proyecto), y manda el texto resultante a través
    del mismo balanceador con tolerancia a fallos que usa /api/<ruta>."""
    if "audio" not in request.files:
        return jsonify({"error": "Falta el archivo 'audio' en la petición"}), 400

    audio_bytes = request.files["audio"].read()
    inicio = time.time()
    texto_usuario = transcripcion.transcribir_wav_bytes(audio_bytes)
    duracion_transcripcion = time.time() - inicio
    print(f"[balanceador] Transcripción ({duracion_transcripcion:.2f}s): {texto_usuario!r}")

    if not texto_usuario.strip():
        return jsonify({"error": "No se detectó texto en el audio"}), 400

    cuerpo_peticion = json.dumps({
        "model": "llama3.2:1b-instruct-q4_K_M",
        "messages": [{"role": "user", "content": texto_usuario}],
        "stream": False,
    }).encode()

    contenido, status, content_type = _consultar_cluster(
        "chat", metodo="POST",
        encabezados={"Content-Type": "application/json"},
        cuerpo=cuerpo_peticion,
    )

    if status != 200:
        return Response(contenido, status=status, content_type=content_type)

    respuesta_ollama = json.loads(contenido)
    return jsonify({
        "texto_usuario": texto_usuario,
        "respuesta": respuesta_ollama.get("message", {}).get("content", ""),
        "tiempo_transcripcion": round(duracion_transcripcion, 2),
    })


@app.route("/salud")
def salud():
    """Revisa el estado de cada nodo del clúster — útil para el informe
    y la demo en vivo."""
    estado = []
    for nodo in NODOS:
        try:
            r = requests.get(nodo["url"], timeout=3)
            estado.append({"nodo": nodo["nombre"], "url": nodo["url"], "activo": r.ok})
        except requests.exceptions.RequestException:
            estado.append({"nodo": nodo["nombre"], "url": nodo["url"], "activo": False})
    return jsonify({"nodos": estado})


if __name__ == "__main__":
    print("Balanceador de carga del clúster iniciando en el puerto 5000...")
    print(f"Nodos configurados: {[n['nombre'] for n in NODOS]}")
    app.run(host="0.0.0.0", port=5000)
