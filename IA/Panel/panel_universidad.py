"""
Panel de control del proyecto universitario (clúster de edge computing)
— VERSIÓN LINUX (Debian). Arranca, detiene y valida cada servicio desde
una sola página web.

Corre en la MINI PC, dentro del entorno virtual del proyecto:
  ~/IA/venv/bin/python panel_universidad.py      (o ejecuta abrir_panel.sh)

Necesita (ya incluidos en el venv): flask, paramiko, requests
y la llave SSH hacia la Pi configurada (ssh-copy-id), para controlar la Pi.
"""

import os
import subprocess
import sys
import threading
import webbrowser

import requests
from flask import Flask, jsonify, render_template_string

try:
    import paramiko
except ImportError:
    paramiko = None

# ---------------- CONFIGURACIÓN — AJUSTA SI ALGO CAMBIA ----------------
BASE = os.environ.get("PROYECTO_BASE", os.path.expanduser("~/IA"))
RUTA_CLUSTER = os.path.join(BASE, "cluster")
RUTA_CHATBOT = os.path.join(BASE, "chatbot_web", "backend")
RUTA_SERVIDOR_LAPTOP = os.path.join(BASE, "servidor_laptop")
RUTA_LOGS = os.path.join(BASE, "logs")
PYTHON = sys.executable  # el Python del venv desde el que corre este panel
PI_HOST = "192.168.10.2"
PI_USUARIO = "admin"
URL_FUNNEL = "https://umg.tail3c471d.ts.net"
MINI_PC_IP = os.environ.get("MINI_PC_IP", "192.168.10.1")
# -------------------------------------------------------------------

