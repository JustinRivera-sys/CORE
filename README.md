
# CORE — Asistente de IA local en un clúster de edge computing

> **C**onfidencialidad · **O**peración local · **R**esiliencia · **E**dge
>
> *A local, offline AI assistant running on a two-node edge cluster (mini PC + Raspberry Pi) with automatic failover.*

![Debian](https://img.shields.io/badge/Debian-13-A81D33?logo=debian&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![IA](https://img.shields.io/badge/IA-100%25_local-brightgreen)
![GPU](https://img.shields.io/badge/GPU-no_requerida-blue)

CORE es un asistente de inteligencia artificial que corre **por completo dentro de la red de la organización**: sin nube, sin GPU y sin enviar preguntas a ningún proveedor externo. Se ejecuta sobre dos equipos pequeños (una mini PC y una Raspberry Pi) conectados por un switch Gigabit, y sigue respondiendo aunque uno de los dos se caiga.

Incluye un **chat web** con usuarios y un **asistente de voz** con cara animada.

---

## Tabla de contenido

- [El problema](#el-problema)
- [La solución](#la-solución)
- [Arquitectura](#arquitectura)
- [Cómo funciona una petición](#cómo-funciona-una-petición)
- [Tolerancia a fallos](#tolerancia-a-fallos)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Probar la tolerancia a fallos](#probar-la-tolerancia-a-fallos)
- [Seguridad y confidencialidad](#seguridad-y-confidencialidad)
- [Rendimiento](#rendimiento)
- [Limitaciones y trabajo futuro](#limitaciones-y-trabajo-futuro)
- [Contexto académico](#contexto-académico)
- [Autores](#autores)
- [Licencia](#licencia)

---

## El problema

Una empresa que quiere usar IA generativa con información interna (contratos, datos de clientes, procedimientos) se enfrenta a cuatro riesgos cuando usa servicios en la nube:

- **Confidencialidad:** cada pregunta, y lo que el empleado pegue en ella, sale de la red de la empresa y queda en servidores de un tercero.
- **Cumplimiento:** las políticas internas y las normas de protección de datos pueden prohibir enviar cierta información a terceros.
- **Dependencia de internet:** en una sucursal con conexión mala o inexistente, el asistente deja de funcionar.
- **Punto único de falla:** si el único servidor local se cae, se pierde el servicio.

## La solución

Llevar la IA al borde (*edge*), dentro de la red de la organización:

- Un **modelo de lenguaje pequeño** (`llama3.2:1b`, cuantizado a 4 bits) ejecutado localmente con [Ollama](https://ollama.com).
- **Transcripción de voz** (Whisper) y **síntesis de voz** (Piper) también locales.
- **Dos nodos** de bajo consumo y un **balanceador** propio que redirige las peticiones al segundo nodo si el primero falla.

## Arquitectura

```
                  ┌───────────────────────────────────────────┐
 Usuario  ───────►│ NODO MAESTRO · Mini PC · 192.168.10.1     │
 (texto / voz)    │  • Balanceador de carga      (:5000)      │
                  │  • Chat web                  (:8000)      │
                  │  • Servidor de voz CORE      (:8100)      │
                  │  • Ollama                    (:11434)     │
                  └──────────────────┬────────────────────────┘
                                     │  solo si el maestro falla
                                     ▼
                  ┌───────────────────────────────────────────┐
                  │ NODO DE RESPALDO · Raspberry Pi           │
                  │ 192.168.10.2                              │
                  │  • Ollama                    (:11434)     │
                  │  • Cliente de voz con cara animada        │
                  └───────────────────────────────────────────┘
        Ambos nodos unidos por un switch Gigabit · subred 192.168.10.0/24
```

| Componente | Tecnología | Función |
|---|---|---|
| Inferencia | Ollama + `llama3.2:1b-instruct-q4_K_M` | Genera las respuestas, 100 % local |
| Balanceador | Python + Flask | Punto de entrada único, redirección y tolerancia a fallos |
| Chat web | FastAPI + SQLite + bcrypt | Usuarios, conversaciones e interfaz web |
| Voz (entrada) | faster-whisper (CPU) | Transcripción de voz a texto |
| Voz (salida) | Piper TTS | Respuestas habladas |
| Cliente de voz | Python + customtkinter | Micrófono, bocinas y cara animada en la Raspberry Pi |
| Panel de control | Flask + paramiko | Arrancar, detener y validar servicios desde el navegador |

**Sistema operativo:** Debian 13 (trixie) en ambos nodos. Solo cambia la arquitectura del procesador (x86-64 en la mini PC, ARM64 en la Raspberry Pi).

## Cómo funciona una petición

**Por texto (chat web)**

1. El usuario escribe en la interfaz web.
2. El backend del chat envía la petición al balanceador (`:5000`).
3. El balanceador la manda a Ollama en la mini PC; si falla, la reintenta en la Raspberry Pi.
4. La respuesta regresa por la misma ruta hasta el navegador.

**Por voz (CORE)**

1. El micrófono de la Raspberry Pi captura el audio.
2. El audio se envía al servidor de voz (`:8100`) en la mini PC.
3. Whisper lo transcribe a texto (en CPU).
4. El texto pasa por el balanceador, igual que en el flujo de texto.
5. Piper convierte la respuesta en audio y la Raspberry Pi la reproduce junto con la animación de la cara.

## Tolerancia a fallos

El balanceador (`cluster/balanceador.py`) usa una estrategia de **maestro con respaldo**, no un reparto parejo:

- Toda petición nueva se intenta **primero en la mini PC**, el nodo más capaz.
- Si no responde en **40 segundos** o rechaza la conexión, se redirige automáticamente a la **Raspberry Pi**.
- Solo si fallan **todos** los nodos devuelve un error `503`.
- `GET /salud` reporta el estado de cada nodo.

Se eligió esta estrategia porque los dos nodos tienen capacidades muy distintas: alternar 50/50 haría que la Raspberry Pi, más lenta, retrasara la mitad de las respuestas.

Cuando el nodo maestro falla, el registro del balanceador muestra algo así:

```
[balanceador] AVISO: mini_pc no respondió (...) — redirigiendo al siguiente nodo del clúster
[balanceador] POST /api/chat -> raspberry_pi (X.XXs, status 200)
```

## Estructura del repositorio

```
.
├── cluster/             # Balanceador de carga (+ transcripcion.py)
├── servidor_laptop/     # Servidor de voz y lógica del asistente (FastAPI, :8100)
│   ├── main.py
│   ├── turno.py         # Decide qué responder en cada turno
│   ├── voz_servidor.py  # Whisper + Piper, en CPU
│   ├── ollama_client.py # Habla con el balanceador
│   ├── memoria.py       # Hechos y pendientes (SQLite)
│   └── voces/           # Modelo de voz de Piper (se descarga aparte)
├── chatbot_web/         # Chat web
│   ├── backend/         # API, autenticación y base de datos
│   ├── frontend/        # HTML, CSS y JavaScript
│   └── requirements.txt
├── cliente_pi/          # Cliente de voz con cara animada (corre en la Raspberry Pi)
└── Panel/               # Panel de control web y scripts de arranque
```

## Requisitos

**Hardware**

- Una mini PC x86-64 **sin GPU dedicada** (probado con Intel i5-10500T y 16 GB de RAM).
- Una Raspberry Pi con 4 GB de RAM.
- Un switch Gigabit Ethernet y dos cables de red.
- Solo para el asistente de voz: micrófono USB, bocinas y una pantalla en la Raspberry Pi.

**Software**

- Debian 13 (trixie) en ambos nodos.
- Python 3.13.
- [Ollama](https://ollama.com).

## Instalación

> Estos pasos asumen que el repositorio se clona en `~/IA` en la mini PC. Los scripts del panel usan esa ruta.

### 1. Red: IP fija en cada nodo

Sin servidor DHCP y sin puerta de enlace en la red del clúster.

| Nodo | IP |
|---|---|
| Mini PC | `192.168.10.1/24` |
| Raspberry Pi | `192.168.10.2/24` |

Ejemplo con NetworkManager (el nombre de la conexión puede variar; consúltalo con `nmcli connection show`):

```bash
sudo nmcli connection modify "Wired connection 1" \
  ipv4.method manual ipv4.addresses 192.168.10.1/24 ipv4.gateway "" ipv4.never-default yes
sudo nmcli connection up "Wired connection 1"
```

### 2. SSH sin contraseña de la mini PC a la Raspberry Pi

El panel de control lo necesita para manejar la Pi.

```bash
ssh-keygen -t ed25519
ssh-copy-id admin@192.168.10.2
```

### 3. Ollama y el modelo (en AMBOS nodos)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:1b-instruct-q4_K_M
ollama show llama3.2:1b-instruct-q4_K_M    # debe decir: quantization Q4_K_M
```

> El modelo por defecto `llama3.2:1b` es de **8 bits** (Q8_0). Para cuantización a **4 bits** usa la etiqueta `1b-instruct-q4_K_M`. Ambos nodos deben tener exactamente el mismo modelo.

**Solo en la Raspberry Pi**, para que acepte conexiones desde la mini PC:

```bash
sudo systemctl edit ollama
```

Añade:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

```bash
sudo systemctl restart ollama
```

En la mini PC no hace falta exponer Ollama: el balanceador le habla por `127.0.0.1`.

### 4. Entorno de Python (mini PC)

```bash
sudo apt install -y python3-venv python3-pip
python3 -m venv ~/IA/venv
~/IA/venv/bin/pip install -r chatbot_web/requirements.txt
~/IA/venv/bin/pip install faster-whisper piper-tts ddgs flask paramiko numpy
```

### 5. Voz de Piper

Descarga `es_ES-davefx-medium.onnx` y `es_ES-davefx-medium.onnx.json` del repositorio de voces de Piper (`rhasspy/piper-voices`, en Hugging Face) y colócalos en `servidor_laptop/voces/`.

### 6. Nombre del modelo en el código

El nombre del modelo aparece en tres archivos; deben coincidir con el que descargaste:

- `servidor_laptop/ollama_client.py`
- `chatbot_web/backend/config.py`
- `cluster/balanceador.py`

### 7. Configuración del chat web

Copia las credenciales **fuera del código**, con variables de entorno:

| Variable | Para qué sirve |
|---|---|
| `SMTP_USER`, `SMTP_PASSWORD` | Cuenta que envía el correo de verificación (Gmail con contraseña de aplicación) |
| `URL_BASE` | Dirección que lleva el enlace de verificación, p. ej. `http://192.168.10.1:8000` |
| `COOKIE_SECURE` | `true` solo si el sitio se sirve por HTTPS |

El correo de verificación necesita internet. En una red totalmente aislada, crea las cuentas de antemano.

### 8. Cliente de voz (Raspberry Pi)

Copia `cliente_pi/` a `~/cliente_pi` en la Raspberry Pi e instala sus dependencias principales (`customtkinter`, `sounddevice`, `numpy`, `requests`). En `asistente_cliente.py`, `SERVIDOR_URL` debe apuntar a la mini PC (`http://192.168.10.1:8100`).

## Uso

### Opción A: panel de control

```bash
~/IA/Panel/abrir_panel.sh
```

Abre `http://127.0.0.1:5050` y usa **Arrancar**, **Detener** y **Validar** en cada servicio. Los registros quedan en `~/IA/logs/`.

### Opción B: a mano (una terminal por servicio, en este orden)

```bash
# 1. Balanceador
cd ~/IA/cluster && ~/IA/venv/bin/python balanceador.py

# 2. Servidor de voz
cd ~/IA/servidor_laptop && ~/IA/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8100

# 3. Chat web
cd ~/IA/chatbot_web/backend && ~/IA/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

En la Raspberry Pi:

```bash
cd ~/cliente_pi && export DISPLAY=:0 && python3 asistente_cliente.py
```

Comprueba que el clúster ve a los dos nodos:

```bash
curl http://localhost:5000/salud
```

Ambos deben aparecer con `"activo": true`. El chat web queda en `http://192.168.10.1:8000`.

## Probar la tolerancia a fallos

**Escenario A: cae el nodo de respaldo.** En la Raspberry Pi:

```bash
sudo systemctl stop ollama
```

`curl http://localhost:5000/salud` marca `raspberry_pi` como inactivo, y el chat sigue respondiendo con normalidad porque el maestro atiende todo. Restablece con `sudo systemctl start ollama`.

**Escenario B: cae la inferencia del maestro.** En la mini PC:

```bash
sudo systemctl stop ollama
```

Manda un mensaje por el chat. El registro del balanceador muestra el aviso y la respuesta llega desde la Raspberry Pi, con más latencia. Restablece con `sudo systemctl start ollama`.

## Seguridad y confidencialidad

**Qué se implementó**

- Inferencia, transcripción y síntesis de voz **100 % locales**: ninguna pregunta se envía a un proveedor de IA.
- Subred privada clase C con IPs fijas y sin puerta de enlace hacia internet.
- Chat con registro verificado por correo y contraseñas con hash **bcrypt**.
- Cookie de sesión `HttpOnly` y `SameSite`, bloqueo tras intentos fallidos y límite de mensajes por minuto.
- Cada usuario ve únicamente sus propias conversaciones.
- Internet solo se usa si el usuario lo pide expresamente: búsqueda web (DuckDuckGo) o consulta de la hora (`worldtimeapi.org`).

**Qué no cubre**

- Los nodos de este montaje tienen Wi-Fi para instalar paquetes y acceder de forma remota. En un despliegue real se desactivaría para dejar la red realmente aislada.
- El tráfico entre nodos usa HTTP sin cifrar dentro de la subred privada.
- El balanceador y Ollama no autentican las peticiones: cualquiera dentro de la subred puede consultarlos.
- Las bases de datos (SQLite) no están cifradas en disco.

> **Antes de publicar tu propia copia:** no subas `config.py` con credenciales reales ni los archivos `*.db` (contienen cuentas y conversaciones). El `.gitignore` incluido excluye las bases de datos, los registros y el entorno virtual.

## Rendimiento

La inferencia corre solo en CPU, sin GPU, por diseño. El tiempo de respuesta depende sobre todo de la **longitud de la respuesta generada**: las respuestas cortas son rápidas y las largas pueden tardar decenas de segundos. La primera petición tras arrancar es más lenta porque Ollama carga el modelo en memoria. Si el maestro falla, las respuestas desde la Raspberry Pi son más lentas todavía.

## Limitaciones y trabajo futuro

- Un modelo de 1B parámetros a 4 bits responde con menos calidad que un modelo grande en la nube: es el costo de ganar privacidad y control.
- Cifrar el tráfico entre nodos (TLS) y autenticar el acceso al balanceador y a Ollama.
- Aislar la red por completo (sin Wi-Fi) y cifrar los datos en reposo.
- Reparto de carga más fino, por ejemplo según el tiempo de respuesta reciente de cada nodo.
- Ejecutar los servicios como unidades `systemd` para que arranquen solos.

## Contexto académico

Proyecto Final Integrador: *Diseño, montaje e implementación de un clúster de edge computing para inferencia de IA local autónoma*. Caso de uso elegido: **Caso 3 — Procesamiento de lenguaje para asistencia local** (modelo de lenguaje pequeño cuantizado a 4 bits).

## Autores

- Nombre 1
- Nombre 2
- Nombre 3
- Nombre 4

## Licencia

Por definir. El modelo Llama 3.2 se distribuye bajo la [Llama 3.2 Community License](https://www.llama.com/llama3_2/license/); revisa también las licencias de Whisper, Piper y de la voz utilizada.
