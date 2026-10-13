"""
Módulo de memoria persistente para el asistente personal.

Estructura:
- hechos: datos personales del usuario, GLOBALES (aplican a todos los proyectos).
- proyectos: espacios de trabajo separados (ej: "Tesis", "Trabajo", "Personal").
- conversacion: historial de chat, cada mensaje pertenece a un proyecto.
- documentos / fragmentos: archivos subidos a un proyecto, troceados en fragmentos
  con su embedding (vector numérico) para búsqueda semántica local.
- pendientes: tareas, con fecha opcional de recordatorio.
"""

import sqlite3
import os
import json
import difflib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asistente.db")

PROYECTO_GENERAL_NOMBRE = "General"


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    """Crea todas las tablas si no existen, y asegura que exista el proyecto General."""
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hechos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT,
            contenido TEXT UNIQUE,
            creado_en TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            creado_en TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER,
            rol TEXT,
            contenido TEXT,
            creado_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS preguntas_hechas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta TEXT UNIQUE,
            creado_en TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER,
            contenido TEXT,
            estado TEXT DEFAULT 'pendiente',
            fecha_recordatorio TEXT,
            notificado INTEGER DEFAULT 0,
            creado_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER,
            nombre_archivo TEXT,
            agregado_en TEXT,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fragmentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento_id INTEGER,
            proyecto_id INTEGER,
            contenido TEXT,
            embedding TEXT,
            FOREIGN KEY (documento_id) REFERENCES documentos (id),
            FOREIGN KEY (proyecto_id) REFERENCES proyectos (id)
        )
    """)

    conn.commit()

    # Asegurar que exista el proyecto General (proyecto por defecto)
    cursor.execute("SELECT id FROM proyectos WHERE nombre = ?", (PROYECTO_GENERAL_NOMBRE,))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO proyectos (nombre, creado_en) VALUES (?, ?)",
            (PROYECTO_GENERAL_NOMBRE, datetime.now().isoformat()),
        )
        conn.commit()

    conn.close()


# ---------- HECHOS (globales sobre el usuario) ----------

def guardar_hecho(categoria, contenido):
    """Guarda un hecho nuevo. Devuelve su id si se guardó, o None si ya
    existía algo prácticamente igual (exacto o muy similar en la misma
    categoría) — esto evita que la memoria se llene de casi-duplicados con
    el tiempo (ej. 'trabaja en una tienda' guardado varias veces con
    ligeras variaciones por cómo se transcribió cada vez)."""
    conn = conectar()
    cursor = conn.cursor()
    contenido = contenido.strip()

    cursor.execute("SELECT contenido FROM hechos WHERE categoria = ?", (categoria,))
    for fila in cursor.fetchall():
        similitud = difflib.SequenceMatcher(None, fila["contenido"].lower(), contenido.lower()).ratio()
        if similitud > 0.85:
            conn.close()
            return None

    try:
        cursor.execute(
            "INSERT INTO hechos (categoria, contenido, creado_en) VALUES (?, ?, ?)",
            (categoria, contenido, datetime.now().isoformat()),
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        conn.close()
        return nuevo_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def obtener_hechos(limite=None):
    """Por defecto devuelve todos. Pasar un límite (ej. los últimos 40)
    evita que el prompt del modelo crezca sin control con el tiempo, lo
    cual diluye su atención y puede hacer que las respuestas se sientan
    más incoherentes cuanta más memoria se acumula."""
    conn = conectar()
    cursor = conn.cursor()
    if limite is None:
        cursor.execute("SELECT categoria, contenido FROM hechos ORDER BY creado_en")
    else:
        cursor.execute(
            "SELECT categoria, contenido FROM hechos ORDER BY creado_en DESC LIMIT ?", (limite,)
        )
    filas = cursor.fetchall()
    conn.close()
    filas = list(reversed(filas)) if limite is not None else filas
    return [f"[{fila['categoria']}] {fila['contenido']}" for fila in filas]


def eliminar_hecho(hecho_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hechos WHERE id = ?", (hecho_id,))
    afectadas = cursor.rowcount
    conn.commit()
    conn.close()
    return afectadas > 0


def eliminar_hechos_por_texto(consulta):
    """Borra todos los hechos cuyo contenido contenga la consulta (sin
    importar mayúsculas). Devuelve la lista de contenidos que se borraron,
    para poder confirmarle al usuario qué se olvidó exactamente."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, contenido FROM hechos WHERE LOWER(contenido) LIKE ?", (f"%{consulta.lower()}%",))
    encontrados = cursor.fetchall()
    for fila in encontrados:
        cursor.execute("DELETE FROM hechos WHERE id = ?", (fila["id"],))
    conn.commit()
    conn.close()
    return [fila["contenido"] for fila in encontrados]


