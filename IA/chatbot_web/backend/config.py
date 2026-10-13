"""
Configuración del backend. RELLENA ESTO ANTES DE USARLO EN LA PI.

No subas este archivo con contraseñas reales a ningún repositorio público
de GitHub — si usas git, agrega config.py a un .gitignore.
"""

import os

# ---------- OLLAMA (proyecto universitario: clúster de 2 nodos) ----------
# Apunta al balanceador.py del clúster (corre en la mini PC, puerto 5000),
# NO directo a Ollama — así cada pregunta del chat se reparte entre la
# mini PC y la Raspberry Pi, con tolerancia a fallos, cumpliendo el
# requisito de hardware permitido (nada de la PC con GPU dedicada).
#
# IMPORTANTE: esto ya NO lee la variable de entorno "OLLAMA_HOST" del
# sistema — esa misma variable la usa Ollama para configurarse a sí mismo
# (OLLAMA_HOST=0.0.0.0:11434), y como se llamaban igual, Windows le pasaba
# ese valor por error al chatbot en vez del balanceador. Valor fijo para
# evitar el choque de nombres.
OLLAMA_HOST = "http://192.168.10.1:5000"
MODELO_CHAT = "llama3.2:1b-instruct-q4_K_M"

# ---------- CORREO (para el link de verificación) ----------
# Ejemplo con Gmail (requiere "Contraseña de aplicación", no tu password normal):
# SMTP_HOST = "smtp.gmail.com"
# SMTP_PORT = 587
# SMTP_USER = "tu_correo@gmail.com"
# SMTP_PASSWORD = "xxxx xxxx xxxx xxxx"   <- la contraseña de aplicación de 16 caracteres
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "ialocalumg@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "jtfc iwoo toyj rkxf")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

# ---------- URL PÚBLICA DEL SITIO ----------
# El link que va dentro del correo de verificación. Mientras pruebas en tu
# red local puede ser la IP de la Pi; cuando actives Tailscale Funnel,
# cámbialo a esa URL pública (https://tu-pi.tu-red.ts.net).
URL_BASE = os.environ.get("URL_BASE", "https://umg.tail3c471d.ts.net")  # link público, funciona desde cualquier red

# ---------- SEGURIDAD ----------
# Duración de la cookie de sesión, y si exigirla como "secure" (solo
# HTTPS). Cuando actives Tailscale Funnel (que sí da HTTPS), cambia esto
# a True.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# Límite de mensajes por usuario para no dejar que alguien sature tu
# laptop haciendo spam de preguntas al modelo.
LIMITE_MENSAJES_POR_MINUTO = 15
