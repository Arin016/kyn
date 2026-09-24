"""Frozen entry point used by the macOS Ari app bundle."""

from __future__ import annotations

import os

import uvicorn

from .server import create_app


def main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("KYN_PORT", "8765"))
    os.environ.setdefault("KYN_CONTROL_URL", f"http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
