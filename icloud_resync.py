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
        self.root.title("iCloud Re-Sync Tool")
        self.root.geometry("540x420")
        self.root.resizable(False, False)
        self.running = False

        # --- Folder selection ---
        frame_top = ttk.LabelFrame(root, text="Target Folder", padding=10)
        frame_top.pack(fill="x", padx=12, pady=(12, 6))

        self.folder_var = tk.StringVar()
        entry = ttk.Entry(frame_top, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ttk.Button(frame_top, text="Browse…", command=self.browse).pack(side="right")

        # --- Drag-and-drop support ---
        if HAS_WINDND:
            windnd.hook_dropfiles(root, func=self._on_drop_windnd)
        elif HAS_TKDND:
            for widget in (root, entry, frame_top):
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
        self.btn_run.pack(side="left")

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

    def _set_dropped_path(self, path):
        """Resolve a dropped path (file or folder) to a directory and set it."""
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if os.path.isdir(path):
            self.folder_var.set(path)
            return True
        return False

    def _on_drop_windnd(self, paths):
        """Callback for windnd — receives a list of bytes paths."""
        for raw in paths:
            path = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if self._set_dropped_path(path):
                return

    def _on_drop_tkdnd(self, event):
        """Callback for tkinterdnd2 — receives an event with .data string."""
        raw = event.data.strip()
        # tkdnd may return multiple paths: brace-wrapped or space-separated
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
            if self._set_dropped_path(path):
                return

    def browse(self):
        path = filedialog.askdirectory(title="Select folder to re-sync")
        if path:
            self.folder_var.set(path)

    def start(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("No folder", "Please select a valid folder first.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Working…")

        threading.Thread(target=self.touch_files, args=(folder,), daemon=True).start()

    def touch_files(self, folder):
        recursive = self.recursive_var.get()
        include_hidden = self.hidden_var.get()
        touched = 0
        skipped = 0
        errors = 0
        now = time.time()

        self.root.after(0, self.log_msg,
                        f"── Started at {datetime.now().strftime('%H:%M:%S')} ──")
        self.root.after(0, self.log_msg,
                        f"Folder: {folder}  |  Recursive: {recursive}")

        walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]

        for dirpath, dirnames, filenames in walker:
            # Optionally skip hidden dirs
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


# ── Auto-update helpers ──────────────────────────────────────

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
            if os.path.exists(old_path):
                os.remove(old_path)
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
            "The application has been updated.\nIt will now restart.",
            parent=self,
        )
        exe = sys.executable
        self.parent.destroy()
        subprocess.Popen([exe] + sys.argv[1:])
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
