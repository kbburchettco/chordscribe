"""Local web server for ChordScribe. Nothing leaves this computer."""
import hashlib
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import engine

HOST = "127.0.0.1"
PORT = 8765
ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
CACHE = os.path.join(ROOT, ".cache")
MAX_UPLOAD = 300 * 1024 * 1024
ALLOWED_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".aif", ".aiff", ".flac", ".caf"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/demo.wav": ("demo.wav", "audio/wav"),
}
# Bump when engine changes should invalidate saved results.
ENGINE_VERSION = "2"

# One analysis at a time: each one needs a lot of memory.
analysis_lock = threading.Lock()


def cached_analysis(data, suffix):
    digest = hashlib.sha256(data).hexdigest()
    cache_path = os.path.join(CACHE, f"{ENGINE_VERSION}-{digest}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as cached:
            return json.load(cached)
    with analysis_lock:
        handle, audio_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(handle, "wb") as audio:
                audio.write(data)
            result = engine.analyze(audio_path)
        finally:
            os.unlink(audio_path)
    os.makedirs(CACHE, exist_ok=True)
    with open(cache_path, "w") as cached:
        json.dump(result, cached)
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host_allowed(self):
        # Stops other websites reaching this server through a lookalike hostname.
        return self.headers.get("Host") in (f"{HOST}:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        entry = STATIC_FILES.get(urlparse(self.path).path)
        if not self.host_allowed() or entry is None:
            self.send_error(404)
            return
        name, content_type = entry
        with open(os.path.join(STATIC, name), "rb") as source:
            body = source.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        if not self.host_allowed() or url.path != "/api/analyze":
            self.send_error(404)
            return
        name = parse_qs(url.query).get("name", [""])[0]
        suffix = os.path.splitext(name)[1].lower()
        if suffix == ".m4p":
            self.close_connection = True
            self.send_json(415, {"error": "This is a copy-protected file, so ChordScribe can't read it. "
                                          "Please use an unprotected MP3 or M4A."})
            return
        if suffix not in ALLOWED_SUFFIXES:
            self.close_connection = True
            self.send_json(415, {"error": "Please use an MP3, M4A, WAV, AIFF or FLAC file."})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            self.close_connection = True
            self.send_json(413, {"error": "That file is empty or larger than 300 MB."})
            return
        data = self.rfile.read(length)
        try:
            self.send_json(200, cached_analysis(data, suffix))
        except ValueError as error:
            self.send_json(422, {"error": str(error)})
        except Exception as error:  # Show the failure in the app, not a dead spinner.
            print(f"Analysis failed: {error!r}", flush=True)
            self.send_json(500, {"error": "Analysis failed. See the Terminal window for details."})


if __name__ == "__main__":
    print(f"ChordScribe is running at http://{HOST}:{PORT}  (press Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
