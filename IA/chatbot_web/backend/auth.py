"""
Lógica de autenticación: hash de contraseñas (nunca se guardan en texto
plano), generación de tokens seguros para verificación de correo y
sesiones de login.
"""

import secrets
import bcrypt
from datetime import datetime, timedelta

import database

DURACION_TOKEN_VERIFICACION_HORAS = 24
DURACION_SESION_DIAS = 7
MAX_INTENTOS_FALLIDOS = 5
DURACION_BLOQUEO_MINUTOS = 15


def hashear_password(password):
    # bcrypt solo admite hasta 72 bytes — se trunca ahí si el usuario
    # escribe algo absurdamente largo, en vez de tronar.
    password_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verificar_password(password, password_hash):
    password_bytes = password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:
        return False


def generar_token_verificacion(usuario_id):
    token = secrets.token_urlsafe(32)
    expira_en = (datetime.now() + timedelta(hours=DURACION_TOKEN_VERIFICACION_HORAS)).isoformat()
    database.guardar_token_verificacion(token, usuario_id, expira_en)
    return token


def validar_token_verificacion(token):
    """Devuelve el usuario_id si el token es válido y no ha expirado, o
    None si es inválido/expiró. Si es válido, lo elimina (de un solo uso)."""
    fila = database.obtener_token_verificacion(token)
    if fila is None:
        return None
    if datetime.fromisoformat(fila["expira_en"]) < datetime.now():
        database.eliminar_token_verificacion(token)
        return None
    database.eliminar_token_verificacion(token)
    return fila["usuario_id"]


def crear_sesion(usuario_id):
    token = secrets.token_urlsafe(32)
    expira_en = (datetime.now() + timedelta(days=DURACION_SESION_DIAS)).isoformat()
    database.crear_sesion(token, usuario_id, expira_en)
    return token


def validar_sesion(token):
    """Devuelve el usuario_id si la sesión es válida, o None si no existe
    o expiró (y la limpia en ese caso)."""
    if not token:
        return None
    fila = database.obtener_sesion(token)
    if fila is None:
        return None
    if datetime.fromisoformat(fila["expira_en"]) < datetime.now():
        database.eliminar_sesion(token)
        return None
    return fila["usuario_id"]


def cerrar_sesion(token):
    database.eliminar_sesion(token)


def esta_bloqueado(usuario):
    """usuario es el dict que devuelve database.obtener_usuario_por_*."""
    if not usuario.get("bloqueado_hasta"):
        return False
    return datetime.fromisoformat(usuario["bloqueado_hasta"]) > datetime.now()


def procesar_intento_fallido(usuario):
    intentos = usuario["intentos_fallidos"] + 1
    bloqueado_hasta = None
    if intentos >= MAX_INTENTOS_FALLIDOS:
        bloqueado_hasta = (datetime.now() + timedelta(minutes=DURACION_BLOQUEO_MINUTOS)).isoformat()
    database.registrar_intento_fallido(usuario["id"], bloqueado_hasta)
    return bloqueado_hasta is not None


def resetear_intentos_fallidos(usuario_id):
    database.resetear_intentos_fallidos(usuario_id)
