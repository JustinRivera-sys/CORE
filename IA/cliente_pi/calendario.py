"""
Ventana de "calendario": una lista real y visible de tus pendientes,
agrupados por fecha. Se abre con un comando de voz directo (código real,
no algo que el modelo de lenguaje simule) — así lo que CORE dice sobre tus
tareas siempre coincide con lo que puedes ver en pantalla.
"""

import customtkinter as ctk
from datetime import datetime

COLOR_FONDO = "#0b0c14"
COLOR_TARJETA = "#171826"
COLOR_TEXTO = "#d8d8e8"
COLOR_TEXTO_TENUE = "#6c6c86"
COLOR_ACENTO = "#8a78ff"


def _formatear_fecha(fecha_iso):
    if not fecha_iso:
        return "Sin fecha"
    try:
        momento = datetime.fromisoformat(fecha_iso)
        return momento.strftime("%d/%m/%Y, %H:%M")
    except ValueError:
        return fecha_iso


class VentanaCalendario(ctk.CTkToplevel):
    def __init__(self, master, obtener_pendientes_fn, eliminar_pendiente_fn=None):
        """obtener_pendientes_fn: función sin argumentos que devuelve la
        lista actual de pendientes (para poder refrescar sin recrear la
        ventana cada vez que se pide abrirla de nuevo).
        eliminar_pendiente_fn: función que recibe el id de un pendiente y lo
        borra de verdad — si no se pasa, el botón ✕ no se muestra."""
        super().__init__(master)
        self.obtener_pendientes_fn = obtener_pendientes_fn
        self.eliminar_pendiente_fn = eliminar_pendiente_fn
        self.title("Mis pendientes — CORE")
        self.geometry("420x520")
        self.configure(fg_color=COLOR_FONDO)

        ctk.CTkLabel(
            self, text="📋 Pendientes", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLOR_TEXTO,
        ).pack(pady=(18, 4))

        self.boton_refrescar = ctk.CTkButton(
            self, text="↻ Actualizar", width=110, command=self.refrescar,
            fg_color="#20222f", hover_color="#2c2e40", text_color=COLOR_TEXTO,
        )
        self.boton_refrescar.pack(pady=(0, 10))

        self.contenedor_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_FONDO, width=380, height=420)
        self.contenedor_scroll.pack(padx=15, pady=(0, 15), fill="both", expand=True)

        self.refrescar()

    def refrescar(self):
        for widget in self.contenedor_scroll.winfo_children():
            widget.destroy()

        pendientes = self.obtener_pendientes_fn()
        # Los que tienen fecha van primero, ordenados; sin fecha al final
        con_fecha = sorted([p for p in pendientes if p[2]], key=lambda p: p[2])
        sin_fecha = [p for p in pendientes if not p[2]]

        if not pendientes:
            ctk.CTkLabel(
                self.contenedor_scroll, text="No tienes pendientes activos.",
                text_color=COLOR_TEXTO_TENUE, font=ctk.CTkFont(size=13),
            ).pack(pady=20)
            return

        for pendiente_id, contenido, fecha_iso in con_fecha + sin_fecha:
            tarjeta = ctk.CTkFrame(self.contenedor_scroll, fg_color=COLOR_TARJETA, corner_radius=10)
            tarjeta.pack(fill="x", pady=5, padx=2)
            tarjeta.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                tarjeta, text=contenido, font=ctk.CTkFont(size=13), text_color=COLOR_TEXTO,
                wraplength=280, justify="left", anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=(12, 4), pady=(10, 2))

            ctk.CTkLabel(
                tarjeta, text=_formatear_fecha(fecha_iso), font=ctk.CTkFont(size=11),
                text_color=COLOR_ACENTO if fecha_iso else COLOR_TEXTO_TENUE, anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=(12, 4), pady=(0, 10))

            if self.eliminar_pendiente_fn is not None:
                boton_borrar = ctk.CTkButton(
                    tarjeta, text="✕", width=28, height=28, corner_radius=14,
                    fg_color="#2a1c22", hover_color="#4a1f28", text_color="#ff8a8a",
                    command=lambda pid=pendiente_id: self._borrar(pid),
                )
                boton_borrar.grid(row=0, column=1, rowspan=2, padx=(0, 10), pady=10)

    def _borrar(self, pendiente_id):
        if self.eliminar_pendiente_fn is not None:
            self.eliminar_pendiente_fn(pendiente_id)
        self.refrescar()
