# MejorWolf Render Relay

Relay HTTP en Python (Flask + gunicorn) que replica las funciones del Worker de
Cloudflare pero ejecuta desde **infraestructura no-CF** (datacenter de Render).
Esto evita el bloqueo que `wolfmax4k.com/mvc/controllers/data.find.php` aplica
a las IPs de Cloudflare Workers (devuelve `"Denied"` siempre).

## Endpoints

- `GET /`                     — ping
- `GET /relay?u=<url>`        — proxy genérico (igual que el Worker `/?u=`)
- `GET /wfsearch?q=<query>`   — busqueda completa wolfmax4k

  Parametros opcionales:
  - `pg=N`  pagina (default 1)
  - `l=N`   limite (default 100)
  - `raw=1` devuelve el JSON crudo de data.find.php sin normalizar

## Despliegue en Render.com (gratis, ~5 min)

### Opción A — Vía Git (recomendada)

1. **Crea cuenta** en https://render.com (login con GitHub o email).
2. **Sube esta carpeta** `render_relay/` a un repo nuevo en GitHub
   (puede ser privado). Con la web de GitHub: New Repository → Add file →
   Upload files → arrastra los 4 archivos (`app.py`, `requirements.txt`,
   `render.yaml`, `README.md`) → Commit.
3. En Render: **New + → Web Service** → Conecta tu GitHub → selecciona el
   repo. Render detecta `render.yaml` automaticamente.
4. Click **Deploy**. Tarda ~3 min. Cuando esté en verde te dará la URL,
   algo como `https://mw-render-relay-XXXX.onrender.com`.

### Opción B — Sin Git, vía CLI render

```bash
pip install render-cli
render login
cd render_relay
render deploy
```

## Configurar el addon

Una vez tengas la URL del servicio Render:

1. Abre Kodi → Add-ons → MejorWolf → engranaje (Configurar) → pestaña
   "Conexión".
2. Pega la URL en el campo **`render_relay_url`**:
   `https://mw-render-relay-XXXX.onrender.com`
   (sin barra final).
3. Guarda. Listo.

El addon usará Render como **prioridad** para `data.find.php`. Si Render
falla o tarda, hace fallback al Cloudflare Worker existente.

## Notas

- **Free tier de Render** duerme tras 15 min sin tráfico. Primer request tras
  dormir tarda ~30s en despertar. Las siguientes son inmediatas. Para
  evitarlo, paga $7/mes por *Always-on*, o pinguea cada 10 min con un cron.
- **Costos**: $0 en el free tier mientras no superes 750h/mes (suficiente
  para uso personal).
- **Privacidad**: el relay no loguea queries por defecto. Solo añade
  cabeceras de diagnóstico (`X-MW-Diag`).
