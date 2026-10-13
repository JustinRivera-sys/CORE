"""
Cliente para hablar con Ollama (100% local, sin API externa ni costo).

Centraliza dos tipos de llamadas:
- chat(): para conversar con el modelo de lenguaje.
- embeddings(): para convertir texto en vectores numéricos, usados en la
  búsqueda semántica sobre los documentos que subas a un proyecto.
"""

import requests
import math

## NOTA: para el proyecto universitario (clúster de edge computing), esto
## NO apunta directo a Ollama — apunta al balanceador.py del clúster, que
## también corre en esta misma mini PC y reparte entre ella y la
## Raspberry Pi, con tolerancia a fallos. Así, cada pregunta de CORE pasa
## por el clúster completo, no solo por el Ollama local de esta máquina.
OLLAMA_HOST = "http://127.0.0.1:5000"
# llama3.2:1b porque es el modelo que se descargó en AMBOS nodos del
# clúster (mini PC y Pi) para el proyecto — debe coincidir en los dos
# lados o el nodo al que le toque el turno no va a tener el modelo.
MODELO_CHAT = "llama3.2:1b-instruct-q4_K_M"
MODELO_EMBEDDINGS = "nomic-embed-text"

# Ventana de contexto: cuántos tokens "recuerda" el modelo por consulta.
# Subida de nuevo porque con 30+ hechos guardados, un contexto muy chico
# (como 3000) puede cortar la lista de hechos a la mitad y hacer que el
# asistente "olvide" o contradiga cosas que sí tiene guardadas.
CONTEXTO_TOKENS = 6000


def esta_disponible():
    try:
        requests.get(OLLAMA_HOST, timeout=3)
        return True
    except requests.exceptions.ConnectionError:
        return False


def modelo_embeddings_disponible():
    """Prueba generar un embedding corto para confirmar que el modelo está
    descargado y respondiendo. Se usa para avisar al usuario apenas abre la app."""
    return generar_embedding("prueba") is not None


def chat(system_prompt, mensajes, max_tokens=600):
    """Envía una conversación al modelo de chat y devuelve el texto de respuesta."""
    payload = {
        "model": MODELO_CHAT,
        "messages": [{"role": "system", "content": system_prompt}] + mensajes,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": CONTEXTO_TOKENS,
        },
    }
    respuesta = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=180)
    respuesta.raise_for_status()
    return respuesta.json()["message"]["content"]


def generar_embedding(texto):
    """Convierte un texto en un vector numérico (lista de floats) usando
    el modelo de embeddings local. Devuelve None si falla."""
    try:
        payload = {"model": MODELO_EMBEDDINGS, "prompt": texto}
        respuesta = requests.post(f"{OLLAMA_HOST}/api/embeddings", json=payload, timeout=60)
        respuesta.raise_for_status()
        return respuesta.json()["embedding"]
    except Exception:
        return None


def similitud_coseno(vector_a, vector_b):
    """Calcula qué tan parecidos son dos vectores (1 = idénticos, 0 = nada que ver)."""
    if not vector_a or not vector_b:
        return 0.0
    producto_punto = sum(a * b for a, b in zip(vector_a, vector_b))
    norma_a = math.sqrt(sum(a * a for a in vector_a))
    norma_b = math.sqrt(sum(b * b for b in vector_b))
    if norma_a == 0 or norma_b == 0:
        return 0.0
    return producto_punto / (norma_a * norma_b)


def buscar_fragmentos_relevantes(pregunta, fragmentos, top_k=4, umbral_minimo=0.3):
    """Dado un texto de pregunta y una lista de (contenido, embedding) de un proyecto,
    devuelve los top_k fragmentos más relevantes semánticamente (por encima del umbral)."""
    if not fragmentos:
        return []

    embedding_pregunta = generar_embedding(pregunta)
    if embedding_pregunta is None:
        return []

    puntuados = []
    for contenido, embedding_fragmento in fragmentos:
        puntaje = similitud_coseno(embedding_pregunta, embedding_fragmento)
        if puntaje >= umbral_minimo:
            puntuados.append((puntaje, contenido))

    puntuados.sort(key=lambda x: x[0], reverse=True)
    return [contenido for _, contenido in puntuados[:top_k]]
