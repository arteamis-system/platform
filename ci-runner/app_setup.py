"""Create the dedicated GitHub App through two browser consent screens.

Secrets are written only to a new mode-0600 file outside this repository.
The loopback callback is protected by a random state and does not log URLs.
"""

import argparse
import html
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def registration_form(callback, state):
    homepage = "https://github.com/arteamis-system/platform"
    manifest = {
        "name": "Arteamis CI Fallback", "url": homepage,
        "redirect_url": callback + "/callback", "setup_url": callback + "/installed?state=" + state,
        "setup_on_update": True, "public": False,
        # GitHub requires a webhook URL even when webhook delivery is disabled.
        "hook_attributes": {"url": homepage, "active": False},
        "default_permissions": {"actions": "write", "administration": "write", "checks": "read",
                                "contents": "read", "metadata": "read", "pull_requests": "read", "actions_variables": "write"},
        "default_events": [],
    }
    action = "https://github.com/organizations/arteamis-system/settings/apps/new?state=" + state
    return ("<h1>Set up Arteamis CI fallback</h1><p>This creates a private GitHub App for CI routing and ephemeral repository runners.</p>"
            + '<form action="' + html.escape(action) + '" method="post"><input type="hidden" name="manifest" value="'
            + html.escape(json.dumps(manifest), quote=True) + '"><button>Create the CI App on GitHub</button></form>')


def serve(output, port, timeout_minutes=120):
    if not 5 <= timeout_minutes <= 240:
        raise ValueError("Setup window must be between 5 and 240 minutes")
    root = Path(__file__).resolve().parents[2]
    if output.resolve().is_relative_to(root) or output.exists():
        raise ValueError("Choose a new output file outside the Arteamis workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    state = secrets.token_urlsafe(32)
    callback = f"http://127.0.0.1:{port}"
    app = {}
    deadline = time.time() + timeout_minutes * 60
    def save():
        if output.exists():
            descriptor = os.open(output, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        else:
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(app, stream)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def page(self, text, status=200):
            data = ("<!doctype html><meta charset=utf-8><title>Arteamis CI setup</title>"
                    "<style>body{font:18px system-ui;max-width:760px;margin:60px auto;padding:20px}button{font:inherit;padding:12px}</style>"
                    + text).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action https://github.com; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            request = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(request.query)
            if self.headers.get("Host") != f"127.0.0.1:{port}" or time.time() >= deadline:
                return self.page("Setup unavailable.", 403)
            if request.path == "/":
                return self.page(registration_form(callback, state))
            if request.path == "/aws-template":
                data = Path(__file__).with_name("generated").joinpath("admin-bootstrap.json").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="arteamis-ci-access.json"')
                self.end_headers()
                self.wfile.write(data)
                return
            if query.get("state") != [state]:
                return self.page("Invalid setup callback.", 403)
            if request.path == "/callback" and not app:
                code = query.get("code", [""])[0]
                if not code or not code.isalnum():
                    return self.page("Invalid GitHub callback.", 400)
                try:
                    exchange = urllib.request.Request("https://api.github.com/app-manifests/" + code + "/conversions", method="POST",
                                                      headers={"Accept": "application/vnd.github+json", "User-Agent": "arteamis-ci-setup/1"})
                    with urllib.request.urlopen(exchange, timeout=15) as result:
                        created = json.load(result)
                    app.update({"app_id": created["id"], "private_key": created["pem"], "installation_id": None})
                    save()
                    install = "https://github.com/apps/" + urllib.parse.quote(created["slug"], safe="") + "/installations/new"
                    return self.page("<h1>App created</h1><p>Choose <strong>Only select repositories</strong> and select backend, web, landing, and product.</p>"
                                     + '<p><a href="' + html.escape(install) + '">Install the CI App</a></p>')
                except Exception:
                    return self.page("App registration did not finish. No credentials are shown. Check GitHub App settings before starting again.", 502)
            if request.path == "/installed" and app and query.get("installation_id", [""])[0].isdigit():
                app["installation_id"] = int(query["installation_id"][0])
                save()
                print("GitHub CI App registration and installation complete. Private configuration saved securely.", flush=True)
                return self.page("<h1>GitHub setup complete</h1><p>The private configuration was saved locally. Return to the Arteamis setup session. Do not copy credentials into chat.</p>")
            return self.page("Unknown setup step.", 404)

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    print(f"GitHub setup: {callback}/", flush=True)
    try:
        while time.time() < deadline and not app.get("installation_id"):
            server.handle_request()
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--timeout-minutes", type=int, default=120)
    args = parser.parse_args()
    serve(args.output, args.port, args.timeout_minutes)
