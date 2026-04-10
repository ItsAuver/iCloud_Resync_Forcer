"""
iCloud Re-Sync Tool
Touches all files in a selected folder (recursively) to update their
Last Modified timestamp, forcing iCloud to recognize them as changed
and re-sync them.
"""

import os
import sys
import time
import json
import shutil
import subprocess
import tempfile
import threading
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

VERSION = "1.0.0"
GITHUB_REPO = "ItsAuver/iCloud_Resync_Forcer"

HAS_WINDND = False
HAS_TKDND = False
if sys.platform == "win32":
    try:
        import windnd
        HAS_WINDND = True
    except ImportError:
        pass

if not HAS_WINDND:
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        HAS_TKDND = True
    except ImportError:
        pass


class TouchApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"iCloud Re-Sync Tool  v{VERSION}")
        self.root.geometry("540x500")
        self.root.resizable(False, False)
        self.running = False
        self.targets = []  # list of file/folder paths

        # --- Target list ---
        frame_top = ttk.LabelFrame(root, text="Targets (drag and drop files/folders here)", padding=10)
        frame_top.pack(fill="x", padx=12, pady=(12, 6))

        list_frame = ttk.Frame(frame_top)
        list_frame.pack(fill="x")

        self.target_listbox = tk.Listbox(list_frame, height=5, font=("Consolas", 9),
                                         selectmode="extended")
        list_scroll = ttk.Scrollbar(list_frame, command=self.target_listbox.yview)
        self.target_listbox.configure(yscrollcommand=list_scroll.set)
        self.target_listbox.pack(side="left", fill="x", expand=True)
        list_scroll.pack(side="right", fill="y")

        btn_frame = ttk.Frame(frame_top)
        btn_frame.pack(fill="x", pady=(6, 0))

        ttk.Button(btn_frame, text="Add Folder…", command=self.browse_folder).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Add Files…", command=self.browse_files).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Clear All", command=self.clear_targets).pack(side="left")

        # --- Drag-and-drop support ---
        if HAS_WINDND:
            windnd.hook_dropfiles(root, func=self._on_drop_windnd)
        elif HAS_TKDND:
            for widget in (root, self.target_listbox, frame_top):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop_tkdnd)

        # --- Options ---
        frame_opts = ttk.LabelFrame(root, text="Options", padding=10)
        frame_opts.pack(fill="x", padx=12, pady=6)

        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_opts, text="Include subfolders (recursive)",
                        variable=self.recursive_var).pack(anchor="w")

        self.hidden_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_opts, text="Include hidden files (starting with .)",
                        variable=self.hidden_var).pack(anchor="w")

        # --- Action ---
        frame_action = ttk.Frame(root, padding=(12, 6))
        frame_action.pack(fill="x")

        self.btn_run = ttk.Button(frame_action, text="Touch All Files ▶",
                                  command=self.start)
        self.btn_run.pack(side="left", padx=(0, 4))

        self.btn_restart_icloud = ttk.Button(frame_action, text="Restart iCloud",
                                             command=self.restart_icloud)
        self.btn_restart_icloud.pack(side="left", padx=(0, 4))

        ttk.Button(frame_action, text="Guide", command=self.show_guide).pack(side="left")

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frame_action, textvariable=self.status_var,
                  foreground="gray").pack(side="right")

        # --- Progress ---
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(6, 2))

        # --- Log ---
        frame_log = ttk.LabelFrame(root, text="Log", padding=6)
        frame_log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        self.log = tk.Text(frame_log, height=8, state="disabled",
                           font=("Consolas", 9), wrap="word")
        self.log.tag_configure("error", foreground="red")
        scrollbar = ttk.Scrollbar(frame_log, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

    # ── helpers ────────────────────────────────────────────

    def log_msg(self, msg, error=False):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", "error" if error else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def add_target(self, path):
        """Add a file or folder path to the target list (no duplicates)."""
        path = os.path.normpath(path)
        if path not in self.targets and (os.path.isfile(path) or os.path.isdir(path)):
            self.targets.append(path)
            self.target_listbox.insert("end", path)
            return True
        return False

    def remove_selected(self):
        """Remove selected items from the target list."""
        for idx in reversed(self.target_listbox.curselection()):
            self.targets.pop(idx)
            self.target_listbox.delete(idx)

    def clear_targets(self):
        """Remove all items from the target list."""
        self.targets.clear()
        self.target_listbox.delete(0, "end")

    def _on_drop_windnd(self, paths):
        """Callback for windnd — receives a list of bytes paths."""
        for raw in paths:
            path = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            self.add_target(path)

    def _on_drop_tkdnd(self, event):
        """Callback for tkinterdnd2 — receives an event with .data string."""
        raw = event.data.strip()
        parsed = []
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.index("}", i)
                parsed.append(raw[i + 1 : end])
                i = end + 2
            elif raw[i] == " ":
                i += 1
            else:
                end = raw.find(" ", i)
                if end == -1:
                    end = len(raw)
                parsed.append(raw[i:end])
                i = end + 1

        for path in parsed:
            self.add_target(path)

    def browse_folder(self):
        path = filedialog.askdirectory(title="Select folder to re-sync")
        if path:
            self.add_target(path)

    def browse_files(self):
        paths = filedialog.askopenfilenames(title="Select files to re-sync")
        for path in paths:
            self.add_target(path)

    def start(self):
        if not self.targets:
            messagebox.showwarning("No targets",
                                   "Please add files or folders first.\n"
                                   "Drag and drop, or use the Add buttons.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Working…")

        targets = list(self.targets)
        threading.Thread(target=self.touch_files, args=(targets,), daemon=True).start()

    def touch_files(self, targets):
        recursive = self.recursive_var.get()
        include_hidden = self.hidden_var.get()
        touched = 0
        skipped = 0
        errors = 0
        now = time.time()

        self.root.after(0, self.log_msg,
                        f"── Started at {datetime.now().strftime('%H:%M:%S')} ──")
        self.root.after(0, self.log_msg,
                        f"Targets: {len(targets)}  |  Recursive: {recursive}")

        for target in targets:
            if os.path.isfile(target):
                # Touch individual file directly
                fname = os.path.basename(target)
                if not include_hidden and fname.startswith("."):
                    skipped += 1
                    continue
                try:
                    os.utime(target, (now, now))
                    touched += 1
                except Exception as e:
                    errors += 1
                    self.root.after(0, lambda m=f"  ERR: {target} — {e}": self.log_msg(m, error=True))

            elif os.path.isdir(target):
                # Walk folder
                walker = os.walk(target) if recursive else [(target, [], os.listdir(target))]

                for dirpath, dirnames, filenames in walker:
                    if not include_hidden:
                        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

                    for fname in filenames:
                        if not include_hidden and fname.startswith("."):
                            skipped += 1
                            continue

                        fpath = os.path.join(dirpath, fname)
                        try:
                            os.utime(fpath, (now, now))
                            touched += 1
                        except Exception as e:
                            errors += 1
                            self.root.after(0, lambda m=f"  ERR: {fpath} — {e}": self.log_msg(m, error=True))

        summary = f"Done. Touched {touched} file(s), skipped {skipped}, errors {errors}."
        self.root.after(0, self.log_msg, summary)
        self.root.after(0, self.log_msg, "")
        self.root.after(0, self.finish, summary)

    def finish(self, summary):
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.status_var.set(summary)
        self.running = False

    def restart_icloud(self):
        if self.running:
            return
        self.running = True
        self.btn_restart_icloud.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self.status_var.set("Restarting iCloud…")
        threading.Thread(target=self._restart_icloud_worker, daemon=True).start()

    def _restart_icloud_worker(self):
        self.root.after(0, self.log_msg,
                        f"── iCloud restart at {datetime.now().strftime('%H:%M:%S')} ──")

        killed = _kill_icloud_processes()
        if killed:
            self.root.after(0, self.log_msg,
                            f"Stopped {len(killed)} process(es): {', '.join(killed)}")
            # Brief pause to let processes fully exit
            time.sleep(2)
        else:
            self.root.after(0, self.log_msg, "No running iCloud processes found.")

        launch = _find_icloud_launch()
        if launch:
            method, value = launch
            try:
                if method == "store":
                    subprocess.Popen(
                        ["explorer.exe", f"shell:AppsFolder\\{value}"],
                    )
                else:
                    subprocess.Popen([value], creationflags=_NO_WINDOW)
                self.root.after(0, self.log_msg, f"Started: {value}")
                msg = "iCloud restarted."
            except Exception as e:
                self.root.after(0, lambda m=f"  ERR: Could not start iCloud — {e}": self.log_msg(m, error=True))
                msg = "iCloud stopped but failed to restart."
        else:
            self.root.after(0, lambda: self.log_msg(
                "  Could not find iCloud executable to relaunch. "
                "Please start iCloud manually.", error=True))
            msg = "iCloud stopped. Relaunch manually."

        self.root.after(0, self.log_msg, "")
        self.root.after(0, self._finish_restart, msg)

    def _finish_restart(self, msg):
        self.btn_restart_icloud.configure(state="normal")
        self.btn_run.configure(state="normal")
        self.status_var.set(msg)
        self.running = False

    def show_guide(self):
        guide = tk.Toplevel(self.root)
        guide.title("How to Use This Program")
        guide.resizable(False, False)
        guide.grab_set()

        text = tk.Text(guide, wrap="word", font=("Segoe UI", 10),
                       padx=16, pady=12, width=58, height=28,
                       relief="flat", bg=guide.cget("bg"))
        text.pack(fill="both", expand=True)

        bold = ("Segoe UI", 10, "bold")
        heading = ("Segoe UI", 12, "bold")
        text.tag_configure("h", font=heading, spacing3=4)
        text.tag_configure("b", font=bold)
        text.tag_configure("body", spacing1=2, spacing3=2)

        def h(s):
            text.insert("end", s + "\n", "h")

        def b(s):
            text.insert("end", s, "b")

        def t(s):
            text.insert("end", s, "body")

        h("What does this program do?")
        t("Sometimes iCloud gets stuck and stops syncing your files. "
          "This tool fixes that by gently \"nudging\" your files so "
          "iCloud notices them again and uploads them.\n\n"
          "It does NOT change the contents of your files. "
          "It only updates the date so iCloud thinks they are new.\n\n")

        h("Step 1 -- Add your files or folders")
        b("Drag and drop: ")
        t("Drag files or folders from File Explorer straight "
          "into the white list at the top of the window.\n\n")
        b("Browse: ")
        t("Click \"Add Folder\" or \"Add Files\" to pick them "
          "from a dialog.\n\n"
          "You can add as many items as you like. "
          "To remove something, select it in the list and click "
          "\"Remove Selected\", or click \"Clear All\" to start over.\n\n")

        h("Step 2 -- Choose your options")
        b("Include subfolders: ")
        t("When checked, the tool will also process files inside "
          "any folders within the folders you added. "
          "Leave this on unless you only want the top level.\n\n")
        b("Include hidden files: ")
        t("Hidden files (whose names start with a dot) are "
          "skipped by default. You usually don't need to change this.\n\n")

        h("Step 3 -- Click \"Touch All Files\"")
        t("The tool will go through every file and nudge it. "
          "Progress and any errors will appear in the Log area "
          "at the bottom.\n\n")

        h("Restart iCloud")
        t("If syncing is still stuck after touching your files, "
          "click \"Restart iCloud\". This will close iCloud completely "
          "and reopen it, which often clears stubborn sync issues.\n\n")

        h("Tips")
        t("  - You can use this tool as many times as you need.\n"
          "  - It's safe to run on any folder, not just iCloud folders.\n"
          "  - If something goes wrong, errors appear in red in the Log.")

        text.configure(state="disabled")

        btn = ttk.Button(guide, text="Got it!", command=guide.destroy)
        btn.pack(pady=(0, 12))

        guide.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - guide.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - guide.winfo_height()) // 2
        guide.geometry(f"+{x}+{y}")


