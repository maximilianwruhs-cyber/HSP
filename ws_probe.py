import argparse
import base64
import hashlib
import os
import socket


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple WebSocket handshake probe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--path", default="/ws")
    args = parser.parse_args()

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {args.path} HTTP/1.1\r\n"
        f"Host: {args.host}:{args.port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Origin: http://{args.host}:{args.port}\r\n"
        "\r\n"
    )

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        sock.sendall(request.encode("ascii"))
        raw = sock.recv(4096).decode("ascii", errors="replace")

    lines = raw.splitlines()
    status = lines[0] if lines else "<no status line>"
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()

    expected_accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")

    print(status)
    print("upgrade:", headers.get("upgrade", ""))
    print("connection:", headers.get("connection", ""))
    print("sec-websocket-accept-valid:", headers.get("sec-websocket-accept", "") == expected_accept)

    return 0 if status.startswith("HTTP/1.1 101") else 1


if __name__ == "__main__":
    raise SystemExit(main())
