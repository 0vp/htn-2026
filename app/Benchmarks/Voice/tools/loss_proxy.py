"""Local-test SRTP loss injector; never decrypts or persists audio/SDP.

Control API binds loopback; UDP accepts only this host and the selected peer.
Run locally with python3. VoiceLossTests configures one simulator session at a
time. Only audio RTP is dropped; STUN, DTLS and RTCP are forwarded unchanged.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Relay:
    def __init__(self, sdp, profile):
        if profile not in {"clean", "isolated", "burst"}:
            raise ValueError("Unknown loss profile")
        lines = sdp.splitlines()
        candidates = [line.split() for line in lines if line.startswith("a=candidate:")]
        udp = next(parts for parts in candidates if parts[2].lower() == "udp")
        self.remote = (socket.gethostbyname(udp[4]), int(udp[5]))
        route = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        route.connect(self.remote)
        self.local_ip = route.getsockname()[0]
        route.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.local_ip, 0))
        self.socket.settimeout(0.1)
        port = self.socket.getsockname()[1]
        rewritten = []
        for line in lines:
            if line.startswith("a=candidate:"):
                parts = line.split()
                if parts[2].lower() != "udp":
                    continue
                parts[4], parts[5] = self.local_ip, str(port)
                line = " ".join(parts)
            rewritten.append(line)
        self.sdp = "\r\n".join(rewritten) + "\r\n"
        self.profile = profile
        self.packets = self.dropped = self.downlink = 0
        self.client = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()

    def pump(self):
        while not self.stopped.is_set():
            try:
                data, address = self.socket.recvfrom(65535)
                if address == self.remote:
                    self.downlink += 1
                    if self.client:
                        self.socket.sendto(data, self.client)
                    continue
                if address[0] != self.local_ip:
                    continue
                self.client = address
                rtp = len(data) >= 12 and data[0] & 0xC0 == 0x80 and not 192 <= data[1] <= 223
                if rtp:
                    self.packets += 1
                    # Start after handshake, at ~1.6 s with 20 ms Opus packets.
                    drop = (self.profile == "burst" and 80 <= self.packets < 92)
                    drop |= self.profile == "isolated" and self.packets >= 80 and self.packets % 10 == 0
                    if drop:
                        self.dropped += 1
                        continue
                self.socket.sendto(data, self.remote)
            except socket.timeout:
                pass
            except OSError:
                break

    def close(self):
        self.stopped.set()
        self.socket.close()
        self.thread.join(timeout=1)


class Handler(BaseHTTPRequestHandler):
    relay = None

    def log_message(self, *_):
        pass  # Never log credentials from SDP.

    def reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/configure" or not 0 < size < 65536:
                raise ValueError("Invalid request")
            body = json.loads(self.rfile.read(size))
            if Handler.relay:
                Handler.relay.close()
            Handler.relay = Relay(body["sdp"], body["profile"])
            self.reply(200, {"sdp": Handler.relay.sdp})
        except (ValueError, KeyError, StopIteration, OSError):
            self.reply(400, {"error": "Invalid relay configuration"})

    def do_GET(self):
        relay = Handler.relay
        self.reply(200, {} if relay is None else {
            "profile": relay.profile, "packets": relay.packets,
            "dropped": relay.dropped, "downlink": relay.downlink,
        })


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8811), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if Handler.relay:
            Handler.relay.close()
        server.server_close()
