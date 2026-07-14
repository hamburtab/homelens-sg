"""Dependency-free local HTTP server for the HomeLens SG demo."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
import mimetypes
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from homelens.errors import HomeLensError
from homelens.service import HomeLensService
from homelens.utils import json_default


STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BYTES = 128 * 1024


def handler_factory(service: HomeLensService) -> type[BaseHTTPRequestHandler]:
    request_times: dict[str, deque[float]] = defaultdict(deque)
    rate_limit_lock = threading.Lock()

    class HomeLensHandler(BaseHTTPRequestHandler):
        server_version = "HomeLensSG/0.1"

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                default=json_default,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, filename: str) -> None:
            path = STATIC_DIR / filename
            if not path.exists() or not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/health":
                self._json(HTTPStatus.OK, service.health())
            elif path in ("/", "/index.html"):
                self._static("index.html")
            elif path == "/styles.css":
                self._static("styles.css")
            elif path == "/app.js":
                self._static("app.js")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/recommend":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    {
                        "error": "unsupported_media_type",
                        "message": "Content-Type must be application/json.",
                    },
                )
                return
            origin = self.headers.get("Origin")
            if origin:
                parsed_origin = urlparse(origin)
                request_host = self.headers.get("Host", "").lower()
                if (
                    parsed_origin.scheme not in {"http", "https"}
                    or parsed_origin.netloc.lower() != request_host
                ):
                    self._json(
                        HTTPStatus.FORBIDDEN,
                        {"error": "forbidden_origin", "message": "Cross-origin requests are blocked."},
                    )
                    return
            client_ip = self.client_address[0]
            now = time.monotonic()
            limited = False
            with rate_limit_lock:
                history = request_times[client_ip]
                while history and history[0] < now - 60:
                    history.popleft()
                if len(history) >= 30:
                    limited = True
                else:
                    history.append(now)
            if limited:
                self._json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {"error": "rate_limited", "message": "Try again in one minute."},
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("request body must be between 1 byte and 128 KiB")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
                self._json(HTTPStatus.OK, service.get_recommendations(payload))
            except (ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(error)})
            except HomeLensError as error:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "service_unavailable", "message": str(error)},
                )
            except Exception as error:  # keep the demo server alive while hiding internals
                self.log_error("Unhandled error: %s", error)
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal_error", "message": "Unexpected server error."},
                )

    return HomeLensHandler


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "The built-in demo server is local-only. Use 127.0.0.1, or place a production "
            "server with authentication and rate limiting in front of HomeLens."
        )
    service = HomeLensService()
    server = ThreadingHTTPServer((host, port), handler_factory(service))
    print(f"HomeLens SG is running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
