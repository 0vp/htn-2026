"""Save the badge's screen as a PNG via the `shot` console command.

    python badge/tools/badge_shot.py /dev/cu.usbmodem2101 out.png [--wait 8]

Opening the USB port restarts the badge, so this waits for it to boot before asking.
Needs pyserial; the PNG is written with the standard library.
"""

import argparse
import struct
import time
import zlib

import serial


def write_png(path: str, width: int, height: int, rows: list[bytes]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def capture(port: str, wait: float) -> tuple[int, int, list[bytes]]:
    link = serial.Serial()
    link.port, link.baudrate, link.timeout = port, 115200, 0.5
    link.dtr = link.rts = False
    link.open()
    time.sleep(wait)
    link.read(1 << 20)
    link.write(b"shot\r\n")

    lines: list[str] = []
    deadline = time.time() + 20
    buffer = b""
    while time.time() < deadline:
        buffer += link.read(1 << 16)
        *done, buffer = buffer.split(b"\n")
        lines += [line.decode(errors="replace").strip() for line in done]
        if "END" in lines:
            break
    start = next(i for i, line in enumerate(lines) if line.startswith("SHOT "))
    _, width, height, count = lines[start].split()
    width, height, count = int(width), int(height), int(count)
    palette_hex = lines[start + 1]
    palette = [bytes.fromhex(palette_hex[i * 6 : i * 6 + 6]) for i in range(count)]
    rows = []
    for line in lines[start + 2 : start + 2 + height]:
        indices = bytes.fromhex(line)
        rows.append(b"".join(palette[i] if i < count else b"\x00\x00\x00" for i in indices))
    return width, height, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    parser.add_argument("out")
    parser.add_argument("--wait", type=float, default=8, help="seconds to let the badge boot and connect")
    args = parser.parse_args()
    width, height, rows = capture(args.port, args.wait)
    write_png(args.out, width, height, rows)
    print(f"saved {width}x{height} to {args.out}")


if __name__ == "__main__":
    main()
