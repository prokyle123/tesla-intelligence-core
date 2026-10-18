"""GENESIS self-contained preview server, strictly loopback only.

This is a development preview; it is intentionally not a public production
WSGI server, is not authenticated and MUST NOT be published to an untrusted
network. Use an SSH localhost port forward from the PC during development.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import signal
from flask import Flask
from werkzeug.serving import make_server
from .api import blueprint


def create_workspace_app(*,data_dir: Path) -> Flask:
    app=Flask("ghost-genesis-standalone")
    app.config.update(
        GENESIS_DATA_DIR=str(Path(data_dir).expanduser().resolve()),
        MAX_CONTENT_LENGTH=0,
    )
    app.register_blueprint(blueprint)
    # Prevent accidental mutation even if an extension adds a route later.
    @app.before_request
    def only_get():
        from flask import abort,request
        if request.method not in ("GET","HEAD","OPTIONS"):
            abort(405)
    return app


def main(argv: list[str]|None=None) -> int:
    p=argparse.ArgumentParser(description="Local-only GENESIS development workspace")
    p.add_argument("--data-dir",type=Path,required=True)
    p.add_argument("--port",type=int,default=8767)
    p.add_argument("--bind",default="127.0.0.1")
    args=p.parse_args(argv)
    if args.bind not in ("127.0.0.1","::1","localhost"):
        p.error("Refusing external bind. Use local SSH port forwarding.")
    if not 1024<=args.port<=65535:
        p.error("Port out of allowed range.")
    if not args.data_dir.expanduser().is_dir():
        p.error("Data directory must already exist; no files created by viewer.")
    app=create_workspace_app(data_dir=args.data_dir)
    print(f"GENESIS preview http://127.0.0.1:{args.port}/genesis",flush=True)
    server=make_server("127.0.0.1",args.port,app,threaded=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
