"""
Chatbot web con login — corre en la Raspberry Pi, habla con Ollama en la
laptop. Sirve tanto la API (registro/login/chat) como las páginas HTML.
"""

import re
from pathlib import Path
from fastapi import FastAPI, Request, Response, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

import database
import auth
import email_utils
import ollama_proxy
import config

app = FastAPI(title="Chatbot Local")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

database.inicializar_db()

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def _pagina(nombre):
    return HTMLResponse((FRONTEND_DIR / nombre).read_text(encoding="utf-8"))


def _usuario_actual(sesion: str | None):
    usuario_id = auth.validar_sesion(sesion)
    if usuario_id is None:
        return None
    return database.obtener_usuario_por_id(usuario_id)


# ---------- PÁGINAS ----------

@app.get("/", response_class=HTMLResponse)
def home(sesion: str | None = Cookie(default=None)):
    if _usuario_actual(sesion):
        return RedirectResponse("/chat")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def pagina_login(sesion: str | None = Cookie(default=None)):
    if _usuario_actual(sesion):
        return RedirectResponse("/chat")
    return _pagina("login.html")


@app.get("/register", response_class=HTMLResponse)
def pagina_registro(sesion: str | None = Cookie(default=None)):
    if _usuario_actual(sesion):
        return RedirectResponse("/chat")
    return _pagina("register.html")


@app.get("/chat", response_class=HTMLResponse)
def pagina_chat(sesion: str | None = Cookie(default=None)):
    if not _usuario_actual(sesion):
        return RedirectResponse("/login")
    return _pagina("chat.html")


@app.get("/verify")
def verificar_correo(token: str):
    usuario_id = auth.validar_token_verificacion(token)
    if usuario_id is None:
        return HTMLResponse("<h2>Link inválido o expirado.</h2><a href='/register'>Regístrate de nuevo</a>", status_code=400)
    database.marcar_verificado(usuario_id)
    return HTMLResponse("<h2>¡Cuenta verificada! Ya puedes iniciar sesión.</h2><a href='/login'>Ir a login</a>")


# ---------- API: REGISTRO ----------

class RegistroRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


