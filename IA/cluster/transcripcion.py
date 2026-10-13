"""
Transcripción de voz a texto — CPU únicamente (las reglas del proyecto
prohíben GPU dedicada para la inferencia). Reutiliza exactamente la
lógica ya probada del proyecto personal CORE, en su versión de CPU.

Corre en la MINI PC (el nodo maestro), que tiene más CPU que la Pi.
"""

import io
import os
import wave

import numpy as np

_modelo_whisper = None


def _cargar_whisper():
    global _modelo_whisper
    if _modelo_whisper is None:
        from faster_whisper import WhisperModel
        _modelo_whisper = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _modelo_whisper


def transcribir_wav_bytes(audio_bytes):
    """Recibe un WAV completo (bytes) y devuelve el texto transcrito en
    español. Devuelve cadena vacía si el audio está vacío o no se
    detectó habla."""
    with io.BytesIO(audio_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            audio_array = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    if audio_array.size == 0:
        return ""

    modelo = _cargar_whisper()
    segmentos, _info = modelo.transcribe(audio_array, language="es", beam_size=1, vad_filter=True)
    return " ".join(segmento.text.strip() for segmento in segmentos).strip()
