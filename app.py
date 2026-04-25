"""
MejorWolf Render relay.

Mismas funciones que el Cloudflare Worker /?u= y /wfsearch, pero corriendo
en infraestructura NO-Cloudflare (IPs residenciales-ish desde el datacenter
de Render). Esto evita el bloqueo de wolfmax4k contra IPs CF que rompe el
endpoint AJAX /mvc/controllers/data.find.php.

Endpoints:
  GET /                     -> ping
  GET /relay?u=<url>        -> proxy generico (igual que CF Worker /?u=)
  GET /wfsearch?q=<query>   -> busqueda completa wolfmax (GET token + POST AJAX
                                en una sola peticion, manteniendo cookie+sesion)
"""
import os
import re
import requests
import cloudscraper
from flask import Flask, request, Response, jsonify

app = Flask(__name__)


def _make_scraper():
    """Devuelve un scraper cloudscraper que emula Chrome y resuelve los
    challenges JavaScript de Cloudflare de forma transparente. Lo usamos
    para wolfmax4k que mete Under Attack Mode contra IPs de datacenter."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

ALLOWED_HOSTS = (
    "mejortorrent",
    "wolfmax4k",
    "enlacito.com",
    "short-info.link",
    "acortador.es",
    "image.tmdb.org",
    "themoviedb.org",
    "api.themoviedb.org",
    "search.brave.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
)

BROWSER_HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

SKIP_RESP_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "strict-transport-security",
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
}

PASSTHROUGH_HEADERS = (
    "x-requested-with",
    "origin",
    "accept",
    "accept-language",
)


def host_allowed(target_url: str) -> bool:
    try:
        from urllib.parse import urlparse
        h = urlparse(target_url).hostname or ""
        h = h.lower()
        return any(d in h for d in ALLOWED_HOSTS)
    except Exception:
        return False


@app.get("/")
def root():
    return Response(
        "MejorWolf Render relay OK. Endpoints: /relay?u=<url>, /wfsearch?q=<q>",
        mimetype="text/plain",
    )


@app.route("/relay", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
def relay():
    target = request.args.get("u", "")
    if not target:
        return Response("missing u", status=400)
    if not host_allowed(target):
        return Response("Host not allowed: " + target, status=403)

    fwd = dict(BROWSER_HEADERS)
    cookie = request.headers.get("cookie")
    if cookie:
        fwd["Cookie"] = cookie
    ct = request.headers.get("content-type")
    if ct:
        fwd["Content-Type"] = ct
    ref = request.headers.get("referer")
    if ref and host_allowed(ref):
        fwd["Referer"] = ref
    for name in PASSTHROUGH_HEADERS:
        v = request.headers.get(name)
        if v:
            canon = "-".join(p.capitalize() for p in name.split("-"))
            fwd[canon] = v

    body = request.get_data() if request.method not in ("GET", "HEAD") else None
    try:
        # Para wolfmax usamos cloudscraper (resuelve CF challenges).
        # Para el resto, requests normal.
        if "wolfmax4k" in target.lower():
            cs = _make_scraper()
            r = cs.request(
                request.method, target, headers=fwd, data=body,
                timeout=25, allow_redirects=True,
            )
        else:
            r = requests.request(
                request.method, target, headers=fwd, data=body,
                timeout=25, allow_redirects=True, stream=False,
            )
    except Exception as e:
        return Response(
            "relay error: " + e.__class__.__name__ + ": " + str(e),
            status=502,
        )

    out_headers = {}
    for k, v in r.headers.items():
        if k.lower() in SKIP_RESP_HEADERS:
            continue
        out_headers[k] = v
    out_headers["Access-Control-Allow-Origin"] = "*"
    out_headers["X-MW-Render-Status"] = str(r.status_code)
    out_headers["X-MW-Render-Final"] = r.url
    return Response(r.content, status=r.status_code, headers=out_headers)


_TOKEN_RE = re.compile(
    r'name=["\']?token["\']?\s+value=["\']([^"\']+)', re.I,
)


@app.get("/wfsearch")
def wfsearch():
    """Busqueda dedicada wolfmax: GET shell + POST data.find.php manteniendo
    sesion en el mismo flujo Python. Devuelve el JSON crudo de data.find.php
    o un wrapper con los items normalizados.

    Parametros:
      q  - query (obligatorio)
      pg - pagina (default 1)
      l  - limite (default 100)
      raw=1 - devolver el JSON raw del backend en vez del wrapper normalizado
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return Response("missing q", status=400)
    pg = request.args.get("pg") or "1"
    limit = request.args.get("l") or "100"
    raw_mode = request.args.get("raw") == "1"

    base = "https://www.wolfmax4k.com"
    sess = _make_scraper()
    sess.headers.update(BROWSER_HEADERS)
    diag = {"phase": "init"}

    try:
        # 1) GET pagina /buscar/<q> para harvest token + cookie
        diag["phase"] = "shell"
        shell_url = f"{base}/buscar/{requests.utils.quote(q, safe='')}"
        r0 = sess.get(shell_url, timeout=20, allow_redirects=True)
        diag["shell_status"] = r0.status_code
        diag["shell_bytes"] = len(r0.content)
        text = r0.text
        m = _TOKEN_RE.search(text)
        token = m.group(1) if m else ""
        diag["token"] = "ok" if token else "miss"
        if not token:
            return jsonify({"response": False, "data": {"error": "no token"},
                            "_diag": diag}), 502

        # 2) POST AJAX -> data.find.php
        diag["phase"] = "ajax"
        ajax_url = base.replace("www.", "") + "/mvc/controllers/data.find.php"
        form = {
            "_ACTION": "buscar",
            "token":   token,
            "q":       q,
            "l":       limit,
            "pg":      pg,
        }
        r1 = sess.post(
            ajax_url,
            data=form,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Origin":  base,
                "Referer": shell_url,
                "Accept":  "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
            timeout=25,
        )
        diag["ajax_status"] = r1.status_code
        diag["ajax_bytes"] = len(r1.content)
        try:
            data = r1.json()
        except Exception:
            data = None

        if raw_mode:
            return Response(
                r1.content,
                status=r1.status_code,
                mimetype=r1.headers.get("content-type",
                                        "application/json"),
                headers={"Access-Control-Allow-Origin": "*",
                         "X-MW-Diag": str(diag)},
            )

        if not data or not data.get("response"):
            return jsonify({"response": False, "data": data, "_diag": diag}), 200

        # Normalizar a items playables
        out = []
        datafinds = (data.get("data") or {}).get("datafinds") or {}
        # datafinds es {"0": {"0": {guid,torrentName,calidad,image}, "1": ...}, "1": {...}}
        if isinstance(datafinds, list):
            buckets = datafinds
        else:
            buckets = [datafinds.get(str(i)) for i in range(20)
                       if datafinds.get(str(i))]
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            for k in sorted(bucket.keys(), key=lambda x: int(x)
                            if str(x).isdigit() else 0):
                it = bucket[k]
                if not isinstance(it, dict):
                    continue
                guid = (it.get("guid") or "").strip().lstrip("/")
                if not guid:
                    continue
                full_url = base + "/" + guid
                out.append({
                    "url":     full_url,
                    "title":   (it.get("torrentName") or "").strip(),
                    "image":   it.get("image"),
                    "quality": it.get("calidad"),
                    "guid":    guid,
                })

        return jsonify({
            "response": True,
            "items":    out,
            "_diag":    diag,
            "_raw":     None if not raw_mode else data,
        })

    except Exception as e:
        diag["error"] = e.__class__.__name__ + ": " + str(e)
        return jsonify({"response": False, "_diag": diag}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
