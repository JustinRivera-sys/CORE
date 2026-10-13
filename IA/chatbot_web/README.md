# Chatbot web con login — corre en la Raspberry Pi, usa Ollama de tu laptop

## Qué es cada cosa
- `backend/` — servidor FastAPI: registro, verificación por correo, login, chat
- `frontend/` — páginas HTML del sitio (login, registro, chat)
- Base de datos SQLite (`chatbot_users.db`) — se crea sola al primer arranque

## Antes de correrlo en la Pi — 3 cosas que TIENES que cambiar

### 1. `backend/config.py` — datos de correo (SMTP)
Rellena `SMTP_USER` y `SMTP_PASSWORD`. Con Gmail:
1. Activa verificación en 2 pasos en tu cuenta de Google (si no la tienes)
2. Ve a https://myaccount.google.com/apppasswords
3. Genera una "Contraseña de aplicación" (16 caracteres) — esa va en `SMTP_PASSWORD`, **no tu contraseña normal de Gmail**

### 2. `backend/config.py` — IP de tu laptop
`OLLAMA_HOST` debe apuntar a la IP real de tu laptop en la red donde esté la Pi (la que le pongas fija cuando conectes por Ethernet, o la que te dé el router si van por WiFi de casa).

### 3. `backend/config.py` — URL pública
`URL_BASE` es el link que va dentro del correo de verificación. Mientras pruebas en casa puede ser la IP de la Pi (`http://192.168.x.x:8000`). Cuando actives Tailscale Funnel para acceso público, cámbialo a esa URL (`https://tu-pi.tu-red.ts.net`) y pon `COOKIE_SECURE=true`.

## Instalar en la Raspberry Pi

```bash
cd chatbot_web
pip install -r requirements.txt --break-system-packages
```

## Configurar Ollama en tu laptop para que la Pi pueda hablarle
Por defecto Ollama solo escucha `localhost`. En Windows (PowerShell o cmd):
```
setx OLLAMA_HOST "0.0.0.0:11434"
setx OLLAMA_ORIGINS "*"
```
Reinicia Ollama después de esto (ciérralo desde la bandeja del sistema y vuelve a abrirlo).

## Correr el servidor (en la Pi)
```bash
cd chatbot_web/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Desde cualquier dispositivo en la misma red: `http://IP-de-la-pi:8000`

## Para que arranque solo al encender la Pi (opcional, después)
Se puede crear un servicio de systemd — te lo doy cuando lleguemos a esa parte.

## Para hacerlo público desde cualquier lugar (Tailscale Funnel)
1. Instala Tailscale en la Pi: https://tailscale.com/download/linux
2. `sudo tailscale up`
3. `sudo tailscale funnel 8000`
4. Te da una URL pública HTTPS — esa va en `URL_BASE` (config.py) y hay que reiniciar el servidor

**Antes de hacerlo público de verdad**: el rate limit (`LIMITE_MENSAJES_POR_MINUTO` en config.py) evita que un solo usuario sature tu laptop, pero cualquiera con el link puede crear una cuenta y usar tu Ollama — considera si quieres eso abierto a cualquiera o prefieres un sistema de invitación después.

## Ya probado (sin necesitar la Pi ni Ollama real)
- Registro → verificación por correo → login → chat → logout, flujo completo
- Bloqueo tras 5 intentos fallidos de contraseña
- Rechazo de correos duplicados
- Rate limit de mensajes por usuario
- Acceso denegado sin sesión válida

Lo único que falta probar en la vida real (cuando estés en casa) es que Ollama responda de verdad a través de la red, y que el correo de Gmail llegue con tus credenciales reales.