@app.post("/api/register")
def api_registro(datos: RegistroRequest):
    if not USERNAME_REGEX.match(datos.username):
        raise HTTPException(400, "El usuario debe tener 3-20 caracteres (letras, números, guion bajo).")
    if len(datos.password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres.")
    if database.obtener_usuario_por_email(datos.email):
        raise HTTPException(400, "Ese correo ya está registrado.")
    if database.obtener_usuario_por_username(datos.username):
        raise HTTPException(400, "Ese nombre de usuario ya está en uso.")

    password_hash = auth.hashear_password(datos.password)
    usuario_id = database.crear_usuario(datos.username, datos.email, password_hash)
    if usuario_id is None:
        raise HTTPException(400, "No se pudo crear el usuario (correo o usuario duplicado).")

    token = auth.generar_token_verificacion(usuario_id)
    link = f"{config.URL_BASE}/verify?token={token}"
    email_utils.enviar_correo_verificacion(datos.email, datos.username, link)

    return {"ok": True, "mensaje": "Cuenta creada. Revisa tu correo para verificarla."}


# ---------- API: LOGIN / LOGOUT ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/api/login")
def api_login(datos: LoginRequest, response: Response):
    usuario = database.obtener_usuario_por_email(datos.email)
    if usuario is None:
        raise HTTPException(401, "Correo o contraseña incorrectos.")

    if auth.esta_bloqueado(usuario):
        raise HTTPException(429, "Demasiados intentos fallidos. Intenta de nuevo en unos minutos.")

    if not auth.verificar_password(datos.password, usuario["password_hash"]):
        auth.procesar_intento_fallido(usuario)
        raise HTTPException(401, "Correo o contraseña incorrectos.")

    if not usuario["verificado"]:
        raise HTTPException(403, "Verifica tu correo antes de iniciar sesión.")

    auth.resetear_intentos_fallidos(usuario["id"])
    token = auth.crear_sesion(usuario["id"])
    response.set_cookie(
        "sesion", token, httponly=True, secure=config.COOKIE_SECURE,
        samesite="lax", max_age=auth.DURACION_SESION_DIAS * 24 * 3600,
    )
    return {"ok": True, "username": usuario["username"]}


@app.post("/api/logout")
def api_logout(response: Response, sesion: str | None = Cookie(default=None)):
    if sesion:
        auth.cerrar_sesion(sesion)
    response.delete_cookie("sesion")
    return {"ok": True}


# ---------- API: CHAT ----------

class ChatRequest(BaseModel):
    mensajes: list[dict]  # [{"role": "user"/"assistant", "content": "..."}]
    conversacion_id: int


@app.post("/api/chat")
def api_chat(datos: ChatRequest, sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    if usuario is None:
        raise HTTPException(401, "Sesión inválida, inicia sesión de nuevo.")

    conversacion = database.obtener_conversacion(datos.conversacion_id)
    if conversacion is None or conversacion["usuario_id"] != usuario["id"]:
        raise HTTPException(404, "Esa conversación no existe.")

    if not ollama_proxy.dentro_del_limite(usuario["id"]):
        raise HTTPException(429, "Vas muy rápido — espera un momento antes de mandar otro mensaje.")

    # Guarda el mensaje del usuario (el último del arreglo que manda el
    # frontend — los anteriores ya se guardaron en turnos previos).
    if datos.mensajes:
        ultimo = datos.mensajes[-1]
        if ultimo.get("role") == "user":
            database.guardar_mensaje(datos.conversacion_id, "user", ultimo.get("content", ""))
            if not conversacion["titulo"]:
                titulo = ultimo.get("content", "")[:48]
                database.actualizar_titulo_conversacion(datos.conversacion_id, titulo)

    try:
        respuesta = ollama_proxy.chat(datos.mensajes)
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(503, "No se pudo conectar con el modelo — revisa que la laptop esté encendida y Ollama corriendo.")

    database.guardar_mensaje(datos.conversacion_id, "assistant", respuesta)
    database.tocar_conversacion(datos.conversacion_id)

    return {"respuesta": respuesta}


# ---------- API: CONVERSACIONES (como la barra lateral de ChatGPT/Claude) ----------

@app.get("/api/conversaciones")
def api_listar_conversaciones(sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    if usuario is None:
        raise HTTPException(401, "Sesión inválida, inicia sesión de nuevo.")
    return {"conversaciones": database.obtener_conversaciones(usuario["id"])}


@app.post("/api/conversaciones")
def api_crear_conversacion(sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    if usuario is None:
        raise HTTPException(401, "Sesión inválida, inicia sesión de nuevo.")
    nueva_id = database.crear_conversacion(usuario["id"])
    return {"id": nueva_id}


@app.get("/api/conversaciones/{conversacion_id}/mensajes")
def api_mensajes_conversacion(conversacion_id: int, sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    if usuario is None:
        raise HTTPException(401, "Sesión inválida, inicia sesión de nuevo.")
    conversacion = database.obtener_conversacion(conversacion_id)
    if conversacion is None or conversacion["usuario_id"] != usuario["id"]:
        raise HTTPException(404, "Esa conversación no existe.")
    mensajes = database.obtener_historial(conversacion_id)
    return {"historial": [{"role": m["rol"], "content": m["contenido"]} for m in mensajes]}


@app.delete("/api/conversaciones/{conversacion_id}")
def api_borrar_conversacion(conversacion_id: int, sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    if usuario is None:
        raise HTTPException(401, "Sesión inválida, inicia sesión de nuevo.")
    conversacion = database.obtener_conversacion(conversacion_id)
    if conversacion is None or conversacion["usuario_id"] != usuario["id"]:
        raise HTTPException(404, "Esa conversación no existe.")
    database.borrar_conversacion(conversacion_id)
    return {"ok": True}


@app.get("/api/estado")
def api_estado(sesion: str | None = Cookie(default=None)):
    usuario = _usuario_actual(sesion)
    return {
        "logueado": usuario is not None,
        "username": usuario["username"] if usuario else None,
        "ollama_disponible": ollama_proxy.ollama_disponible(),
    }
