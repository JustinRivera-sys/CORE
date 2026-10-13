"""
Cliente de CORE — corre en la Raspberry Pi. Solo interfaz: cara animada,
micrófono y altavoz. Todo el procesamiento pesado (Ollama, Whisper, Piper,
memoria) vive en el servidor (tu laptop) — este cliente le manda audio y
reproduce lo que le regresa.
"""

import threading
import time
import base64

import tkinter as tk
import customtkinter as ctk
import requests

import cliente_audio
from cara import Cara
from calendario import VentanaCalendario

ctk.set_appearance_mode("dark")

COLOR_FONDO = "#0b0c14"
COLOR_TEXTO = "#d8d8e8"
COLOR_TEXTO_TENUE = "#6c6c86"

# --- CAMBIA ESTO por la IP real de tu laptop en la red donde esté la Pi ---
SERVIDOR_URL = "http://192.168.10.1:8100"

INTERVALO_REVISAR_RECORDATORIOS_SEG = 20


class VentanaCliente(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CORE")
        self.geometry("480x400")
        self.configure(fg_color=COLOR_FONDO)
        self.resizable(False, False)

        self.pausado = False
        self.cerrando = False
        self._evento_detener_reproduccion = None
        self._cronometro_fin = 0.0
        self._cronometro_contenido = ""
        self.ventana_calendario = None
        self._ultima_revision_recordatorios = 0.0

        self._construir_layout()

        self.escucha = cliente_audio.EscuchaContinua(callback_amplitud=self._on_amplitud)

        self._animar()

        self.hilo_conversacion = threading.Thread(target=self._bucle_conversacion, daemon=True)
        self.hilo_conversacion.start()

        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    # ---------- LAYOUT ----------

    def _construir_layout(self):
        self.grid_columnconfigure(0, weight=1)

        self.cara = Cara(self, tamano=280)
        self.cara.grid(row=0, column=0, pady=(30, 15))

        self.label_estado = ctk.CTkLabel(
            self, text="Conectando...", font=ctk.CTkFont(size=13), text_color=COLOR_TEXTO_TENUE
        )
        self.label_estado.grid(row=1, column=0, pady=(0, 8))

        self.label_subtitulo = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12), text_color=COLOR_TEXTO,
            wraplength=420, justify="center",
        )
        self.label_subtitulo.grid(row=2, column=0, padx=20, pady=(0, 12))

        self.label_cronometro = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#8a78ff",
        )
        self.label_cronometro.grid(row=3, column=0, pady=(0, 8))

        self.boton_pausa = ctk.CTkButton(
            self, text="⏸ Pausar", width=130, command=self._alternar_pausa,
            fg_color="#20222f", hover_color="#2c2e40", text_color=COLOR_TEXTO,
        )
        self.boton_pausa.grid(row=4, column=0, pady=8)

    # ---------- ANIMACIÓN ----------

    def _on_amplitud(self, valor):
        self.cara.establecer_amplitud(valor)

    def _animar(self):
        self.cara.actualizar_frame()
        if not self.cerrando:
            self.after(33, self._animar)

    def _set_estado(self, modo, texto, animo=None):
        self.cara.establecer_modo(modo)
        if animo is not None:
            self.cara.establecer_animo(animo)
        self.label_estado.configure(text=texto)

    # ---------- COMUNICACIÓN CON EL SERVIDOR ----------

    def _servidor_disponible(self):
        try:
            r = requests.get(f"{SERVIDOR_URL}/api/salud", timeout=3)
            return r.ok and r.json().get("ollama_disponible", False)
        except requests.exceptions.RequestException:
            return False

    def _pedir_saludo_inicial(self):
        try:
            r = requests.get(f"{SERVIDOR_URL}/api/saludo_inicial", timeout=30)
            datos = r.json()
            return datos if datos.get("hay_saludo") else None
        except requests.exceptions.RequestException:
            return None

    def _enviar_turno(self, audio_array):
        wav_bytes = cliente_audio.audio_a_wav_bytes(audio_array)
        try:
            r = requests.post(
                f"{SERVIDOR_URL}/api/turno",
                files={"audio": ("audio.wav", wav_bytes, "audio/wav")},
                timeout=120,
            )
            if r.status_code != 200:
                return None
            return r.json()
        except requests.exceptions.RequestException:
            return None

    def _revisar_recordatorios_servidor(self):
        try:
            r = requests.get(f"{SERVIDOR_URL}/api/revisar_recordatorios", timeout=5)
            datos = r.json()
            return datos if datos.get("hay_recordatorio") else None
        except requests.exceptions.RequestException:
            return None

    # ---------- REPRODUCCIÓN DE RESPUESTAS ----------

    def _reproducir_respuesta(self, datos):
        texto = datos.get("texto", "")
        animo = datos.get("animo", "neutral")
        accion = datos.get("accion")

        self.after(0, lambda t=texto: self.label_subtitulo.configure(text=t))
        self.after(0, lambda a=animo: self._set_estado("hablando", "Hablando...", animo=a))

        audio_b64 = datos.get("audio_base64")
        if audio_b64:
            evento_detener = threading.Event()
            self._evento_detener_reproduccion = evento_detener
            wav_bytes = base64.b64decode(audio_b64)
            cliente_audio.reproducir_wav_bytes(wav_bytes, callback_amplitud=self._on_amplitud, detener_evento=evento_detener)

        self._ejecutar_accion(accion, datos)

    def _ejecutar_accion(self, accion, datos):
        if accion == "abrir_calendario":
            self.after(0, self._abrir_ventana_calendario)
        elif accion == "cerrar_calendario":
            self.after(0, self._cerrar_ventana_calendario)
        elif accion == "refrescar_calendario":
            if self.ventana_calendario is not None and self.ventana_calendario.winfo_exists():
                self.after(0, self.ventana_calendario.refrescar)
        elif accion == "iniciar_cronometro":
            segundos = datos.get("cronometro_segundos")
            contenido = datos.get("cronometro_contenido")
            if segundos:
                self.after(0, lambda: self._mostrar_cronometro(segundos, contenido))

    # ---------- CALENDARIO (datos vía HTTP al servidor) ----------

    def _obtener_pendientes_remoto(self):
        try:
            r = requests.get(f"{SERVIDOR_URL}/api/pendientes", timeout=5)
            datos = r.json()["pendientes"]
            return [(p["id"], p["contenido"], p["fecha_recordatorio"]) for p in datos]
        except requests.exceptions.RequestException:
            return []

    def _eliminar_pendiente_remoto(self, pendiente_id):
        try:
            requests.delete(f"{SERVIDOR_URL}/api/pendientes/{pendiente_id}", timeout=5)
        except requests.exceptions.RequestException:
            pass

    def _abrir_ventana_calendario(self):
        if self.ventana_calendario is not None and self.ventana_calendario.winfo_exists():
            self.ventana_calendario.refrescar()
            self.ventana_calendario.deiconify()
            self.ventana_calendario.lift()
        else:
            self.ventana_calendario = VentanaCalendario(
                self, self._obtener_pendientes_remoto, eliminar_pendiente_fn=self._eliminar_pendiente_remoto,
            )

    def _cerrar_ventana_calendario(self):
        if self.ventana_calendario is not None and self.ventana_calendario.winfo_exists():
            self.ventana_calendario.destroy()
        self.ventana_calendario = None

    # ---------- CRONÓMETRO ----------

    def _mostrar_cronometro(self, segundos_totales, contenido):
        self._cronometro_fin = time.time() + segundos_totales
        self._cronometro_contenido = contenido
        self._actualizar_cronometro()

    def _actualizar_cronometro(self):
        restante = self._cronometro_fin - time.time()
        if restante <= 0:
            self.label_cronometro.configure(text="")
            return
        minutos, segundos = divmod(int(restante) + 1, 60)
        self.label_cronometro.configure(text=f'⏳ "{self._cronometro_contenido}" en {minutos:02d}:{segundos:02d}')
        if not self.cerrando:
            self.after(500, self._actualizar_cronometro)

    # ---------- LOOP PRINCIPAL ----------

    def _bucle_conversacion(self):
        while not self._servidor_disponible() and not self.cerrando:
            self.after(0, lambda: self._set_estado("inactivo", "⚠️ No encuentro al servidor. Revisa el cable y que Ollama esté abierto."))
            time.sleep(3)

        if self.cerrando:
            return

        saludo = self._pedir_saludo_inicial()
        if saludo:
            self._reproducir_respuesta(saludo)

        while not self.cerrando:
            if self.pausado:
                time.sleep(0.2)
                continue

            ahora = time.time()
            if ahora - self._ultima_revision_recordatorios > INTERVALO_REVISAR_RECORDATORIOS_SEG:
                self._ultima_revision_recordatorios = ahora
                recordatorio = self._revisar_recordatorios_servidor()
                if recordatorio:
                    self._reproducir_respuesta(recordatorio)
                    continue

            try:
                self.after(0, lambda: self._set_estado("escuchando", "Escuchando..."))
                self.escucha.iniciar()
            except Exception as e:
                print(f"[cliente] Error al iniciar el micrófono: {e}")
                self.after(0, lambda: self._set_estado("inactivo", "⚠️ Error de micrófono"))
                time.sleep(2)
                continue

            audio = None
            while not self.cerrando and not self.pausado:
                audio = self.escucha.esperar_utterance(tiempo_limite=0.3)
                if audio is not None:
                    break
            self.escucha.detener()

            if self.cerrando or self.pausado or audio is None:
                continue

            self.after(0, lambda: self._set_estado("procesando", "Pensando...", animo="neutral"))

            resultado = self._enviar_turno(audio)
            if resultado is None:
                self.after(0, lambda: self._set_estado("inactivo", "⚠️ No pude conectarme al servidor"))
                time.sleep(1)
                continue

            texto_usuario = resultado.get("texto_usuario", "")
            self.after(0, lambda t=texto_usuario: self.label_subtitulo.configure(text=f"Tú: {t}"))

            self._reproducir_respuesta(resultado)

    # ---------- CONTROLES ----------

    def _alternar_pausa(self):
        self.pausado = not self.pausado
        if self.pausado:
            self.boton_pausa.configure(text="▶ Reanudar")
            self._set_estado("inactivo", "En pausa")
            self.escucha.detener()
            if self._evento_detener_reproduccion is not None:
                self._evento_detener_reproduccion.set()
        else:
            self.boton_pausa.configure(text="⏸ Pausar")

    def _al_cerrar(self):
        self.cerrando = True
        self.pausado = True
        try:
            self.escucha.detener()
        except Exception:
            pass
        if self._evento_detener_reproduccion is not None:
            self._evento_detener_reproduccion.set()
        self.destroy()


if __name__ == "__main__":
    app = VentanaCliente()
    app.mainloop()
