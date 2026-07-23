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
from urllib.parse import parse_qs, urlparse

from homelens.errors import HomeLensError
from homelens.config import PROJECT_ROOT
from homelens.service import HomeLensService
from homelens.utils import json_default


STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST = PROJECT_ROOT / "map" / "dist"
MAX_REQUEST_BYTES = 128 * 1024
LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _local_origin_allowed(origin: str, request_host: str) -> bool:
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https"}:
        return False
    origin_host = (parsed_origin.hostname or "").lower()
    host_name = (request_host.rsplit("@", 1)[-1].split(":", 1)[0] or "").lower()
    return origin_host in LOCAL_ORIGIN_HOSTS and host_name in LOCAL_ORIGIN_HOSTS


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

        def _file(self, path: Path) -> None:
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

        def _frontend(self, request_path: str) -> None:
            if FRONTEND_DIST.exists():
                relative = request_path.lstrip("/") or "index.html"
                path = (FRONTEND_DIST / relative).resolve()
                if path.is_relative_to(FRONTEND_DIST.resolve()) and path.is_file():
                    self._file(path)
                    return
                # The built app is a single-page application.
                if "." not in Path(relative).name:
                    self._file(FRONTEND_DIST / "index.html")
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            legacy = {
                "/": "index.html",
                "/index.html": "index.html",
                "/styles.css": "styles.css",
                "/app.js": "app.js",
            }.get(request_path)
            if legacy:
                self._file(STATIC_DIR / legacy)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/health":
                    self._json(HTTPStatus.OK, service.health())
                elif path == "/api/overview":
                    self._json(HTTPStatus.OK, service.overview())
                elif path == "/api/locations/search":
                    parameters = parse_qs(parsed.query)
                    query = (parameters.get("q") or [""])[0]
                    raw_limit = (parameters.get("limit") or ["5"])[0]
                    try:
                        limit = int(raw_limit)
                    except ValueError as error:
                        raise ValueError("location candidate limit must be an integer") from error
                    self._json(HTTPStatus.OK, service.search_locations(query, limit=limit))
                elif path == "/api/advisor/session":
                    parameters = parse_qs(parsed.query)
                    session_id = (parameters.get("session_id") or [""])[0]
                    self._json(HTTPStatus.OK, service.advisor_state(session_id))
                elif path.startswith("/api/"):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                else:
                    self._frontend(path)
            except ValueError as error:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_request", "message": str(error)},
                )
            except HomeLensError as error:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "service_unavailable", "message": str(error)},
                )

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in {"/api/recommend", "/api/advisor/message", "/api/advisor/reset"}:
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
                request_host = self.headers.get("Host", "").lower()
                if not _local_origin_allowed(origin, request_host):
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
                if path == "/api/recommend":
                    result = service.get_recommendations(payload)
                elif path == "/api/advisor/message":
                    result = service.advisor_message(payload)
                else:
                    result = service.reset_advisor(payload)
                self._json(HTTPStatus.OK, result)
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