# ── iCloud process helpers ────────────────────────────────────

# CREATE_NO_WINDOW prevents console pop-ups from subprocess calls
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Process names that belong to iCloud on Windows (explicit list)
ICLOUD_PROCESS_NAMES = [
    "iCloud.exe",
    "iCloudDrive.exe",
    "iCloudHome.exe",
    "iCloudPhotos.exe",
    "iCloudServices.exe",
    "iCloud Keychain Sync.exe",
    "ApplePhotoStreams.exe",
    "APSDaemon.exe",
]


def _get_running_icloud_processes():
    """Return a set of iCloud-related process image names currently running."""
    if sys.platform != "win32":
        return set()
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        running = set()
        for line in result.stdout.splitlines():
            # CSV format: "ImageName","PID",...
            if not line:
                continue
            name = line.split(",")[0].strip('"')
            name_lower = name.lower()
            # Skip our own process
            if "resync" in name_lower:
                continue
            if "icloud" in name_lower or name in ICLOUD_PROCESS_NAMES:
                running.add(name)
        return running
    except Exception:
        return set()


def _kill_icloud_processes():
    """Kill all running iCloud processes.  Returns list of names that were killed."""
    if sys.platform != "win32":
        return []
    targets = _get_running_icloud_processes()
    killed = []
    for name in targets:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            killed.append(name)
    return killed


