"""
Cara animada minimalista: dos ojos y una boca sobre un Canvas, estilo
"robot amigable". Reemplaza al orbe como interfaz visual del asistente.

Dos cosas se animan de forma independiente:
- El MODO (inactivo / escuchando / procesando / hablando): controla el
  color de la cara y el comportamiento de los ojos y la boca (atenta,
  pensativa, hablando con la amplitud de la voz).
- El ÁNIMO (neutral / feliz / triste / sorprendido / pensativo): controla
  la forma de las cejas y la curva de la boca en reposo, para que la cara
  refleje el tono de lo que el asistente está diciendo.
"""

import tkinter as tk
import math
import random
import time

COLOR_FONDO = "#0b0c14"

# (r, g, b) por cada estado del asistente — mismo criterio que tenía el orbe
COLORES_POR_MODO = {
    "inactivo": (90, 90, 115),
    "escuchando": (60, 200, 220),
    "procesando": (170, 170, 190),
    "hablando": (150, 120, 255),
}


def _interpolar_color(color_a, color_b, t):
    t = max(0.0, min(1.0, t))
    r = int(color_a[0] + (color_b[0] - color_a[0]) * t)
    g = int(color_a[1] + (color_b[1] - color_a[1]) * t)
    b = int(color_a[2] + (color_b[2] - color_a[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rect_redondeado(canvas, x0, y0, x1, y1, radio, **kwargs):
    """Dibuja un rectángulo con esquinas redondeadas (los 'ojos' de la cara)."""
    puntos = [
        x0 + radio, y0,
        x1 - radio, y0,
        x1, y0,
        x1, y0 + radio,
        x1, y1 - radio,
        x1, y1,
        x1 - radio, y1,
        x0 + radio, y1,
        x0, y1,
        x0, y1 - radio,
        x0, y0 + radio,
        x0, y0,
    ]
    return canvas.create_polygon(puntos, smooth=True, **kwargs)


class Cara(tk.Canvas):
    def __init__(self, master, tamano=340, **kwargs):
        super().__init__(master, width=tamano, height=tamano, bg=COLOR_FONDO, highlightthickness=0, **kwargs)
        self.tamano = tamano
        self.centro_x = tamano / 2
        self.centro_y = tamano / 2

        self.modo = "inactivo"
        self.animo = "neutral"
        self.amplitud_objetivo = 0.0
        self.amplitud_actual = 0.0

        self._tiempo_inicio = time.time()
        self._proximo_parpadeo = self._tiempo_inicio + random.uniform(2.0, 5.0)
        self._parpadeo_hasta = 0.0

        self._dibujar()

    # ---------- API pública (misma interfaz que tenía el Orbe) ----------

    def establecer_modo(self, modo):
        self.modo = modo

    def establecer_animo(self, animo):
        """animo: 'neutral' | 'feliz' | 'triste' | 'sorprendido' | 'pensativo'."""
        self.animo = animo if animo in ("neutral", "feliz", "triste", "sorprendido", "pensativo") else "neutral"

    def establecer_amplitud(self, valor):
        """valor esperado aproximadamente entre 0.0 (silencio) y 1.0 (fuerte)."""
        self.amplitud_objetivo = max(0.0, min(1.0, valor))

    def actualizar_frame(self):
        self.amplitud_actual += (self.amplitud_objetivo - self.amplitud_actual) * 0.3
        ahora = time.time()

        if ahora >= self._proximo_parpadeo and self._parpadeo_hasta == 0.0:
            self._parpadeo_hasta = ahora + 0.14
            self._proximo_parpadeo = ahora + random.uniform(2.5, 6.0)
        if self._parpadeo_hasta and ahora >= self._parpadeo_hasta:
            self._parpadeo_hasta = 0.0

        self._dibujar()

    # ---------- dibujo ----------

    def _factor_parpadeo(self, ahora):
        """1.0 = ojos totalmente abiertos, 0.0 = totalmente cerrados."""
        if not self._parpadeo_hasta:
            return 1.0
        progreso = 1.0 - abs((self._parpadeo_hasta - ahora) / 0.07 - 1.0)
        return max(0.05, 1.0 - progreso)

    def _dibujar(self):
        self.delete("all")
        ahora = time.time()
        color = _interpolar_color((70, 70, 90), COLORES_POR_MODO.get(self.modo, COLORES_POR_MODO["inactivo"]), 1.0)

        # Respiración leve constante para que la cara nunca se vea muerta/estática
        t = ahora - self._tiempo_inicio
        respiracion = (math.sin(t * 1.3) + 1) / 2 * 0.04
        escala = 1.0 + respiracion + (self.amplitud_actual * 0.05 if self.modo == "hablando" else 0.0)

        separacion_ojos = self.tamano * 0.20 * escala
        ancho_ojo = self.tamano * 0.13 * escala
        alto_ojo_base = self.tamano * 0.17 * escala
        y_ojos = self.centro_y - self.tamano * 0.06

        # Los ojos se agrandan un poco mientras escucha (atención), y se
        # entrecierran levemente mientras piensa (mirada relajada, sin
        # llegar a verse cansada/triste)
        factor_modo = 1.0
        if self.modo == "escuchando":
            factor_modo = 1.0 + self.amplitud_actual * 0.25
        elif self.modo == "procesando":
            factor_modo = 0.85
        alto_ojo = alto_ojo_base * factor_modo * self._factor_parpadeo(ahora)
        alto_ojo = max(3, alto_ojo)

        radio_ojo = ancho_ojo * 0.4

        for lado in (-1, 1):
            cx = self.centro_x + lado * separacion_ojos
            x0, x1 = cx - ancho_ojo / 2, cx + ancho_ojo / 2
            y0, y1 = y_ojos - alto_ojo / 2, y_ojos + alto_ojo / 2
            _rect_redondeado(self, x0, y0, x1, y1, radio_ojo, fill=color, outline="")

        # Mientras "procesando" (pensando), la cara usa una expresión neutral
        # fija en vez del ánimo de la última respuesta — así nunca hereda una
        # ceja/boca triste de lo último que dijo mientras simplemente calcula.
        animo_dibujado = "neutral" if self.modo == "procesando" else self.animo

        # Cejas — su ángulo/posición define el ánimo visualmente. Se anclan
        # respecto a la altura BASE del ojo (no la altura animada por el
        # parpadeo/atención), para que nunca se monten sobre el ojo.
        self._dibujar_cejas(y_ojos, separacion_ojos, ancho_ojo, alto_ojo_base, color, animo_dibujado)

        # Boca
        self._dibujar_boca(color, animo_dibujado)

    def _dibujar_cejas(self, y_ojos, separacion_ojos, ancho_ojo, alto_ojo_base, color, animo):
        y_base = y_ojos - alto_ojo_base / 2 - self.tamano * 0.045
        largo = ancho_ojo * 0.6
        grosor = max(3, int(self.tamano * 0.016))

        # (desplazamiento_y_interior, desplazamiento_y_exterior) por lado, según ánimo.
        # Valores moderados a propósito: el objetivo es una inclinación sutil y
        # legible, no cejas que se monten sobre los ojos. "pensativo" es
        # simétrico a propósito — una sola ceja alzada se leía como enojo/
        # desconfianza en vez de curiosidad.
        formas = {
            "neutral": (0, 0),
            "feliz": (-2, -4),
            "triste": (-5, 5),
            "sorprendido": (-7, -7),
            "pensativo": (-3, -3),
        }
        interior, exterior = formas.get(animo, (0, 0))

        for lado in (-1, 1):
            cx = self.centro_x + lado * separacion_ojos
            x_int = cx - lado * largo * 0.5
            x_ext = cx + lado * largo * 0.5
            self.create_line(
                x_int, y_base + interior,
                x_ext, y_base + exterior,
                fill=color, width=grosor, capstyle="round",
            )

    def _dibujar_boca(self, color, animo):
        cy = self.centro_y + self.tamano * 0.20
        ancho_base = self.tamano * 0.22
        grosor = max(3, int(self.tamano * 0.02))

        if self.modo == "hablando":
            # boca abierta, oscila con la amplitud de la voz (simula hablar)
            alto = 4 + self.amplitud_actual * self.tamano * 0.14
            ancho = ancho_base * (0.85 + self.amplitud_actual * 0.2)
            self.create_oval(
                self.centro_x - ancho / 2, cy - alto / 2,
                self.centro_x + ancho / 2, cy + alto / 2,
                fill=color, outline="",
            )
            return

        # Boca en reposo: una curva simple cuya concavidad depende del ánimo
        curvas = {
            "neutral": 0.0,
            "feliz": 14,
            "triste": -12,
            "sorprendido": 0.0,
            "pensativo": 0.0,
        }

        if animo == "sorprendido":
            radio = self.tamano * 0.045
            self.create_oval(
                self.centro_x - radio, cy - radio, self.centro_x + radio, cy + radio,
                fill=color, outline="",
            )
            return

        curvatura = curvas.get(animo, 0.0)
        puntos = []
        segmentos = 16
        for i in range(segmentos + 1):
            frac = i / segmentos
            x = self.centro_x - ancho_base / 2 + ancho_base * frac
            # parábola simple para la curva de la sonrisa/mueca
            y = cy + curvatura * (1 - (2 * frac - 1) ** 2)
            puntos.extend([x, y])
        self.create_line(*puntos, fill=color, width=grosor, capstyle="round", joinstyle="round", smooth=True)
