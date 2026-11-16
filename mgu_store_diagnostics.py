"""Read-only MGU Store diagnostics for authorized head units."""
import subprocess
import socket
import json
import ipaddress
import select
import time
import shutil
import re
import sys
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from threading import Thread
from queue import Queue, Empty

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MGU Store Diagnostics — ENET")
        self.geometry("1000x700")
        self.q = Queue()
        self.host = tk.StringVar(value="")
        self.key = tk.StringVar()
        self.script = tk.StringVar()
        self.gateway = tk.StringVar(value='Not detected')
        self.mgu_ip = tk.StringVar(value='Not detected')
        self.variant = tk.StringVar(value='Unknown')
        self.software = tk.StringVar(value='Not read')
        self.ssh_status = tk.StringVar(value='Not checked')
        self.compatibility = tk.StringVar(value='Pending identification')
        self.backup_state = tk.StringVar(value='Not selected')
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="MGU Store — Read-only Diagnostics", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        for name, variable in [("Head-unit SSH host", self.host), ("Private SSH key", self.key), ("Official mgu-install.js", self.script)]:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=name, width=23).pack(side="left")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
            if variable is not self.host:
                ttk.Button(row, text="Browse", command=lambda v=variable: self.pick(v)).pack(side="left", padx=5)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Detect ENET", command=self.detect_enet).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Discover BMW Gateway", command=self.discover_gateway).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Read MGU Identity", command=self.identify_mgu).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Check SSH Port", command=self.test_ssh).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Read MGU Store Status", command=self.status).pack(side="left")
        ttk.Button(buttons, text="Verify Backup File", command=self.verify_backup).pack(side="left", padx=(8, 0))
        self.state = tk.StringVar(value="Ready — no changes will be made")
        dashboard = ttk.LabelFrame(frame, text="MGU Connection Dashboard", padding=8)
        dashboard.pack(fill="x", pady=6)
        for label, value in [("Gateway", self.gateway), ("MGU IP", self.mgu_ip), ("Variant", self.variant), ("BTLD", self.software), ("SSH", self.ssh_status), ("Compatibility", self.compatibility), ("Backup", self.backup_state)]:
            line = ttk.Frame(dashboard)
            line.pack(fill="x")
            ttk.Label(line, text=label + ":", width=12).pack(side="left")
            ttk.Label(line, textvariable=value).pack(side="left")
        ttk.Label(frame, textvariable=self.state).pack(anchor="w")
        self.output = tk.Text(frame, height=17, state="disabled", wrap="word")
        self.output.pack(fill="both", expand=True, pady=8)
        self.after(100, self.drain)

    def pick(self, var):
        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def inputs(self):
        host = self.host.get().strip()
        if not host or host.startswith("-") or any(c.isspace() for c in host):
            raise ValueError("Enter a valid SSH hostname or IP address.")
        key = self.key.get().strip()
        return host, key

    def run(self, cmd):
        self.state.set("Running read-only check…")
        def worker():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=45, stdin=subprocess.DEVNULL, shell=False)
                self.q.put(((result.stdout + "\n" + result.stderr).strip(),
                            "Completed" if result.returncode == 0 else f"Failed (exit {result.returncode})"))
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.q.put((str(exc), "Failed"))
        Thread(target=worker, daemon=True).start()

    def detect_enet(self):
        def worker():
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-NetIPConfiguration | Where-Object {$_.IPv4Address} | "
                   "Select-Object InterfaceAlias,InterfaceDescription,"
                   "@{Name='IPv4';Expression={($_.IPv4Address.IPAddress -join ', ')}} | "
                   "ConvertTo-Json -Depth 3"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode:
                return result.stderr.strip() or "Unable to list adapters"
            data = json.loads(result.stdout or "[]")
            entries = data if isinstance(data, list) else [data]
            lines = ["Detected Windows adapters (physical Ethernet prioritized):"]
            for item in entries:
                ip = item.get("IPv4", "")
                desc = str(item.get("InterfaceDescription") or "").lower()
                virtual = any(word in desc for word in ("vpn", "virtual", "tap-", "tunnel", "bluetooth", "wireless", "wi-fi", "hyper-v"))
                label = " — PHYSICAL ETHERNET CANDIDATE" if "169.254." in ip and not virtual else (" — virtual/non-ENET candidate" if "169.254." in ip else "")
                lines.append(f"{item.get('InterfaceAlias')}: {ip} {item.get('InterfaceDescription')}{label}")
            lines.append("Adapter detection alone does not confirm a BMW connection or head-unit IP.")
            return "\n".join(lines)
        self.run_task(worker)

    def discover_gateway(self):
        """Read-only BMW ENET UDP discovery. Never transmits coding commands."""
        def task():
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-NetIPConfiguration | Where-Object {$_.IPv4Address} | "
                   "Select-Object InterfaceAlias,InterfaceDescription,"
                   "@{Name='IPv4';Expression={($_.IPv4Address.IPAddress -join ', ')}} | ConvertTo-Json -Depth 3"]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if p.returncode:
                raise RuntimeError(p.stderr.strip() or "Could not enumerate network interfaces")
            raw = json.loads(p.stdout or "[]")
            adapters = raw if isinstance(raw, list) else [raw]
            candidates = []
            for entry in adapters:
                desc = (str(entry.get("InterfaceDescription") or "") + " " + str(entry.get("InterfaceAlias") or "")).lower()
                if any(term in desc for term in ("vpn", "virtual", "bluetooth", "wi-fi", "wireless", "tap-", "tunnel", "hyper-v")):
                    continue
                for ip in str(entry.get("IPv4") or "").split(","):
                    ip = ip.strip()
                    if ip.startswith("169.254."):
                        candidates.append((entry.get("InterfaceAlias"), ip))
            if not candidates:
                return "No physical link-local Ethernet interface found. Check cable, ignition and Windows network settings."
            lines = ["BMW ENET discovery — read-only UDP broadcast on port 6811"]
            found = []
            for name, source in candidates:
                lines.append(f"Testing {name} ({source})")
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.bind((source, 0))
                        sock.sendto(bytes([0,0,0,0,0,17]), ("169.254.255.255", 6811))
                        deadline = time.monotonic() + 2.0
                        while time.monotonic() < deadline:
                            ready, _, _ = select.select([sock], [], [], max(0, deadline - time.monotonic()))
                            if not ready:
                                break
                            packet, addr = sock.recvfrom(4096)
                            if b"BMWVIN" in packet and addr[0] not in found:
                                found.append(addr[0])
                                self.q.put(("__GATEWAY__", addr[0]))
                                lines.append(f"BMW gateway response: {addr[0]} (BMWVIN marker verified)")
                except OSError as exc:
                    lines.append(f"Interface probe failed: {exc}")
            if not found:
                lines.append("No BMW gateway reply. Check physical ENET link and firewall; this does not prove the MGU is offline.")
            else:
                lines.append("Gateway identified. This is not the MGU IP. Head-unit identification requires a separate read-only diagnostic step.")
            return "\n".join(lines)
        self.run_task(task)

    def identify_mgu(self):
        """Read-only MGU SVK and IP over the discovered BMW gateway."""
        from mgu_readonly import read_identity
        gateway = self.gateway.get().strip()
        try:
            ipaddress.IPv4Address(gateway)
        except ValueError:
            messagebox.showerror("MGU identity", "Discover BMW Gateway first.")
            return
        def task():
            result = read_identity(gateway)
            btld = ", ".join(result["btld"]) or "Not reported"
            self.q.put(("__SOFTWARE__", btld))
            ip = result["ip"]
            if ip:
                self.q.put(("__MGU__", ip))
            self.q.put(("__VARIANT__", "MGU family unverified (ID7/ID8)"))
            self.q.put(("__COMPAT__", self.classify_compatibility(result["records"])))
            rows = [f"MGU responded through gateway {gateway}:6801",
                    "BTLD: " + btld,
                    "MGU IP: " + (ip or "Not returned"),
                    "Variant: unverified; BTLD alone is insufficient to identify BDC3 vs BCP.",
                    "SVK records:"]
            rows.extend(f"  {kind}: {value}" for kind,value in result["records"])
            if result["parse_error"]:
                rows.append("SVK decode warning: " + result["parse_error"])
                rows.append("Raw SVK (hex): " + result["svk_raw"])
            if ip:
                from mgu_readonly import check_ssh
                ssh = check_ssh(ip)
                self.q.put(("__SSH__", ssh))
                rows.append("SSH: " + ssh)
            else:
                self.q.put(("__SSH__", "MGU IP unavailable"))
            return "\n".join(rows)
        self.run_task(task)

    @staticmethod
    def classify_compatibility(records):
        """Informational classification, never authorization to flash."""
        bootloaders = [value for kind, value in records if kind == "BTLD"]
        if not bootloaders:
            return "Unknown — no BTLD record"
        if any("_036." in value for value in bootloaders):
            return "036 family detected — support unverified"
        if any("_030." in value for value in bootloaders):
            return "030 family detected — support unverified"
        return "BTLD detected — compatibility unverified"

    def verify_backup(self):
        path = filedialog.askopenfilename(title="Select an existing MGU coding backup")
        if not path:
            return
        def task():
            target = Path(path)
            if not target.is_file():
                raise ValueError("Backup file not found")
            size = target.stat().st_size
            if size == 0:
                raise ValueError("Backup file is empty")
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            self.q.put(("__BACKUP__", "File present; restore unverified"))
            return ("Backup file check (no changes made)\n"
                    f"Name: {target.name}\nSize: {size:,} bytes\n"
                    f"SHA-256: {digest.hexdigest()}\n"
                    "This confirms file readability and a checksum only. "
                    "It does NOT verify coding contents, vehicle match, "
                    "restore compatibility, or Digital Key preservation.")
        self.run_task(task)

    def run_task(self, task):
        self.state.set("Checking network…")
        def worker():
            try:
                self.q.put((task(), "Check complete"))
            except Exception as exc:
                self.q.put((str(exc), "Check failed"))
        Thread(target=worker, daemon=True).start()

    def test_ssh(self):
        try:
            host, _ = self.inputs()
            def probe():
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    return "Enter a discovered head-unit IP before testing SSH; laptop IP is not the MGU IP."
                try:
                    with socket.create_connection((host, 22), timeout=3):
                        self.q.put(("__SSH__", "TCP port 22 open (SSH/root not verified)"))
                        return f"{host}:22 is reachable. This does not establish SSH/root access."
                except OSError:
                    self.q.put(("__SSH__", "TCP port 22 closed or unreachable"))
                    return f"{host}:22 is closed or unreachable. This is expected if SSH is not enabled."
            self.run_task(probe)
        except ValueError as exc:
            messagebox.showerror("Connection", str(exc))

    def status(self):
        try:
            host, key = self.inputs()
            if not key or not Path(key).expanduser().is_file():
                raise ValueError("MGU Store status requires authorized SSH access and an existing private key.")
            script = Path(self.script.get()).expanduser()
            if not script.is_file():
                raise ValueError("Select the official mgu-install.js file.")
            if not shutil.which("node"):
                raise ValueError("Node.js 18+ is required.")
            self.run(["node", str(script), "status", "--host", host, "--identity", key])
        except ValueError as exc:
            messagebox.showerror("Status", str(exc))

    def drain(self):
        try:
            while True:
                output, status = self.q.get_nowait()
                if output in ('__GATEWAY__', '__MGU__', '__SOFTWARE__', '__VARIANT__', '__SSH__', '__COMPAT__', '__BACKUP__'):
                    {'__GATEWAY__': self.gateway, '__MGU__': self.mgu_ip, '__SOFTWARE__': self.software, '__VARIANT__': self.variant, '__SSH__': self.ssh_status, '__COMPAT__': self.compatibility, '__BACKUP__': self.backup_state}[output].set(status)
                    if output == '__MGU__':
                        self.host.set(status)
                    continue
                self.output.configure(state="normal")
                self.output.insert("end", output + "\n\n")
                self.output.configure(state="disabled")
                self.output.see("end")
                self.state.set(status)
        except Empty:
            pass
        self.after(100, self.drain)

if __name__ == "__main__":
    App().mainloop()
