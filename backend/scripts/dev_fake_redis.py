"""Local development only: an in-memory Redis-compatible server for the job queue.

Lets background jobs run on a Windows machine without Docker or a real Redis
install. It listens on 127.0.0.1:6379 (the default EARTHSCOPE_REDIS_URL).

* Nothing is persisted: closing this window empties the queue. Job records live in
  the SQLite database, and the reconciler re-queues QUEUED/PENDING jobs whose
  queue entry vanished, so no job is lost.
* Not for production: use real Redis (Docker Compose) there.

    .venv\\Scripts\\python.exe scripts\\dev_fake_redis.py [--port 6379]
"""

from __future__ import annotations

import argparse

from fakeredis import TcpFakeServer
from fakeredis._clients._tcp_server import TCPFakeRequestHandler


def _host_port(sockname: tuple) -> str:
    return f"{sockname[0]}:{sockname[1]}"


class _Handler(TCPFakeRequestHandler):
    """fakeredis' TCP server reports client addresses as Python tuples ("('127.0.0.1', 5000)"),
    which breaks redis-py's CLIENT LIST parser (and therefore RQ workers). Report "host:port"
    like real Redis does."""

    def setup(self) -> None:
        super().setup()
        info = self.current_client.get_socket()._client_info
        info["addr"] = _host_port(self.connection.getpeername())
        info["laddr"] = _host_port(self.connection.getsockname())


def main() -> None:
    parser = argparse.ArgumentParser(description="In-memory Redis for local Earth Scope job testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    args = parser.parse_args()
    server = TcpFakeServer((args.host, args.port), server_type="redis")
    server.RequestHandlerClass = _Handler
    print(f"Fake Redis (in-memory, dev only) listening on {args.host}:{args.port} — Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
