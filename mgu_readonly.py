"""Minimal read-only BMW MGU identification over HSFZ/ENET.
Protocol approach informed by cauliflowermossgrape/idrive7-8-ssh-root.
No programming sessions, SecurityAccess, routines, or write operations.
"""
import socket
import struct
import time

def _request(sock, destination, payload, wait=4):
    # HSFZ diagnostic frame, tester 0xF4, MGU 0x63.
    frame = bytes([0xF4, destination]) + payload
    sock.sendall(struct.pack(">IH", len(frame), 1) + frame)
    sock.settimeout(0.4)
    deadline = time.monotonic() + wait
    received = bytearray()
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            received.extend(chunk)
        except socket.timeout:
            continue
        offset = 0
        while len(received) - offset >= 8:
            length, kind = struct.unpack_from(">IH", received, offset)
            if length < 2 or length > 1048576:
                raise ValueError("Invalid HSFZ response length")
            if len(received) - offset < length + 6:
                break
            src, dst = received[offset+6:offset+8]
            body = bytes(received[offset+8:offset+6+length])
            offset += length + 6
            if kind == 1 and src == destination and dst == 0xF4:
                if body[:1] == b"\\x7f":
                    raise ValueError("MGU rejected read-only request: " + body.hex())
                if body.startswith(bytes([payload[0] + 0x40]) + payload[1:3]):
                    return body
        if offset:
            del received[:offset]
    raise TimeoutError("MGU did not answer the read-only identification request")

def read_identity(gateway):
    with socket.create_connection((gateway, 6801), timeout=4) as sock:
        svk = _request(sock, 0x63, bytes.fromhex("22 F1 01"), wait=10)
        body = svk[3:]
        records = []
        for i in range(0, len(body)-7, 8):
            kind = body[i]
            if kind in (1,5,6,8,13):
                ident = int.from_bytes(body[i+1:i+5], "big")
                trip = ".".join(str(x).zfill(3) for x in body[i+5:i+8])
                records.append((kind, f"{ident:08X}_{trip}"))
        if not records:
            raise ValueError("SVK response received but could not decode records")
        btld = [value for kind,value in records if kind == 6]
        try:
            raw_ip = _request(sock, 0x63, bytes.fromhex("22 17 2A"), wait=3)
            ip = socket.inet_ntoa(raw_ip[4:8]) if len(raw_ip) >= 16 and raw_ip[3] == 0 else None
        except (OSError, TimeoutError, ValueError):
            ip = None
        return {"btld": btld, "ip": ip, "records": records}