# Servicios que corren en ESTA máquina. "patron" sirve para encontrarlos y
# detenerlos aunque los haya arrancado otra cosa (otra terminal, el panel
# anterior, etc.), no solo los que lanzó este panel.
SERVICIOS_LOCALES = {
    "balanceador": {
        "cmd": [PYTHON, "balanceador.py"],
        "cwd": RUTA_CLUSTER,
        "patron": "balanceador.py",
    },
    "chatbot": {
        "cmd": [PYTHON, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        "cwd": RUTA_CHATBOT,
        "patron": "uvicorn main:app --host 0.0.0.0 --port 8000",
    },
    "servidor_laptop": {
        "cmd": [PYTHON, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"],
        "cwd": RUTA_SERVIDOR_LAPTOP,
        "patron": "uvicorn main:app --host 0.0.0.0 --port 8100",
    },
}

app = Flask(__name__)
_procesos_locales = {}  # nombre -> objeto Popen, para poder detenerlos despues


def _conectar_ssh():
    if paramiko is None:
        raise RuntimeError("Falta instalar paramiko: pip install paramiko")
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(PI_HOST, username=PI_USUARIO, timeout=6)
    return cliente


def _ssh_en_fondo(comando, nombre_log):
    cliente = _conectar_ssh()
    ruta_log = f"/tmp/panel_log_{nombre_log}.txt"
    comando_completo = f"nohup bash -lc {comando!r} > {ruta_log} 2>&1 & disown"
    cliente.exec_command(comando_completo)
    cliente.close()


def _ssh_directo(comando):
    """Ejecuta un comando y espera su salida (para detener cosas, no para
    dejarlas corriendo)."""
    cliente = _conectar_ssh()
    _stdin, stdout, stderr = cliente.exec_command(comando)
    salida = stdout.read().decode()
    error = stderr.read().decode()
    cliente.close()
    return salida, error


def _esta_corriendo(patron):
    return subprocess.run(["pgrep", "-f", patron], capture_output=True).returncode == 0


def _arrancar_local(nombre):
    """Lanza el servicio en segundo plano y guarda su salida en
    ~/IA/logs/<nombre>.log (útil para revisar errores y para la demo)."""
    servicio = SERVICIOS_LOCALES[nombre]
    if _esta_corriendo(servicio["patron"]):
        return False, "Ya está corriendo."
    os.makedirs(RUTA_LOGS, exist_ok=True)
    ruta_log = os.path.join(RUTA_LOGS, f"{nombre}.log")
    with open(ruta_log, "ab") as log:
        proceso = subprocess.Popen(
            servicio["cmd"], cwd=servicio["cwd"],
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,  # sigue vivo aunque se cierre el panel
        )
    _procesos_locales[nombre] = proceso
    return True, f"Arrancando... (registro en {ruta_log})"


def _detener_local(nombre):
    """Detiene el servicio por el proceso que lanzó este panel y, además,
    por su patrón — así funciona aunque lo haya arrancado otra cosa."""
    servicio = SERVICIOS_LOCALES[nombre]
    proceso = _procesos_locales.pop(nombre, None)
    if proceso is not None and proceso.poll() is None:
        proceso.terminate()
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()
    resultado = subprocess.run(["pkill", "-f", servicio["patron"]], capture_output=True)
    if proceso is None and resultado.returncode != 0:
        return False, "No encontré ese servicio corriendo."
    return True, "Detenido."


# ---------------- ACCIONES: ARRANCAR ----------------

@app.route("/accion/balanceador", methods=["POST"])
def accion_balanceador():
    try:
        ok, mensaje = _arrancar_local("balanceador")
        return jsonify(ok=ok, mensaje=mensaje)
    except Exception as e:
        return jsonify(ok=False, mensaje=str(e))


@app.route("/accion/chatbot", methods=["POST"])
def accion_chatbot():
    try:
        ok, mensaje = _arrancar_local("chatbot")
        return jsonify(ok=ok, mensaje=mensaje)
    except Exception as e:
        return jsonify(ok=False, mensaje=str(e))


@app.route("/accion/servidor_laptop", methods=["POST"])
def accion_servidor_laptop():
    try:
        ok, mensaje = _arrancar_local("servidor_laptop")
        return jsonify(ok=ok, mensaje=mensaje)
    except Exception as e:
        return jsonify(ok=False, mensaje=str(e))


@app.route("/accion/funnel", methods=["POST"])
def accion_funnel():
    try:
        cliente = _conectar_ssh()
        cliente.exec_command("sudo tailscale serve reset")
        cliente.close()
        _ssh_en_fondo(f"sudo tailscale funnel http://{MINI_PC_IP}:8000", "funnel")
        return jsonify(ok=True, mensaje="Activando Funnel (puede tardar ~1-2 min en propagarse)...")
    except Exception as e:
        return jsonify(ok=False, mensaje=f"Error de SSH: {e}")


@app.route("/accion/cliente_voz", methods=["POST"])
def accion_cliente_voz():
    try:
        _ssh_en_fondo("export DISPLAY=:0; cd ~/cliente_pi && python3 asistente_cliente.py", "cliente_voz")
        return jsonify(ok=True, mensaje="Comando enviado — revisa la pantalla física de la Pi.")
    except Exception as e:
        return jsonify(ok=False, mensaje=f"Error de SSH: {e}")


# ---------------- ACCIONES: DETENER ----------------

@app.route("/detener/balanceador", methods=["POST"])
def detener_balanceador():
    ok, mensaje = _detener_local("balanceador")
    return jsonify(ok=ok, mensaje=mensaje)


@app.route("/detener/chatbot", methods=["POST"])
def detener_chatbot():
    ok, mensaje = _detener_local("chatbot")
    return jsonify(ok=ok, mensaje=mensaje)


@app.route("/detener/servidor_laptop", methods=["POST"])
def detener_servidor_laptop():
    ok, mensaje = _detener_local("servidor_laptop")
    return jsonify(ok=ok, mensaje=mensaje)


@app.route("/detener/funnel", methods=["POST"])
def detener_funnel():
    try:
        _salida, _error = _ssh_directo("sudo tailscale serve reset")
        return jsonify(ok=True, mensaje="Funnel desactivado.")
    except Exception as e:
        return jsonify(ok=False, mensaje=f"Error de SSH: {e}")


@app.route("/detener/cliente_voz", methods=["POST"])
def detener_cliente_voz():
    try:
        _salida, _error = _ssh_directo("pkill -f asistente_cliente.py")
        return jsonify(ok=True, mensaje="Cliente de voz detenido en la Pi.")
    except Exception as e:
        return jsonify(ok=False, mensaje=f"Error de SSH: {e}")


# ---------------- VALIDAR ----------------

@app.route("/validar/balanceador")
def validar_balanceador():
    try:
        r = requests.get("http://localhost:5000/salud", timeout=3)
        return jsonify(activo=r.ok, detalle=r.json() if r.ok else None)
    except Exception:
        return jsonify(activo=False)


@app.route("/validar/chatbot")
def validar_chatbot():
    try:
        r = requests.get(f"http://{MINI_PC_IP}:8000/login", timeout=3)
        return jsonify(activo=r.status_code == 200)
    except Exception:
        return jsonify(activo=False)


@app.route("/validar/servidor_laptop")
def validar_servidor_laptop():
    try:
        r = requests.get("http://localhost:8100/api/salud", timeout=3)
        return jsonify(activo=r.ok, detalle=r.json() if r.ok else None)
    except Exception:
        return jsonify(activo=False)


@app.route("/validar/funnel")
def validar_funnel():
    try:
        r = requests.get(f"{URL_FUNNEL}/login", timeout=6)
        return jsonify(activo=r.status_code == 200)
    except Exception:
        return jsonify(activo=False)


@app.route("/validar/cliente_voz")
def validar_cliente_voz():
    try:
        if paramiko is None:
            raise RuntimeError("falta paramiko")
        cliente = _conectar_ssh()
        _stdin, stdout, _stderr = cliente.exec_command("pgrep -f asistente_cliente.py")
        salida = stdout.read().decode().strip()
        cliente.close()
        return jsonify(activo=bool(salida))
    except Exception:
        return jsonify(activo=False)


HTML_PAGINA = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Panel — Proyecto Universitario</title>
<style>
  * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", Arial, sans-serif; }
  body { background: #0e0e10; color: #e8e8ea; margin: 0; padding: 30px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .subtitulo { color: #97979f; font-size: 13px; margin-bottom: 20px; }
  h2.grupo { font-size: 14px; color: #a594ff; text-transform: uppercase; letter-spacing: 0.5px; margin: 28px 0 10px; }
  .tarjeta {
    background: #17171a; border: 1px solid #2a2a2f; border-radius: 14px;
    padding: 16px 20px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between;
  }
  .info { display: flex; align-items: center; gap: 12px; }
  .punto { width: 11px; height: 11px; border-radius: 50%; background: #555; flex-shrink: 0; transition: background 0.2s; }
  .punto.activo { background: #3ddc73; }
  .punto.inactivo { background: #ff5c5c; }
  .nombre { font-size: 15px; font-weight: 600; }
  .estado-texto { font-size: 12.5px; color: #97979f; }
  .botones { display: flex; gap: 8px; }
  button {
    background: #6d5aff; color: white; border: none; border-radius: 8px;
    padding: 9px 14px; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  button:hover { background: #5a47e8; }
  button.secundario { background: #26262c; }
  button.secundario:hover { background: #33333a; }
  button.peligro { background: #3a2222; color: #ff8080; }
  button.peligro:hover { background: #4a2a2a; }
  .mensaje { font-size: 12.5px; color: #97979f; margin-top: 4px; max-width: 300px; }
</style>
</head>
<body>
  <h1>Panel — Proyecto Universitario</h1>
  <div class="subtitulo">Clúster de edge computing — arranca, detén y valida cada servicio.</div>
  <div id="contenedor"></div>

<script>
const GRUPOS = [
  { titulo: "Compartido (clúster)", servicios: [
    { id: "balanceador", nombre: "Balanceador de carga", puedeArrancar: true },
  ]},
  { titulo: "Chatbot web", servicios: [
    { id: "chatbot", nombre: "Chatbot web (puerto 8000)", puedeArrancar: true },
    { id: "funnel", nombre: "Link público (Tailscale Funnel)", puedeArrancar: true },
  ]},
  { titulo: "CORE (voz + cara)", servicios: [
    { id: "servidor_laptop", nombre: "Servidor de CORE (puerto 8100)", puedeArrancar: true },
    { id: "cliente_voz", nombre: "Cliente de voz (Pi)", puedeArrancar: true },
  ]},
];

const contenedor = document.getElementById("contenedor");

function crearTarjeta(s) {
  const div = document.createElement("div");
  div.className = "tarjeta";
  div.innerHTML = `
    <div class="info">
      <div class="punto" id="punto-${s.id}"></div>
      <div>
        <div class="nombre">${s.nombre}</div>
        <div class="estado-texto" id="estado-${s.id}">Revisando...</div>
        <div class="mensaje" id="mensaje-${s.id}"></div>
      </div>
    </div>
    <div class="botones">
      <button onclick="arrancar('${s.id}')">Arrancar</button>
      <button class="peligro" onclick="detener('${s.id}')">Detener</button>
      <button class="secundario" onclick="validar('${s.id}')">Validar</button>
    </div>
  `;
  contenedor.appendChild(div);
}

GRUPOS.forEach((grupo) => {
  const titulo = document.createElement("h2");
  titulo.className = "grupo";
  titulo.textContent = grupo.titulo;
  contenedor.appendChild(titulo);
  grupo.servicios.forEach(crearTarjeta);
});

async function validar(id) {
  document.getElementById(`estado-${id}`).textContent = "Revisando...";
  try {
    const resp = await fetch(`/validar/${id}`);
    const datos = await resp.json();
    const punto = document.getElementById(`punto-${id}`);
    const estado = document.getElementById(`estado-${id}`);
    if (datos.activo) {
      punto.className = "punto activo";
      estado.textContent = "Activo";
    } else {
      punto.className = "punto inactivo";
      estado.textContent = "No responde";
    }
  } catch (err) {
    document.getElementById(`estado-${id}`).textContent = "Error al validar";
  }
}

async function arrancar(id) {
  document.getElementById(`mensaje-${id}`).textContent = "Enviando...";
  try {
    const resp = await fetch(`/accion/${id}`, { method: "POST" });
    const datos = await resp.json();
    document.getElementById(`mensaje-${id}`).textContent = datos.mensaje;
    setTimeout(() => validar(id), 4000);
  } catch (err) {
    document.getElementById(`mensaje-${id}`).textContent = "No se pudo enviar la acción.";
  }
}

async function detener(id) {
  document.getElementById(`mensaje-${id}`).textContent = "Deteniendo...";
  try {
    const resp = await fetch(`/detener/${id}`, { method: "POST" });
    const datos = await resp.json();
    document.getElementById(`mensaje-${id}`).textContent = datos.mensaje;
    setTimeout(() => validar(id), 2000);
  } catch (err) {
    document.getElementById(`mensaje-${id}`).textContent = "No se pudo detener.";
  }
}

GRUPOS.forEach((g) => g.servicios.forEach((s) => validar(s.id)));
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGINA)


if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5050")).start()
    app.run(host="127.0.0.1", port=5050)
