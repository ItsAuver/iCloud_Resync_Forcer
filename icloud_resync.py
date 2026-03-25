"""
iCloud Re-Sync Tool
Touches all files in a selected folder (recursively) to update their
Last Modified timestamp, forcing iCloud to recognize them as changed
and re-sync them.
"""

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False


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
        if HAS_DND:
            for widget in (root, entry, frame_top):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

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
        scrollbar = ttk.Scrollbar(frame_log, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

    # ── helpers ────────────────────────────────────────────

    def log_msg(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_drop(self, event):
        path = event.data.strip()
        # tkdnd wraps paths containing spaces in curly braces
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        # If a file was dropped, use its parent folder
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if os.path.isdir(path):
            self.folder_var.set(path)

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
                    self.root.after(0, self.log_msg, f"  ERR: {fpath} — {e}")

        summary = f"Done. Touched {touched} file(s), skipped {skipped}, errors {errors}."
        self.root.after(0, self.log_msg, summary)
        self.root.after(0, self.log_msg, "")
        self.root.after(0, self.finish, summary)

    def finish(self, summary):
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.status_var.set(summary)
        self.running = False


def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    # Windows DPI awareness for crisp text
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    TouchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
