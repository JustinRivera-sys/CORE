"""
Captura de micrófono con detección automática de habla (VAD), y
reproducción de audio recibido del servidor. Es la misma lógica de
EscuchaContinua que tenía voz.py en CORE, pero sin Whisper ni Piper — este
cliente no transcribe ni sintetiza nada, solo graba y reproduce.
"""

import io
import time
import threading
import wave

import numpy as np
import sounddevice as sd

FRECUENCIA_MUESTREO = 16000  # Hz — la que espera el servidor (Whisper). El
# micrófono puede no soportar grabar directo a esta frecuencia (muchos USB
# solo hacen 44100/48000), así que se graba a la frecuencia nativa del
# dispositivo y se convierte (resample) antes de mandarla al servidor.


def _frecuencia_nativa_microfono():
    """Frecuencia de muestreo que el micrófono realmente soporta. Si no se
    puede detectar, usa 44100 (el estándar más común en mics USB baratos)."""
    try:
        info = sd.query_devices(kind="input")
        return int(info["default_samplerate"])
    except Exception:
        return 44100


def _resamplear(audio, frecuencia_original, frecuencia_destino):
    """Convierte un array de audio de una frecuencia a otra por
    interpolación lineal — simple y suficiente para voz, sin depender de
    scipy (más liviano para la Pi)."""
    if frecuencia_original == frecuencia_destino or audio.size == 0:
        return audio
    duracion = len(audio) / frecuencia_original
    n_muestras_destino = int(duracion * frecuencia_destino)
    x_original = np.linspace(0, duracion, len(audio), endpoint=False)
    x_destino = np.linspace(0, duracion, n_muestras_destino, endpoint=False)
    return np.interp(x_destino, x_original, audio).astype(np.float32)

UMBRAL_RMS_VOZ = 0.02
SILENCIO_PARA_CORTAR = 1.0
DURACION_MINIMA_UTTERANCE = 0.4


def _rms(bloque):
    if bloque.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(bloque))))


def audio_a_wav_bytes(audio_array, frecuencia=FRECUENCIA_MUESTREO):
    """Convierte un array numpy float32 (-1.0 a 1.0) a bytes de un WAV
    completo, listo para mandar al servidor por HTTP."""
    audio_int16 = np.clip(audio_array * 32767, -32768, 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frecuencia)
        wav_file.writeframes(audio_int16.tobytes())
    return buffer.getvalue()


class EscuchaContinua:
    """Escucha el micrófono de forma continua y detecta automáticamente
    cuándo el usuario empezó y terminó de hablar, sin necesidad de botones.
    Mientras escucha, reporta el volumen en vivo (para animar la cara)."""

    def __init__(self, callback_amplitud=None):
        self.callback_amplitud = callback_amplitud
        self._stream = None
        self._audio_utterance = []
        self._en_habla = False
        self._tiempo_ultimo_sonido = None
        self._tiempo_inicio_habla = None
        self._utterance_lista = threading.Event()
        self._utterance_resultado = None
        self._frecuencia_captura = _frecuencia_nativa_microfono()
        print(f"[cliente] Micrófono grabando a {self._frecuencia_captura} Hz (se convierte a {FRECUENCIA_MUESTREO} Hz antes de enviar)")

    def _callback(self, datos, frames, tiempo, estado):
        bloque = datos[:, 0]
        nivel = _rms(bloque)

        if self.callback_amplitud:
            self.callback_amplitud(min(1.0, nivel * 12))

        ahora = time.time()

        if nivel > UMBRAL_RMS_VOZ:
            if not self._en_habla:
                self._en_habla = True
                self._tiempo_inicio_habla = ahora
                self._audio_utterance = []
            self._tiempo_ultimo_sonido = ahora
            self._audio_utterance.append(bloque.copy())
        elif self._en_habla:
            self._audio_utterance.append(bloque.copy())
            if ahora - self._tiempo_ultimo_sonido > SILENCIO_PARA_CORTAR:
                duracion_habla = self._tiempo_ultimo_sonido - self._tiempo_inicio_habla
                self._en_habla = False
                if duracion_habla >= DURACION_MINIMA_UTTERANCE:
                    audio_final = np.concatenate(self._audio_utterance).flatten()
                    audio_final = _resamplear(audio_final, self._frecuencia_captura, FRECUENCIA_MUESTREO)
                    self._utterance_resultado = audio_final
                    self._utterance_lista.set()
                self._audio_utterance = []

    def iniciar(self):
        self._utterance_lista.clear()
        self._utterance_resultado = None
        self._en_habla = False
        self._audio_utterance = []
        self._stream = sd.InputStream(
            samplerate=self._frecuencia_captura, channels=1, dtype="float32", callback=self._callback,
            blocksize=int(self._frecuencia_captura * 0.05),
        )
        self._stream.start()

    def esperar_utterance(self, tiempo_limite=0.3):
        detectado = self._utterance_lista.wait(timeout=tiempo_limite)
        if detectado:
            self._utterance_lista.clear()
            resultado = self._utterance_resultado
            self._utterance_resultado = None
            return resultado
        return None

    def detener(self):
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        finally:
            self._stream = None
        if self.callback_amplitud:
            self.callback_amplitud(0.0)


