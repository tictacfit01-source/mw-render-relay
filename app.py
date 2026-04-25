"""
MejorWolf Render relay.

Mismas funciones que el Cloudflare Worker /?u= y /wfsearch, pero corriendo
en infraestructura NO-Cloudflare. Como Wolf banea por IP los rangos de
Cloudflare/Render/etc, opcionalmente enruta wolfmax via ScraperAPI (pool
residencial rotante) cuando esta presente la variable SCRAPERAPI_KEY.

Endpoints:
  GET /                     -> ping
  GET /relay?u=<url>        -> proxy generico
  GET /wfsearch?q=<query>   -> busqueda completa wolfmax (GET shell + POST AJAX
                                manteniendo sesion, via ScraperAPI si esta
                                configurada).
"""
import os
import re
import requests
import cloudscraper
from urllib.parse import urlencode, quote as urlquote
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

# === ScraperAPI (residential proxy bypass) =================================
# Si esta presente esta env var, todas las peticiones a wolfmax4k pasan por
# ScraperAPI que rota IPs residenciales. Wolf no puede banear porque cada
# request sale por una IP distinta.
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "").strip()

# Sticky session — necesitamos GET shell + POST AJAX usando la MISMA
# sesion (cookies+token comparten estado). ScraperAPI mantiene cookies
# si pasamos session_number=N (mismo N en ambas requests).
SCRAPERAPI_BASE = "http://api.scraperapi.com"


def _scraperapi_url(target_url, session_number=None, post=False):
    """Construye URL de ScraperAPI envolviendo target_url.

    `premium=true` -> usa el pool de IPs residenciales premium, necesario
    para dominios protegidos como wolfmax4k. Consume 25 creditos/request
    (vs 1 normal). Plan free 1000 creditos = ~40 requests/dia.
    """
    params = {
        "api_key":      SCRAPERAPI_KEY,
        "url":          target_url,
        "keep_headers": "true",
        "country_code": "es",
        # premium=true respeta nuestros headers (Referer, etc.) y rota
        # IPs residenciales. ultra_premium=true usa navegador real que
        # sobrescribe Referer -> server rechaza con "No Referrer".
        "premium":      "true",
    }
    if session_number is not None:
        params["session_number"] = str(session_number)
    return SCRAPERAPI_BASE + "/?" + urlencode(params)


def _wolf_get(session_number, url, headers=None, timeout=60):
    """GET hacia wolfmax via ScraperAPI (si hay key) o cloudscraper."""
    if SCRAPERAPI_KEY:
        wrapped = _scraperapi_url(url, session_number=session_number)
        return requests.get(wrapped, headers=headers or {}, timeout=timeout)
    cs = _make_scraper()
    return cs.get(url, headers=headers or {}, timeout=timeout)


def _wolf_post(session_number, url, data=None, headers=None, timeout=60):
    """POST hacia wolfmax via ScraperAPI (si hay key) o cloudscraper."""
    if SCRAPERAPI_KEY:
        wrapped = _scraperapi_url(url, session_number=session_number)
        return requests.post(wrapped, data=data, headers=headers or {},
                             timeout=timeout)
    cs = _make_scraper()
    return cs.post(url, data=data, headers=headers or {}, timeout=timeout)


def _make_scraper():
    """Cloudscraper para flujos donde no haya ScraperAPI configurado."""
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
        return any(d in h.lower() for d in ALLOWED_HOSTS)
    except Exception:
        return False