def obtener_hechos_completos():
    """Igual que obtener_hechos, pero con id/categoria/contenido separados —
    para la visualización de memoria, que necesita datos reales por nodo."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, categoria, contenido, creado_en FROM hechos ORDER BY creado_en")
    filas = cursor.fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


# ---------- PROYECTOS ----------

def crear_proyecto(nombre):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO proyectos (nombre, creado_en) VALUES (?, ?)",
            (nombre, datetime.now().isoformat()),
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        nuevo_id = None
    conn.close()
    return nuevo_id


def obtener_proyectos():
    """Devuelve lista de tuplas (id, nombre), con 'General' siempre primero."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre FROM proyectos ORDER BY (nombre != ?), creado_en", (PROYECTO_GENERAL_NOMBRE,))
    filas = cursor.fetchall()
    conn.close()
    return [(fila["id"], fila["nombre"]) for fila in filas]


def obtener_id_proyecto_general():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM proyectos WHERE nombre = ?", (PROYECTO_GENERAL_NOMBRE,))
    fila = cursor.fetchone()
    conn.close()
    return fila["id"] if fila else None


def eliminar_proyecto(proyecto_id):
    """Elimina un proyecto y todo lo asociado (conversación, documentos, fragmentos, pendientes)."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversacion WHERE proyecto_id = ?", (proyecto_id,))
    cursor.execute("DELETE FROM fragmentos WHERE proyecto_id = ?", (proyecto_id,))
    cursor.execute("DELETE FROM documentos WHERE proyecto_id = ?", (proyecto_id,))
    cursor.execute("DELETE FROM pendientes WHERE proyecto_id = ?", (proyecto_id,))
    cursor.execute("DELETE FROM proyectos WHERE id = ?", (proyecto_id,))
    conn.commit()
    conn.close()


# ---------- CONVERSACIÓN (por proyecto) ----------

def guardar_mensaje(proyecto_id, rol, contenido):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversacion (proyecto_id, rol, contenido, creado_en) VALUES (?, ?, ?, ?)",
        (proyecto_id, rol, contenido, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def obtener_historial_reciente(proyecto_id, limite=12):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT rol, contenido FROM conversacion WHERE proyecto_id = ? ORDER BY id DESC LIMIT ?",
        (proyecto_id, limite),
    )
    filas = cursor.fetchall()
    conn.close()
    filas = list(reversed(filas))
    return [{"role": fila["rol"], "content": fila["contenido"]} for fila in filas]


def obtener_historial_completo(proyecto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT rol, contenido, creado_en FROM conversacion WHERE proyecto_id = ? ORDER BY id",
        (proyecto_id,),
    )
    filas = cursor.fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def contar_mensajes_usuario(proyecto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as total FROM conversacion WHERE rol = 'user' AND proyecto_id = ?",
        (proyecto_id,),
    )
    total = cursor.fetchone()["total"]
    conn.close()
    return total


# ---------- PREGUNTAS YA HECHAS (globales) ----------

def pregunta_ya_hecha(pregunta):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM preguntas_hechas WHERE pregunta = ?", (pregunta,))
    existe = cursor.fetchone() is not None
    conn.close()
    return existe


def marcar_pregunta_hecha(pregunta):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO preguntas_hechas (pregunta, creado_en) VALUES (?, ?)",
            (pregunta, datetime.now().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


# ---------- PENDIENTES (por proyecto, con recordatorio opcional) ----------

def agregar_pendiente(proyecto_id, contenido, fecha_recordatorio=None):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pendientes (proyecto_id, contenido, estado, fecha_recordatorio, notificado, creado_en)
           VALUES (?, ?, 'pendiente', ?, 0, ?)""",
        (proyecto_id, contenido, fecha_recordatorio, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def obtener_pendientes_activos(proyecto_id=None):
    """Si proyecto_id es None, devuelve pendientes de TODOS los proyectos (para el hilo de recordatorios)."""
    conn = conectar()
    cursor = conn.cursor()
    if proyecto_id is None:
        cursor.execute(
            "SELECT id, contenido, fecha_recordatorio FROM pendientes WHERE estado = 'pendiente' ORDER BY id"
        )
    else:
        cursor.execute(
            "SELECT id, contenido, fecha_recordatorio FROM pendientes WHERE estado = 'pendiente' AND proyecto_id = ? ORDER BY id",
            (proyecto_id,),
        )
    filas = cursor.fetchall()
    conn.close()
    return [(fila["id"], fila["contenido"], fila["fecha_recordatorio"]) for fila in filas]


def completar_pendiente(pendiente_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE pendientes SET estado = 'completado' WHERE id = ?", (pendiente_id,))
    afectadas = cursor.rowcount
    conn.commit()
    conn.close()
    return afectadas > 0


def eliminar_pendiente(pendiente_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pendientes WHERE id = ?", (pendiente_id,))
    afectadas = cursor.rowcount
    conn.commit()
    conn.close()
    return afectadas > 0


def eliminar_pendientes_por_texto(proyecto_id, consulta):
    """Borra pendientes ACTIVOS cuyo contenido contenga la consulta. Devuelve
    la lista de contenidos borrados, para confirmarle al usuario cuáles."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, contenido FROM pendientes
           WHERE proyecto_id = ? AND estado = 'pendiente' AND LOWER(contenido) LIKE ?""",
        (proyecto_id, f"%{consulta.lower()}%"),
    )
    encontrados = cursor.fetchall()
    for fila in encontrados:
        cursor.execute("DELETE FROM pendientes WHERE id = ?", (fila["id"],))
    conn.commit()
    conn.close()
    return [fila["contenido"] for fila in encontrados]


def obtener_recordatorios_pendientes_de_notificar(ahora_iso):
    """Pendientes con fecha_recordatorio ya cumplida, activos, y no notificados aún."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, contenido FROM pendientes
           WHERE estado = 'pendiente' AND notificado = 0
           AND fecha_recordatorio IS NOT NULL AND fecha_recordatorio <= ?""",
        (ahora_iso,),
    )
    filas = cursor.fetchall()
    conn.close()
    return [(fila["id"], fila["contenido"]) for fila in filas]


def marcar_recordatorio_notificado(pendiente_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE pendientes SET notificado = 1 WHERE id = ?", (pendiente_id,))
    conn.commit()
    conn.close()


def reprogramar_pendiente(pendiente_id, nueva_fecha_iso):
    """Cambia la fecha de recordatorio de un pendiente y lo vuelve a dejar
    'sin notificar', para que el hilo de recordatorios lo dispare de nuevo
    en el nuevo horario (usado cuando el usuario responde 'recuérdamelo más tarde')."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE pendientes SET fecha_recordatorio = ?, notificado = 0 WHERE id = ?",
        (nueva_fecha_iso, pendiente_id),
    )
    conn.commit()
    conn.close()


def obtener_pendiente(pendiente_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, contenido, estado, fecha_recordatorio FROM pendientes WHERE id = ?", (pendiente_id,)
    )
    fila = cursor.fetchone()
    conn.close()
    return dict(fila) if fila else None


# ---------- DOCUMENTOS Y FRAGMENTOS (para búsqueda semántica) ----------

def agregar_documento(proyecto_id, nombre_archivo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO documentos (proyecto_id, nombre_archivo, agregado_en) VALUES (?, ?, ?)",
        (proyecto_id, nombre_archivo, datetime.now().isoformat()),
    )
    conn.commit()
    documento_id = cursor.lastrowid
    conn.close()
    return documento_id


def obtener_documentos(proyecto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, nombre_archivo, agregado_en FROM documentos WHERE proyecto_id = ? ORDER BY agregado_en",
        (proyecto_id,),
    )
    filas = cursor.fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def guardar_fragmento(documento_id, proyecto_id, contenido, embedding):
    """embedding es una lista de floats; se guarda serializada como JSON."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fragmentos (documento_id, proyecto_id, contenido, embedding) VALUES (?, ?, ?, ?)",
        (documento_id, proyecto_id, contenido, json.dumps(embedding)),
    )
    conn.commit()
    conn.close()


def obtener_fragmentos_de_proyecto(proyecto_id):
    """Devuelve lista de (contenido, embedding_como_lista) para un proyecto."""
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT contenido, embedding FROM fragmentos WHERE proyecto_id = ?", (proyecto_id,)
    )
    filas = cursor.fetchall()
    conn.close()
    return [(fila["contenido"], json.loads(fila["embedding"])) for fila in filas]
