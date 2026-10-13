"""
Base de datos SQLite para el chatbot web: usuarios, verificación de correo
y sesiones de login. Vive en la Raspberry Pi junto al resto del backend.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatbot_users.db")


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            verificado INTEGER DEFAULT 0,
            intentos_fallidos INTEGER DEFAULT 0,
            bloqueado_hasta TEXT,
            creado_en TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tokens_verificacion (
            token TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            expira_en TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            token TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            creado_en TEXT NOT NULL,
            expira_en TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            titulo TEXT,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversacion_id INTEGER NOT NULL,
            rol TEXT NOT NULL,
            contenido TEXT NOT NULL,
            creado_en TEXT NOT NULL,
            FOREIGN KEY (conversacion_id) REFERENCES conversaciones (id)
        )
    """)

    conn.commit()
    conn.close()


# ---------- USUARIOS ----------

def crear_usuario(username, email, password_hash):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (username, email, password_hash, verificado, creado_en) VALUES (?, ?, ?, 0, ?)",
            (username, email, password_hash, datetime.now().isoformat()),
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        conn.close()
        return nuevo_id
    except sqlite3.IntegrityError:
        conn.close()
        return None  # username o email ya existen


def obtener_usuario_por_email(email):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def obtener_usuario_por_username(username):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def obtener_usuario_por_id(usuario_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def marcar_verificado(usuario_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET verificado = 1 WHERE id = ?", (usuario_id,))
    conn.commit()
    conn.close()


def registrar_intento_fallido(usuario_id, bloqueado_hasta=None):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios SET intentos_fallidos = intentos_fallidos + 1, bloqueado_hasta = ? WHERE id = ?",
        (bloqueado_hasta, usuario_id),
    )
    conn.commit()
    conn.close()


def resetear_intentos_fallidos(usuario_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?", (usuario_id,)
    )
    conn.commit()
    conn.close()


# ---------- TOKENS DE VERIFICACIÓN DE CORREO ----------

def guardar_token_verificacion(token, usuario_id, expira_en_iso):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tokens_verificacion (token, usuario_id, expira_en) VALUES (?, ?, ?)",
        (token, usuario_id, expira_en_iso),
    )
    conn.commit()
    conn.close()


def obtener_token_verificacion(token):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens_verificacion WHERE token = ?", (token,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def eliminar_token_verificacion(token):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tokens_verificacion WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ---------- SESIONES ----------

def crear_sesion(token, usuario_id, expira_en_iso):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sesiones (token, usuario_id, creado_en, expira_en) VALUES (?, ?, ?, ?)",
        (token, usuario_id, datetime.now().isoformat(), expira_en_iso),
    )
    conn.commit()
    conn.close()


def obtener_sesion(token):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sesiones WHERE token = ?", (token,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def eliminar_sesion(token):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sesiones WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ---------- CONVERSACIONES (una por "chat" separado, como ChatGPT/Claude) ----------

def crear_conversacion(usuario_id, titulo=None):
    conn = conectar()
    cursor = conn.cursor()
    ahora = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO conversaciones (usuario_id, titulo, creado_en, actualizado_en) VALUES (?, ?, ?, ?)",
        (usuario_id, titulo, ahora, ahora),
    )
    conn.commit()
    nueva_id = cursor.lastrowid
    conn.close()
    return nueva_id


def obtener_conversaciones(usuario_id):
    """Lista de conversaciones del usuario, la más reciente primero (por
    fecha de actualización, no de creación — para que la que acabas de
    usar suba al principio, como en ChatGPT/Claude)."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, titulo, creado_en, actualizado_en FROM conversaciones "
        "WHERE usuario_id = ? ORDER BY actualizado_en DESC",
        (usuario_id,),
    )
    filas = cursor.fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def obtener_conversacion(conversacion_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversaciones WHERE id = ?", (conversacion_id,))
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


def actualizar_titulo_conversacion(conversacion_id, titulo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE conversaciones SET titulo = ? WHERE id = ?", (titulo, conversacion_id))
    conn.commit()
    conn.close()


def tocar_conversacion(conversacion_id):
    """Actualiza 'actualizado_en' a ahora — se llama cada vez que se manda
    un mensaje nuevo, para que esa conversación suba al principio de la lista."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE conversaciones SET actualizado_en = ? WHERE id = ?",
        (datetime.now().isoformat(), conversacion_id),
    )
    conn.commit()
    conn.close()


def borrar_conversacion(conversacion_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mensajes WHERE conversacion_id = ?", (conversacion_id,))
    cursor.execute("DELETE FROM conversaciones WHERE id = ?", (conversacion_id,))
    conn.commit()
    conn.close()


# ---------- MENSAJES (dentro de una conversación) ----------

def guardar_mensaje(conversacion_id, rol, contenido):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO mensajes (conversacion_id, rol, contenido, creado_en) VALUES (?, ?, ?, ?)",
        (conversacion_id, rol, contenido, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def obtener_historial(conversacion_id, limite=200):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT rol, contenido, creado_en FROM mensajes WHERE conversacion_id = ? ORDER BY id DESC LIMIT ?",
        (conversacion_id, limite),
    )
    filas = list(reversed(cursor.fetchall()))
    conn.close()
    return [dict(fila) for fila in filas]
