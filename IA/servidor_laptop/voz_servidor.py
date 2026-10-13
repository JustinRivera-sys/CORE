"""
Voz del lado del SERVIDOR (tu laptop). A diferencia del voz.py original de
CORE, este módulo NO captura micrófono ni reproduce audio por altavoz — eso
ahora vive en el cliente (la Raspberry Pi). Aquí solo se:

- transcribe audio que llega del cliente (Whisper)
- sintetiza el audio de la respuesta y se devuelve como bytes (Piper),
  para que el cliente lo reproduzca donde esté.
"""

import io
import os
import wave

import numpy as np

FRECUENCIA_MUESTREO = 16000  # Hz, la que espera Whisper y la que debe grabar el cliente

CARPETA_VOCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voces")

_modelo_whisper = None
_voz_piper = None

PARAMS_POR_ANIMO = {
    "feliz": {"length_scale": 0.92, "noise_scale": 0.75, "noise_w_scale": 0.85},
    "triste": {"length_scale": 1.15, "noise_scale": 0.55, "noise_w_scale": 0.65},
    "sorprendido": {"length_scale": 0.88, "noise_scale": 0.8, "noise_w_scale": 0.9},
    "pensativo": {"length_scale": 1.05, "noise_scale": 0.6, "noise_w_scale": 0.7},
    "neutral": {"length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8},
}

try:
    from piper.config import SynthesisConfig
except ImportError:
    SynthesisConfig = None


# ---------- TRANSCRIPCIÓN ----------

def _cargar_whisper():
    global _modelo_whisper
    if _modelo_whisper is None:
        from faster_whisper import WhisperModel
        # Vuelto a "small": "base" entendía mal con demasiada frecuencia,
        # y eso arruina la conversación más que la ganancia de velocidad.
        # La ganancia de velocidad real se busca en beam_size (abajo) en
        # vez de sacrificar precisión con un modelo más chico.
        # cpu_threads=0 le dice a faster-whisper que use todos los núcleos
        # disponibles del CPU (por defecto usa menos) — gana velocidad real
        # sin tocar el modelo ni la precisión.
        import os as _os
        _modelo_whisper = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=_os.cpu_count() or 4)
    return _modelo_whisper


def transcribir_wav_bytes(audio_bytes):
    """Recibe un WAV completo (bytes, como llega del cliente) y devuelve el
    texto transcrito en español."""
    with io.BytesIO(audio_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            audio_array = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    if audio_array.size == 0:
        return ""

    modelo = _cargar_whisper()
    # beam_size=1 (greedy, más rápido que 2) + vad_filter recorta silencios
    # internos antes de transcribir — ambos ganan velocidad sin cambiar de
    # modelo, que es lo que realmente afectaba la precisión.
    segmentos, _info = modelo.transcribe(audio_array, language="es", beam_size=1, vad_filter=True)
    return " ".join(segmento.text.strip() for segmento in segmentos).strip()


# ---------- SÍNTESIS ----------

def _encontrar_modelo_voz():
    if not os.path.isdir(CARPETA_VOCES):
        return None
    archivos_onnx = sorted(f for f in os.listdir(CARPETA_VOCES) if f.lower().endswith(".onnx"))
    if not archivos_onnx:
        return None
    return os.path.join(CARPETA_VOCES, archivos_onnx[0])


def _cargar_piper():
    global _voz_piper
    if _voz_piper is None:
        from piper.voice import PiperVoice
        ruta_modelo = _encontrar_modelo_voz()
        if ruta_modelo is None:
            raise FileNotFoundError(
                f"No hay ningún modelo .onnx de Piper en '{CARPETA_VOCES}'. Copia ahí el "
                ".onnx y el .onnx.json de la voz (los mismos que usaba CORE)."
            )
        _voz_piper = PiperVoice.load(ruta_modelo)
    return _voz_piper


def voz_disponible():
    return _encontrar_modelo_voz() is not None


def _sintetizar_fragmentos(voz_obj, texto, animo):
    params = PARAMS_POR_ANIMO.get(animo, PARAMS_POR_ANIMO["neutral"])
    if SynthesisConfig is not None:
        try:
            config = SynthesisConfig(**params)
            return list(voz_obj.synthesize(texto, syn_config=config))
        except TypeError:
            pass
    try:
        return list(voz_obj.synthesize(texto, **params))
    except TypeError:
        pass
    return list(voz_obj.synthesize(texto))


def sintetizar_a_wav_bytes(texto, animo="neutral"):
    """Sintetiza el texto y devuelve un WAV completo en bytes, listo para
    mandar al cliente por HTTP. Devuelve None si el texto está vacío."""
    if not texto.strip():
        return None

    voz_obj = _cargar_piper()
    fragmentos = _sintetizar_fragmentos(voz_obj, texto, animo)
    if not fragmentos:
        return None

    frecuencia = fragmentos[0].sample_rate
    audio = np.concatenate([f.audio_float_array for f in fragmentos]).astype("float32")
    audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frecuencia)
        wav_file.writeframes(audio_int16.tobytes())
    return buffer.getvalue()
