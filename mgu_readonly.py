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
                if body[:1] == bytes([0x7F]):
                    raise ValueError("MGU rejected read-only request: " + body.hex())
                if body.startswith(bytes([payload[0] + 0x40]) + payload[1:3]):
                    return body
        if offset:
            del received[:offset]
    raise TimeoutError("MGU did not answer the read-only identification request")

SVK_TYPES = {1: "HWEL", 5: "CAFD", 6: "BTLD", 8: "SWFL", 13: "SWFK"}

def parse_svk(payload):
    """Decode SVK using the upstream strict-or-offset record-pair approach."""
    marker = bytes.fromhex("62 F1 01")
    index = payload.find(marker)
    if index < 0:
        raise ValueError("SVK response lacks the expected positive identifier")
    body = payload[index + len(marker):]
    def valid(offset):
        return offset + 7 < len(body) and body[offset] in SVK_TYPES and body[offset+1:offset+3] == bytes(2)
    if index == 0 and len(body) % 8 == 0:
        start = 0
    else:
        start = next((i for i in range(max(0, len(body)-15)) if valid(i) and valid(i+8)), None)
    if start is None:
        raise ValueError("SVK records could not be aligned; raw response retained")
    records = []
    for i in range(start, len(body)-7, 8):
        if body[i] not in SVK_TYPES:
            continue
        identifier = int.from_bytes(body[i+1:i+5], "big")
        version = ".".join(f"{x:03d}" for x in body[i+5:i+8])
        records.append((SVK_TYPES[body[i]], f"{identifier:08X}_{version}"))
    if not records:
        raise ValueError("No recognized SVK records")
    return records

def read_identity(gateway):
    with socket.create_connection((gateway, 6801), timeout=4) as sock:
        svk = _request(sock, 0x63, bytes.fromhex("22 F1 01"), wait=10)
        try:
            records = parse_svk(svk)
            parse_error = None
        except ValueError as exc:
            records = []
            parse_error = str(exc)
        btld = [value for kind, value in records if kind == "BTLD"]
        try:
            raw_ip = _request(sock, 0x63, bytes.fromhex("22 17 2A"), wait=3)
            marker = bytes.fromhex("62 17 2A 00")
            index = raw_ip.find(marker)
            ip = socket.inet_ntoa(raw_ip[index+4:index+8]) if index >= 0 and len(raw_ip) >= index+16 else None
        except (OSError, TimeoutError, ValueError):
            ip = None
        return {"btld": btld, "ip": ip, "records": records,
                "parse_error": parse_error, "svk_raw": svk.hex(" ").upper()}

def check_ssh(host, timeout=3):
    """TCP reachability only: not proof of authentication or root access."""
    try:
        with socket.create_connection((host, 22), timeout=timeout):
            return "TCP port 22 open (SSH/root not verified)"
    except OSError:
        return "TCP port 22 closed or unreachable"
