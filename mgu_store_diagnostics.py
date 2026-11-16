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
import os
import webbrowser
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
        self.upstream_status_script = tk.StringVar()
        self.gateway = tk.StringVar(value='Not detected')
        self.mgu_ip = tk.StringVar(value='Not detected')
        self.variant = tk.StringVar(value='Unknown')
        self.software = tk.StringVar(value='Not read')
        self.hardware = tk.StringVar(value='Not read')
        self.cafd = tk.StringVar(value='Not read')
        self.arch_hint = tk.StringVar(value='Unknown / not confirmed')
        self.ssh_status = tk.StringVar(value='Not checked')
        self.compatibility = tk.StringVar(value='Pending identification')
        self.backup_state = tk.StringVar(value='Not selected')
        self.backup_kind = tk.StringVar(value='BimmerCode (Android)')
        self.arch_choice = tk.StringVar(value="ID8-BDC3")
        self.load_backup_preference()
        self.load_arch_preference()
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
        arch_row = ttk.Frame(frame)
        arch_row.pack(fill="x", pady=(6, 2))
        ttk.Label(arch_row, text="Manually selected architecture:", width=27).pack(side="left")
        ttk.Combobox(arch_row, textvariable=self.arch_choice, state="readonly",
                     width=25, values=("Unknown / not selected", "ID8-BDC3",
                                       "ID8-BCP", "ID7")).pack(side="left")
        ttk.Button(arch_row, text="Save selection", command=self.save_arch_selection).pack(side="left", padx=8)
        ttk.Label(arch_row, text="User-selected; not verified by diagnostics").pack(side="left")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Detect ENET", command=self.detect_enet).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Discover BMW Gateway", command=self.discover_gateway).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Read MGU Identity", command=self.identify_mgu).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Check SSH Port", command=self.test_ssh).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Read MGU Store Status", command=self.status).pack(side="left")
        ttk.Button(buttons, text="Verify Backup File", command=self.verify_backup).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="External Backup", command=self.external_backup).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Compatibility Details", command=self.compatibility_details).pack(side="left", padx=(8, 0))
        ssh_row = ttk.Frame(frame)
        ssh_row.pack(fill="x", pady=(0, 5))
        ttk.Button(ssh_row, text="SSH Readiness Report", command=self.ssh_readiness).pack(side="left")
        ttk.Label(ssh_row, text="Read-only: checks port, client and local key availability").pack(side="left", padx=8)
        upstream_row = ttk.Frame(frame)
        upstream_row.pack(fill="x", pady=(0, 5))
        ttk.Label(upstream_row, text="Upstream ssh_enable.py:", width=23).pack(side="left")
        ttk.Entry(upstream_row, textvariable=self.upstream_status_script).pack(side="left", fill="x", expand=True)
        ttk.Button(upstream_row, text="Browse", command=lambda: self.pick(self.upstream_status_script)).pack(side="left", padx=5)
        ttk.Button(upstream_row, text="Run upstream status only", command=self.upstream_status).pack(side="left")
        self.state = tk.StringVar(value="Ready — no changes will be made")
        dashboard = ttk.LabelFrame(frame, text="MGU Connection Dashboard", padding=8)
        dashboard.pack(fill="x", pady=6)
        for label, value in [("Gateway", self.gateway), ("MGU IP", self.mgu_ip), ("Variant", self.arch_choice), ("BTLD", self.software), ("HWEL", self.hardware), ("CAFD", self.cafd), ("SSH", self.ssh_status), ("Compatibility", self.compatibility), ("Backup", self.backup_state)]:
            line = ttk.Frame(dashboard)
            line.pack(fill="x")
            ttk.Label(line, text=label + ":", width=12).pack(side="left")
            ttk.Label(line, textvariable=value).pack(side="left")
        ttk.Label(frame, textvariable=self.state).pack(anchor="w")
        self.output = tk.Text(frame, height=17, state="disabled", wrap="word")
        self.output.pack(fill="both", expand=True, pady=8)
        self.add_catalog_panel(frame)
        self.after(100, self.drain)

    def add_catalog_panel(self, parent):
        """Local catalog browsing only: never executes packages or installer."""
        self.catalog_items = []
        section = ttk.LabelFrame(parent, text="App Catalog — Preview Only", padding=8)
        section.pack(fill="x", pady=(4, 6))
        ttk.Label(section, text="Browse a local catalog.json; this does not contact or change the MGU.").pack(anchor="w")
        bar = ttk.Frame(section)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Open local catalog.json", command=self.open_catalog).pack(side="left")
        ttk.Button(bar, text="View upstream MGU Store", command=lambda: webbrowser.open(
            "https://github.com/robertnisipeanu/mgu-store")).pack(side="left", padx=8)
        ttk.Button(bar, text="Preview selected app", command=self.preview_app).pack(side="left")
        self.catalog_list = tk.Listbox(section, height=4, exportselection=False)
        self.catalog_list.pack(fill="x")
        ttk.Label(section, text="Install / update / remove disabled: root SSH and compatibility not verified.").pack(anchor="w")

    def open_catalog(self):
        path = filedialog.askopenfilename(title="Choose MGU catalog.json",
                                          filetypes=[("JSON catalog", "*.json")])
        if not path:
            return
        try:
            if Path(path).stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Catalog is too large (2 MB limit).")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = next((data[k] for k in ("apps", "packages", "items")
                                if isinstance(data.get(k), list)), None)
                if entries is None:
                    raise ValueError("Expected an apps, packages or items array.")
            else:
                raise ValueError("Expected a JSON catalog object or array.")
            if len(entries) > 1000:
                raise ValueError("Catalog has too many entries.")
            self.catalog_items = [e for e in entries if isinstance(e, dict)]
            self.catalog_list.delete(0, "end")
            for item in self.catalog_items:
                name = str(item.get("name") or item.get("id") or "Unnamed")[:100]
                version = str(item.get("version") or "version unknown")[:40]
                self.catalog_list.insert("end", name + " — " + version)
            self.state.set(f"Loaded {len(self.catalog_items)} catalog entries locally")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            messagebox.showerror("App catalog", str(exc))

    def preview_app(self):
        chosen = self.catalog_list.curselection()
        if not chosen:
            messagebox.showinfo("App preview", "Choose an app from a local catalog first.")
            return
        item = self.catalog_items[chosen[0]]
        supported = item.get("mguHmi", item.get("compatibility", "Not specified"))
        if isinstance(supported, list):
            supported = ", ".join(str(v) for v in supported)
        dependencies = item.get("requires", [])
        if isinstance(dependencies, list):
            dependencies = ", ".join(str(v) for v in dependencies) or "None declared"
        messagebox.showinfo("App preview — no installation",
            "App: " + str(item.get("name") or item.get("id") or "Unnamed")[:150] +
            "\\nVersion: " + str(item.get("version") or "Unknown")[:100] +
            "\\nDeclared platform: " + str(supported)[:250] +
            "\\nDependencies: " + str(dependencies)[:250] +
            "\\nSelected vehicle architecture: " + self.arch_choice.get() +
            "\\n\\nCatalog metadata is untrusted and not a compatibility verification." +
            "\\nNo package will be downloaded or installed.")

    @staticmethod
    def backup_settings_path():
        """Use per-user AppData, not the executable's directory."""
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "MGUStoreDiagnostics" / "settings.json"

    def load_backup_preference(self):
        """Restore only the user's declared backup source; never imply verification."""
        try:
            data = json.loads(self.backup_settings_path().read_text(encoding="utf-8"))
            source = data.get("external_backup_source")
            valid = ("BimmerCode (Android)", "BimmerCode (iOS)",
                     "E-Sys (external device)", "Other external backup")
            if source in valid:
                self.backup_kind.set(source)
                self.backup_state.set(source + " — user-confirmed; restore unverified")
        except (OSError, ValueError, TypeError):
            pass

    def save_backup_preference(self, source):
        path = self.backup_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, TypeError):
            data = {}
        data["external_backup_source"] = source
        temporary.write_text(json.dumps(data, indent=2),
                             encoding="utf-8")
        temporary.replace(path)

    def load_arch_preference(self):
        """Load a user selection, never silently infer architecture from BTLD."""
        try:
            data = json.loads(self.backup_settings_path().read_text(encoding="utf-8"))
            value = data.get("manual_architecture", "Unknown / not selected")
            if value in ("Unknown / not selected", "ID8-BDC3", "ID8-BCP", "ID7"):
                self.arch_choice.set(value)
        except (OSError, ValueError, TypeError):
            pass

    def save_arch_selection(self):
        """Persist manual selection alongside external backup preference."""
        value = self.arch_choice.get()
        if value not in ("Unknown / not selected", "ID8-BDC3", "ID8-BCP", "ID7"):
            messagebox.showerror("Architecture", "Invalid architecture selection.")
            return
        path = self.backup_settings_path()
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError, TypeError):
                data = {}
            data["manual_architecture"] = value
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            messagebox.showerror("Architecture", "Unable to save selection: " + str(exc))
            return
        messagebox.showinfo("Architecture", value + " saved as a manual selection.\\nThis does not verify flash compatibility.")

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
            self.q.put(("__VARIANT__", "MGU ID7/ID8 architecture not established"))
            self.q.put(("__HWEL__", ", ".join(v for k, v in result["records"] if k == "HWEL") or "Not reported"))
            self.q.put(("__CAFD__", ", ".join(v for k, v in result["records"] if k == "CAFD") or "Not reported"))
            self.q.put(("__COMPAT__", self.classify_compatibility(result["records"])))
            rows = [f"MGU responded through gateway {gateway}:6801",
                    "BTLD: " + btld,
                    "MGU IP: " + (ip or "Not returned"),
                    "Variant: unverified; software and CAFD alone do not establish ID8-BDC3 vs ID8-BCP.",
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
        """Read-only upstream catalog gate, NOT a flash approval or architecture proof."""
        bootloaders = [value for kind, value in records if kind == "BTLD"]
        if not bootloaders:
            return "Unknown: no BTLD record"
        ids = [value.split("_", 1)[0].upper() for value in bootloaders]
        if "00003F36" not in ids:
            return "BTLD outside upstream 00003F36 gate; unverified"
        return "00003F36 catalog match; architecture unverified"

    def compatibility_details(self):
        """Explain evidence and require independent variant verification."""
        btld = self.software.get()
        hwel = self.hardware.get()
        cafd = self.cafd.get()
        messagebox.showinfo(
            "MGU Compatibility — Read Only",
            f"Manual architecture: {self.arch_choice.get()} (not independently verified)\\n\\n"
            "Observed MGU identity:\n"
            f"BTLD: {btld}\nHWEL: {hwel}\nCAFD: {cafd}\n\n"
            "Upstream SSH project checks the 00003F36 BTLD catalog identifier. "
            "A matching identifier does NOT confirm the correct flash architecture.\\n\\n"
            "The project's separate architecture choices are ID7, ID8-BDC3 and ID8-BCP. "
            "This diagnostic tool cannot reliably distinguish them using the current SVK data. "
            "Verify architecture independently before considering any programming.\\n\\n"
            "This app performs read-only diagnostics only; no flash or SSH activation."
        )

    def external_backup(self):
        """Record user-confirmed external backup without asserting restore validity."""
        dialog = tk.Toplevel(self)
        dialog.title("External MGU Coding Backup")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Backup stored on another device").pack(anchor="w")
        ttk.Label(panel, text="Backup source:").pack(anchor="w", pady=(12, 2))
        ttk.Combobox(panel, textvariable=self.backup_kind, state="readonly",
                     values=("BimmerCode (Android)", "BimmerCode (iOS)",
                             "E-Sys (external device)", "Other external backup")).pack(fill="x")
        ttk.Label(panel, text="This records your confirmation only; it does not inspect or verify the backup.",
                  wraplength=370).pack(anchor="w", pady=12)
        def confirm():
            source = self.backup_kind.get()
            try:
                self.save_backup_preference(source)
            except OSError as exc:
                messagebox.showwarning("Backup preference", "Could not save backup preference: " + str(exc))
                return
            self.backup_state.set(source + " — user-confirmed; restore unverified")
            self.output.configure(state="normal")
            self.output.insert("end", "External MGU coding backup recorded: " + source +
                               "\nNo file was accessed. Restore compatibility, full coding recovery "
                               "and Digital Key pairings are NOT verified.\n\n")
            self.output.configure(state="disabled")
            self.output.see("end")
            dialog.destroy()
        ttk.Button(panel, text="Confirm external backup", command=confirm).pack(anchor="e")

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

    def upstream_status(self):
        """Run only the upstream project's documented read-only status action."""
        script = Path(self.upstream_status_script.get().strip()).expanduser()
        if script.name != "ssh_enable.py" or not script.is_file():
            messagebox.showerror("Upstream SSH status",
                "Select ssh_enable.py from a locally downloaded copy of the upstream project.")
            return
        gateway = self.gateway.get().strip()
        mgu_ip = self.mgu_ip.get().strip()
        try:
            ipaddress.IPv4Address(gateway)
            ipaddress.IPv4Address(mgu_ip)
        except ValueError:
            messagebox.showerror("Upstream SSH status", "Discover the gateway and read MGU identity first.")
            return
        architecture = {"ID8-BDC3": "id8-bdc3", "ID8-BCP": "id8-bcp", "ID7": "id7"}.get(
            self.arch_choice.get())
        if not architecture:
            messagebox.showerror("Upstream SSH status", "Choose an architecture first.")
            return
        if not messagebox.askokcancel("Run upstream status",
            "This launches code from the selected local project on your PC.\\n"
            "Only its documented 'status' action will be requested.\\n"
            "It reads the debug DTC and checks SSH connectivity; it does not request flashing.\\n"
            "Use only a source you trust. Continue?"):
            return
        self.state.set("Running upstream read-only status…")
        def worker():
            try:
                cmd = [sys.executable if not getattr(sys, "frozen", False) else
                       (shutil.which("python") or "python"),
                       str(script.resolve()), "status", "--gateway", gateway,
                       "--mgu-ip", mgu_ip, "--arch", architecture, "--no-log"]
                p = subprocess.run(cmd, cwd=str(script.parent), stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=90, shell=False)
                output = ("Upstream SSH status (read-only action)\\n" +
                          (p.stdout + "\\n" + p.stderr).strip())
                self.q.put((output, "Upstream status completed" if p.returncode == 0
                            else f"Upstream status failed (exit {p.returncode})"))
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.q.put((str(exc), "Upstream status failed"))
        Thread(target=worker, daemon=True).start()

    def ssh_readiness(self):
        """Inspect SSH prerequisites without attempting authentication or writes."""
        host = self.mgu_ip.get().strip()
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            messagebox.showinfo("SSH readiness", "Read MGU Identity first to obtain the head-unit IP.")
            return
        key_name = self.key.get().strip()
        def task():
            lines = ["MGU SSH readiness — no changes made", "MGU IP: " + host]
            lines.append("Architecture: " + self.arch_choice.get() + " (manual; unverified)")
            client = shutil.which("ssh")
            lines.append("Windows SSH client: " + ("available" if client else "not found"))
            if key_name:
                key_path = Path(key_name).expanduser()
                lines.append("Selected SSH private key: " +
                             ("file present (authentication not verified)" if key_path.is_file()
                              else "file not found"))
            else:
                lines.append("Selected SSH private key: none")
            try:
                with socket.create_connection((host, 22), timeout=3):
                    port_status = "TCP port 22 open (authentication not verified)"
            except OSError:
                port_status = "TCP port 22 closed or unreachable"
            self.q.put(("__SSH__", port_status))
            lines.append("SSH endpoint: " + port_status)
            lines.append("Root SSH activation: not performed")
            lines.append("MGU Store installation: unavailable until authorized SSH and compatibility are verified")
            lines.append("BimmerCode coding backup does not establish full firmware recovery.")
            return "\n".join(lines)
        self.run_task(task)

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
                if output in ('__GATEWAY__', '__MGU__', '__SOFTWARE__', '__VARIANT__', '__SSH__', '__COMPAT__', '__BACKUP__', '__HWEL__', '__CAFD__'):
                    {'__GATEWAY__': self.gateway, '__MGU__': self.mgu_ip, '__SOFTWARE__': self.software, '__VARIANT__': self.variant, '__SSH__': self.ssh_status, '__COMPAT__': self.compatibility, '__BACKUP__': self.backup_state, '__HWEL__': self.hardware, '__CAFD__': self.cafd}[output].set(status)
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