def _find_icloud_launch():
    """Locate how to launch iCloud.  Returns (method, value) or None.

    method is "exe" (value = path) or "store" (value = app user model ID).
    """
    if sys.platform != "win32":
        return None

    # Desktop (MSI) install — direct exe paths
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Apple\iCloud\iCloud.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Apple\Internet Services\iCloud.exe"),
        os.path.expandvars(r"%ProgramFiles%\Apple\Internet Services\iCloud.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return ("exe", path)

    # Fallback: search PATH
    try:
        result = subprocess.run(
            ["where.exe", "iCloud.exe"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            return ("exe", result.stdout.strip().splitlines()[0])
    except Exception:
        pass

    # Microsoft Store install — query for the app's user model ID
    try:
        ps_cmd = (
            "Get-AppxPackage -Name '*iCloud*' | "
            "Get-AppxPackageManifest | "
            "ForEach-Object { $_.Package.Applications.Application } | "
            "Select-Object -ExpandProperty Id -First 1"
        )
        pkg_cmd = (
            "(Get-AppxPackage -Name '*iCloud*').PackageFamilyName"
        )
        app_id_result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        pkg_result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", pkg_cmd],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        app_id = app_id_result.stdout.strip()
        pkg_family = pkg_result.stdout.strip()
        if app_id and pkg_family:
            return ("store", f"{pkg_family}!{app_id}")
    except Exception:
        pass

    return None


# ── Auto-update helpers ──────────────────────────────────────

def _cleanup_old_update_files():
    """Remove leftover .old and .tmp files from a previous update."""
    if not getattr(sys, "frozen", False):
        return
    exe_dir = os.path.dirname(sys.executable)
    for name in os.listdir(exe_dir):
        if name.endswith(".old") or name.endswith(".tmp"):
            try:
                os.remove(os.path.join(exe_dir, name))
            except OSError:
                pass


def _parse_version(tag):
    """Turn 'v1.2.3' into (1, 2, 3) for comparison."""
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def _asset_name():
    """Return the expected release-asset filename for this platform."""
    if sys.platform == "win32":
        return "iCloud_ReSyncTool.exe"
    elif sys.platform == "darwin":
        return "iCloud_ReSyncTool-macos"
    else:
        return "iCloud_ReSyncTool-linux"


def _check_for_update():
    """Query GitHub for the latest release.  Returns (tag, download_url) or None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    latest_tag = data.get("tag_name", "")
    if not latest_tag:
        return None

    try:
        if _parse_version(latest_tag) <= _parse_version(VERSION):
            return None
    except (ValueError, TypeError):
        return None

    want = _asset_name()
    for asset in data.get("assets", []):
        if asset["name"] == want:
            return latest_tag, asset["browser_download_url"]
    return None


def _apply_update(download_url, progress_cb=None, done_cb=None):
    """Download the new binary and replace the running executable."""
    try:
        current_exe = sys.executable if getattr(sys, "frozen", False) else None
        if not current_exe:
            if done_cb:
                done_cb(False, "Cannot self-update when running from source.")
            return

        req = urllib.request.Request(download_url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            chunks = []
            downloaded = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    progress_cb(downloaded, total)
            new_bytes = b"".join(chunks)

        # Write to a temp file next to the current exe
        exe_dir = os.path.dirname(current_exe)
        fd, tmp_path = tempfile.mkstemp(dir=exe_dir, suffix=".tmp")
        os.write(fd, new_bytes)
        os.close(fd)

        if sys.platform == "win32":
            # Windows: can't overwrite a running exe, so rename-swap
            old_path = current_exe + ".old"
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass  # locked from a prior update; will be cleaned up next launch
            os.rename(current_exe, old_path)
            shutil.move(tmp_path, current_exe)
        else:
            os.chmod(tmp_path, os.stat(current_exe).st_mode)
            shutil.move(tmp_path, current_exe)

        if done_cb:
            done_cb(True, None)
    except Exception as e:
        if done_cb:
            done_cb(False, str(e))


class UpdateDialog(tk.Toplevel):
    """Modal dialog that offers a one-click update."""

    def __init__(self, parent, latest_tag, download_url):
        super().__init__(parent)
        self.title("Update Available")
        self.download_url = download_url
        self.parent = parent
        self.resizable(False, False)
        self.grab_set()

        pad = dict(padx=16, pady=(14, 4))
        ttk.Label(
            self,
            text=f"A new version is available: {latest_tag}  (you have v{VERSION})",
        ).pack(**pad)

        self.progress = ttk.Progressbar(self, length=320, mode="determinate")
        self.progress.pack(padx=16, pady=6)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=(4, 14))

        self.btn_update = ttk.Button(btn_frame, text="Update Now", command=self._do_update)
        self.btn_update.pack(side="left", padx=4)

        self.btn_skip = ttk.Button(btn_frame, text="Skip", command=self.destroy)
        self.btn_skip.pack(side="left", padx=4)

        # Centre on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _do_update(self):
        self.btn_update.configure(state="disabled")
        self.btn_skip.configure(state="disabled")
        threading.Thread(
            target=_apply_update,
            args=(self.download_url, self._on_progress, self._on_done),
            daemon=True,
        ).start()

    def _on_progress(self, downloaded, total):
        pct = downloaded / total * 100
        self.after(0, lambda: self.progress.configure(value=pct))

    def _on_done(self, success, error):
        if success:
            self.after(0, self._restart_prompt)
        else:
            self.after(0, lambda: self._show_error(error))

    def _restart_prompt(self):
        messagebox.showinfo(
            "Update complete",
            "The update has been installed.\n"
            "Please reopen the application to use the new version.",
            parent=self,
        )
        self.parent.destroy()
        sys.exit(0)

    def _show_error(self, error):
        messagebox.showerror("Update failed", f"Could not update:\n{error}", parent=self)
        self.btn_update.configure(state="normal")
        self.btn_skip.configure(state="normal")


def _background_update_check(root):
    """Run the update check in a thread; show dialog on the main thread if needed."""
    def check():
        result = _check_for_update()
        if result:
            root.after(0, lambda: UpdateDialog(root, result[0], result[1]))
    threading.Thread(target=check, daemon=True).start()


def main():
    _cleanup_old_update_files()

    root = TkinterDnD.Tk() if HAS_TKDND else tk.Tk()
    # Windows DPI awareness for crisp text
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    TouchApp(root)

    # Check for updates after the UI is visible
    root.after(500, lambda: _background_update_check(root))

    root.mainloop()


if __name__ == "__main__":
    main()