def _dispositivo_salida_usb():
    """Busca un dispositivo de salida de audio USB explícitamente — en la
    Pi, el dispositivo 'default' de ALSA no siempre apunta a las bocinas
    USB (puede irse al HDMI o al jack de audífonos), así que hay que
    pedirlo por nombre en vez de confiar en el default del sistema."""
    try:
        dispositivos = sd.query_devices()
        for idx, d in enumerate(dispositivos):
            if d["max_output_channels"] > 0 and "usb" in d["name"].lower():
                return idx
    except Exception:
        pass
    return None  # None = usar el default del sistema, como respaldo


def _frecuencia_nativa_salida(dispositivo_idx):
    """Frecuencia real que soporta el dispositivo de salida elegido. Si no
    se puede detectar, usa 44100 (estándar más compatible)."""
    try:
        info = sd.query_devices(device=dispositivo_idx) if dispositivo_idx is not None else sd.query_devices(kind="output")
        return int(info["default_samplerate"])
    except Exception:
        return 44100


def reproducir_tono(frecuencia_hz=880, duracion_seg=0.12, volumen=0.3):
    """Reproduce un beep corto sintetizado (sin depender de archivos .wav)
    — se usa como acuso de recibo ('te escuché') y como tic mientras
    espera la respuesta del servidor, para que la espera no se sienta
    muerta. No bloquea la animación de la cara porque es casi instantáneo."""
    try:
        dispositivo = _dispositivo_salida_usb()
        frecuencia_salida = _frecuencia_nativa_salida(dispositivo)
        t = np.linspace(0, duracion_seg, int(frecuencia_salida * duracion_seg), endpoint=False)
        # fade out suave para evitar un "click" al cortar el tono
        envolvente = np.linspace(1.0, 0.0, len(t)) ** 2
        tono = (volumen * np.sin(2 * np.pi * frecuencia_hz * t) * envolvente).astype(np.float32)
        sd.play(tono, samplerate=frecuencia_salida, device=dispositivo, blocking=True)
    except Exception as e:
        print(f"[cliente] No pude reproducir el tono: {e}")


def reproducir_wav_bytes(wav_bytes, callback_amplitud=None, detener_evento=None):
    """Reproduce un WAV completo (recibido del servidor) por el altavoz,
    reportando el volumen en vivo para animar la boca de la cara. Bloquea
    hasta terminar o hasta que detener_evento se active."""
    with io.BytesIO(wav_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_file:
            frecuencia_wav = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    if audio.size == 0:
        return

    dispositivo = _dispositivo_salida_usb()
    frecuencia = _frecuencia_nativa_salida(dispositivo)
    # El audio que manda el servidor (Piper, normalmente 22050Hz) casi
    # nunca coincide con lo que soportan las bocinas USB — se convierte
    # antes de reproducir, igual que se hace con el micrófono al grabar.
    audio = _resamplear(audio, frecuencia_wav, frecuencia)

    duracion_audio = len(audio) / frecuencia
    tamano_bloque = max(1, int(frecuencia * 0.05))
    indice = [0]

    def callback_salida(outdata, frames, tiempo, estado):
        inicio = indice[0]
        fin = inicio + frames
        bloque = audio[inicio:fin]

        if len(bloque) < frames:
            outdata[: len(bloque), 0] = bloque
            outdata[len(bloque):, 0] = 0
            if callback_amplitud:
                callback_amplitud(min(1.0, _rms(bloque) * 6) if len(bloque) else 0.0)
            indice[0] = fin
            raise sd.CallbackStop()

        outdata[:, 0] = bloque
        if callback_amplitud:
            callback_amplitud(min(1.0, _rms(bloque) * 6))
        indice[0] = fin

    try:
        stream = sd.OutputStream(
            samplerate=frecuencia, channels=1, dtype="float32", device=dispositivo,
            callback=callback_salida, blocksize=tamano_bloque,
        )
        stream.start()
    except Exception as e:
        print(f"[cliente] No pude abrir el altavoz: {e}")
        return

    tiempo_limite = time.time() + duracion_audio + 5

    try:
        while stream.active:
            if detener_evento is not None and detener_evento.is_set():
                break
            if time.time() > tiempo_limite:
                break
            time.sleep(0.03)
    finally:
        stream.stop()
        stream.close()
        if callback_amplitud:
            callback_amplitud(0.0)
