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
        self.status_tool = tk.StringVar()
        self.gateway = tk.StringVar(value='Not detected')
        self.mgu_ip = tk.StringVar(value='Not detected')
        self.variant = tk.StringVar(value='Unknown')
        self.software = tk.StringVar(value='Not read')
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="MGU Store — Read-only Diagnostics", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        for name, variable in [("Head-unit SSH host", self.host), ("Private SSH key", self.key), ("Official mgu-install.js", self.script), ("Official ssh_enable.py", self.status_tool)]:
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
        self.state = tk.StringVar(value="Ready — no changes will be made")
        dashboard = ttk.LabelFrame(frame, text="MGU Connection Dashboard", padding=8)
        dashboard.pack(fill="x", pady=6)
        for label, value in [("Gateway", self.gateway), ("MGU IP", self.mgu_ip), ("Variant", self.variant), ("BTLD", self.software)]:
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
        """Only invoke upstream status; never invoke flash, enable or coding writes."""
        tool = Path(self.status_tool.get().strip()).expanduser()
        if not tool.is_file() or tool.name.lower() != "ssh_enable.py":
            messagebox.showerror("MGU identity", "Select the official ssh_enable.py script from the idrive7-8-ssh-root project.")
            return
        def task():
            result = subprocess.run([sys.executable, str(tool), "status"],
                                    cwd=str(tool.parent), capture_output=True,
                                    text=True, timeout=60, stdin=subprocess.DEVNULL, shell=False)
            output = (result.stdout + "\n" + result.stderr).strip()
            gateway = re.search(r"Connecting to ENET gateway\s+(\d+\.\d+\.\d+\.\d+)", output)
            mgu = re.search(r"MGU IP:\s*(\d+\.\d+\.\d+\.\d+)", output)
            btld = re.search(r"BTLD\s+([0-9A-Fa-f_.]+)", output)
            if gateway:
                self.q.put(("__GATEWAY__", gateway.group(1)))
            if mgu:
                self.q.put(("__MGU__", mgu.group(1)))
            if btld:
                version = btld.group(1)
                self.q.put(("__SOFTWARE__", version))
                family = "ID7 family (verify)" if "_030." in version else ("ID8 family (BDC3/BCP unresolved)" if "_036." in version else "Unknown")
                self.q.put(("__VARIANT__", family))
            if result.returncode:
                output += "\nStatus command exited with code " + str(result.returncode)
            if not btld:
                output += "\nNo BTLD parsed; variant not identified."
            return output
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
                        return f"{host}:22 is reachable. This does not establish SSH/root access."
                except OSError:
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
                if output in ('__GATEWAY__', '__MGU__', '__SOFTWARE__', '__VARIANT__'):
                    {'__GATEWAY__': self.gateway, '__MGU__': self.mgu_ip, '__SOFTWARE__': self.software, '__VARIANT__': self.variant}[output].set(status)
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
