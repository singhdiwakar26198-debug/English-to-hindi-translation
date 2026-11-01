import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "SARVAM_API_KEY":
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def sarvam_post(endpoint, payload):
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("Add SARVAM_API_KEY to the .env file and restart the server.")

    request = Request(
        f"https://api.sarvam.ai/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-subscription-key": key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"Sarvam returned an error ({error.code}). Check your key and try again.") from None
    except URLError:
        raise RuntimeError("Could not reach Sarvam. Check your internet connection and try again.") from None


class AppHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = (ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/translate-speak":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 10000:
                self.send_json(413, {"error": "Please use text under 1,000 characters."})
                return
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            text = data.get("text", "").strip()
            if not text:
                self.send_json(400, {"error": "Enter some English text first."})
                return
            if len(text) > 1000:
                self.send_json(400, {"error": "Please keep the text under 1,000 characters."})
                return

            translation = sarvam_post(
                "translate",
                {
                    "input": text,
                    "source_language_code": "en-IN",
                    "target_language_code": "hi-IN",
                    "model": "mayura:v1",
                    "mode": "modern-colloquial",
                },
            )
            hindi_text = translation["translated_text"]
            speech = sarvam_post(
                "text-to-speech",
                {
                    "text": hindi_text,
                    "language_code": "hi-IN",
                    "model": "bulbul:v4-flash",
                    "output_audio_codec": "mp3",
                },
            )
            self.send_json(
                200,
                {
                    "translated_text": hindi_text,
                    "audio_base64": speech["audios"][0],
                },
            )
        except (RuntimeError, KeyError, ValueError, json.JSONDecodeError) as error:
            self.send_json(502, {"error": str(error) or "The request could not be completed."})
        except Exception:
            self.send_json(500, {"error": "Something went wrong. Please try again."})


if __name__ == "__main__":
    load_env()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Open http://127.0.0.1:8000 in your browser. Press Ctrl+C to stop.")
    server.serve_forever()
