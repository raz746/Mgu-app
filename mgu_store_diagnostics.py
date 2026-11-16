"""Read-only MGU Store diagnostics for authorized head units."""
import subprocess
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from threading import Thread
from queue import Queue, Empty

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MGU Store Diagnostics — Phase 1")
        self.geometry("780x510")
        self.q = Queue()
        self.host = tk.StringVar(value="172.16.222.97")
        self.key = tk.StringVar()
        self.script = tk.StringVar()
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
        ttk.Button(buttons, text="Test SSH", command=self.test_ssh).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Read MGU Store Status", command=self.status).pack(side="left")
        self.state = tk.StringVar(value="Ready — no changes will be made")
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
        key = Path(self.key.get()).expanduser()
        if not key.is_file():
            raise ValueError("Select your existing SSH private key.")
        return host, str(key)

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

    def test_ssh(self):
        try:
            host, key = self.inputs()
            if not shutil.which("ssh"):
                raise ValueError("Windows OpenSSH client not found.")
            self.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                      "-o", "StrictHostKeyChecking=yes", "-i", key,
                      f"root@{host}", "printf MGU_SSH_OK"])
        except ValueError as exc:
            messagebox.showerror("Connection", str(exc))

    def status(self):
        try:
            host, key = self.inputs()
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