@app.get("/")
def root():
    return Response(
        "MejorWolf Render relay OK. ScraperAPI=" +
        ("ON" if SCRAPERAPI_KEY else "OFF"),
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
    is_wolf = "wolfmax4k" in target.lower()
    try:
        if is_wolf and SCRAPERAPI_KEY:
            wrapped = _scraperapi_url(target, session_number=None)
            r = requests.request(request.method, wrapped, headers=fwd,
                                 data=body, timeout=60, allow_redirects=True)
        elif is_wolf:
            cs = _make_scraper()
            r = cs.request(request.method, target, headers=fwd, data=body,
                           timeout=25, allow_redirects=True)
        else:
            r = requests.request(request.method, target, headers=fwd,
                                 data=body, timeout=25, allow_redirects=True,
                                 stream=False)
    except Exception as e:
        return Response("relay error: " + e.__class__.__name__ + ": " + str(e),
                        status=502)

    out_headers = {}
    for k, v in r.headers.items():
        if k.lower() in SKIP_RESP_HEADERS:
            continue
        out_headers[k] = v
    out_headers["Access-Control-Allow-Origin"] = "*"
    out_headers["X-MW-Render-Status"] = str(r.status_code)
    out_headers["X-MW-Render-Final"] = r.url
    out_headers["X-MW-Via-Scraperapi"] = "1" if (is_wolf and SCRAPERAPI_KEY) else "0"
    return Response(r.content, status=r.status_code, headers=out_headers)


_TOKEN_RE = re.compile(
    r'name=["\']?token["\']?\s+value=["\']([^"\']+)', re.I,
)


@app.get("/wfsearch")
def wfsearch():
    """Busqueda dedicada wolfmax: GET shell + POST data.find.php manteniendo
    sesion via ScraperAPI session_number (cookies+token consistentes entre
    ambas requests)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return Response("missing q", status=400)
    pg = request.args.get("pg") or "1"
    limit = request.args.get("l") or "100"
    raw_mode = request.args.get("raw") == "1"

    base = "https://www.wolfmax4k.com"
    diag = {"phase": "init", "scraperapi": bool(SCRAPERAPI_KEY)}

    # Sesion sticky por query — asi misma IP+cookies entre GET y POST
    import hashlib
    session_number = int(hashlib.sha1(q.encode()).hexdigest()[:8], 16) % 1000

    try:
        # 1) GET HOMEPAGE para harvest token + cookie.
        # IMPORTANTE: Chrome envia Referer "/" (home), no /buscar/<q>.
        # El token CSRF que valida data.find.php proviene del form ffind
        # de la HOME, no del de la pagina de busqueda. Usar la URL
        # equivocada hace que el server rechaze con "Denied".
        diag["phase"] = "shell"
        diag["session_number"] = session_number
        shell_url = base + "/"
        r0 = _wolf_get(session_number, shell_url,
                       headers={**BROWSER_HEADERS}, timeout=70)
        diag["shell_status"] = r0.status_code
        diag["shell_bytes"] = len(r0.content)
        text = r0.text
        m = _TOKEN_RE.search(text)
        token = m.group(1) if m else ""
        diag["token"] = "ok" if token else "miss"
        if not token:
            return jsonify({"response": False,
                            "data": {"error": "no token"},
                            "_diag": diag,
                            "_html_sample": text[:400]}), 502

        # Capturar PHPSESSID y cualquier cookie del shell. Los pasamos
        # explicitamente al POST porque ScraperAPI puede no propagar
        # cookies entre requests al mismo session_number.
        cookies_to_fwd = []
        for c in r0.cookies:
            cookies_to_fwd.append(f"{c.name}={c.value}")
        # ScraperAPI tambien puede devolver Set-Cookie en headers raw
        sc_header = r0.headers.get("Set-Cookie") or ""
        for piece in sc_header.split(","):
            mm = re.match(r"^\s*([^=;\s]+)=([^;]*)", piece)
            if mm and mm.group(1) not in [c.split("=")[0] for c in cookies_to_fwd]:
                cookies_to_fwd.append(f"{mm.group(1)}={mm.group(2)}")
        cookie_header = "; ".join(cookies_to_fwd)
        diag["cookies"] = cookie_header[:120]

        # 2) POST AJAX -> data.find.php
        # Replica EXACTA del request de Chrome capturado con DevTools:
        # - Sin www en el host
        # - multipart/form-data (NO urlencoded)
        # - Campos: token, cidr=0, c=0, q, l, pg  (NO _ACTION!)
        # - SIN X-Requested-With
        # - Referer: home (NO /buscar/<q>)
        # - Accept: */*
        diag["phase"] = "ajax"
        ajax_url = "https://wolfmax4k.com/mvc/controllers/data.find.php"
        # Construir multipart/form-data manualmente con boundary tipo Chrome
        boundary = "----WebKitFormBoundaryyMTCxsxFHq3bxBSN"
        crlf = "\r\n"
        parts = []
        for name, value in [
            ("token", token),
            ("cidr",  "0"),
            ("c",     "0"),
            ("q",     q),
            ("l",     limit),
            ("pg",    pg),
        ]:
            parts.append(f"--{boundary}{crlf}"
                         f"Content-Disposition: form-data; name=\"{name}\"{crlf}{crlf}"
                         f"{value}{crlf}")
        parts.append(f"--{boundary}--{crlf}")
        body = "".join(parts).encode("utf-8")
        ajax_headers = {
            "Accept":            "*/*",
            "Accept-Language":   "es-ES,es;q=0.9",
            "Origin":            "https://www.wolfmax4k.com",
            "Referer":           "https://www.wolfmax4k.com/",
            "Content-Type":      f"multipart/form-data; boundary={boundary}",
            "Sec-Fetch-Dest":    "empty",
            "Sec-Fetch-Mode":    "cors",
            "Sec-Fetch-Site":    "same-site",
            "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/147.0.0.0 Safari/537.36",
        }
        # NOTA: Chrome NO envia Cookie en su POST a data.find.php (verificado
        # via DevTools). Si la enviamos podemos romper la validacion del token.
        # Asi que omitimos cookie_header aqui aunque la tengamos.
        # POST con body raw (no data=dict, para mantener el body multipart exacto)
        if SCRAPERAPI_KEY:
            wrapped = _scraperapi_url(ajax_url, session_number=session_number)
            r1 = requests.post(wrapped, data=body, headers=ajax_headers,
                               timeout=70)
        else:
            cs = _make_scraper()
            r1 = cs.post(ajax_url, data=body, headers=ajax_headers, timeout=70)
        diag["ajax_status"] = r1.status_code
        diag["ajax_bytes"] = len(r1.content)
        diag["ajax_text_sample"] = (r1.text or "")[:200]
        try:
            data = r1.json()
        except Exception:
            data = None

        if raw_mode:
            return Response(
                r1.content, status=r1.status_code,
                mimetype=r1.headers.get("content-type", "application/json"),
                headers={"Access-Control-Allow-Origin": "*",
                         "X-MW-Diag": str(diag)},
            )

        if not data or not data.get("response"):
            return jsonify({"response": False, "data": data,
                            "_diag": diag}), 200

        # Normalizar a items playables
        out = []
        datafinds = (data.get("data") or {}).get("datafinds") or {}
        if isinstance(datafinds, list):
            buckets = datafinds
        else:
            buckets = [datafinds.get(str(i)) for i in range(20)
                       if datafinds.get(str(i))]
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            for k in sorted(bucket.keys(),
                            key=lambda x: int(x) if str(x).isdigit() else 0):
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
        })

    except Exception as e:
        diag["error"] = e.__class__.__name__ + ": " + str(e)
        return jsonify({"response": False, "_diag": diag}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
