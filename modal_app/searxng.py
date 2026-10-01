"""
Modal app: a private SearXNG — open-source metasearch (Google, Bing, Brave,
DuckDuckGo, Wikipedia…) with no API key or monthly quota, for Sem's web_search.

Deploy (Colab or a terminal):
    modal secret create semblance-searxng SEARXNG_KEY=<any long random string> --force
    modal deploy modal_app/searxng.py

Set the GitHub secret SEARXNG_URL to the printed URL plus "/" and the same key:
    https://<you>--semblance-searxng-web.modal.run/<SEARXNG_KEY>
Anything without the key gets a 404, so nobody else can spend your credit.
CPU only and scales to zero: a single user's searches cost cents a month.
"""
import modal

app = modal.App("semblance-searxng")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .run_commands(
        "git clone --depth 1 https://github.com/searxng/searxng /opt/searxng",
        "pip install -U pip setuptools wheel",
        "pip install -r /opt/searxng/requirements.txt",
        "pip install --no-build-isolation /opt/searxng",
    )
    .env({"SEARXNG_SETTINGS_PATH": "/opt/settings.yml"})
)

SETTINGS = """
use_default_settings: true
general:
  instance_name: "semblance"
server:
  secret_key: "{secret}"
  limiter: false
  public_instance: false
  image_proxy: false
search:
  formats: [html, json]
  safe_search: 0
"""


@app.function(image=image, secrets=[modal.Secret.from_name("semblance-searxng")], scaledown_window=300)
@modal.concurrent(max_inputs=20)
@modal.wsgi_app()
def web():
    import hashlib
    import os

    key = os.environ["SEARXNG_KEY"].strip()
    with open("/opt/settings.yml", "w") as f:
        f.write(SETTINGS.format(secret=hashlib.sha256(("searxng:" + key).encode()).hexdigest()))

    from searx.webapp import app as searx_app  # reads the settings file on import

    prefix = "/" + key

    def guarded(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path != prefix and not path.startswith(prefix + "/"):
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found"]
        environ["PATH_INFO"] = path[len(prefix):] or "/"
        environ.setdefault("REMOTE_ADDR", "127.0.0.1")
        environ.setdefault("HTTP_X_FORWARDED_FOR", "127.0.0.1")
        return searx_app(environ, start_response)

    return guarded
