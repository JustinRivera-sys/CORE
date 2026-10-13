"""
Habla con Ollama corriendo en la laptop (no en la Pi). También aplica un
límite simple de mensajes por usuario por minuto, para que el link público
no deje que alguien sature tu laptop mandando spam de preguntas.
"""

import time
import requests
from collections import defaultdict, deque

import config

# usuario_id -> deque de timestamps de sus últimos mensajes
_historial_envios = defaultdict(deque)


def dentro_del_limite(usuario_id):
    ahora = time.time()
    cola = _historial_envios[usuario_id]
    while cola and ahora - cola[0] > 60:
        cola.popleft()
    if len(cola) >= config.LIMITE_MENSAJES_POR_MINUTO:
        return False
    cola.append(ahora)
    return True


def chat(mensajes, system_prompt=None):
    """mensajes: lista de {"role": "user"|"assistant", "content": "..."}.
    Devuelve el texto de respuesta, o lanza una excepción si Ollama no
    responde (la laptop apagada, red caída, etc.)."""
    payload_mensajes = mensajes
    if system_prompt:
        payload_mensajes = [{"role": "system", "content": system_prompt}] + mensajes

    respuesta = requests.post(
        f"{config.OLLAMA_HOST}/api/chat",
        json={"model": config.MODELO_CHAT, "messages": payload_mensajes, "stream": False},
        timeout=120,
    )
    respuesta.raise_for_status()
    return respuesta.json()["message"]["content"]


def ollama_disponible():
    try:
        requests.get(config.OLLAMA_HOST, timeout=3)
        return True
    except requests.exceptions.RequestException:
        return False
