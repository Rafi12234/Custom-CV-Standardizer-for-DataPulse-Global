# app/ui.py
# Tkinter UI for CV Standardizer.

import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, scrolledtext, ttk

from app.file_helper import open_output_folder
from app.main import process_folder

_BG         = "#f0f4f8"
_PRIMARY    = "#1a3c5e"
_SECONDARY  = "#2e7fc1"
_BTN_FG     = "#ffffff"
_LOG_BG     = "#1e1e2e"
_LOG_FG     = "#cdd6f4"
_SUCCESS    = "#a6e3a1"
_ERROR      = "#f38ba8"
_WARNING    = "#fab387"
_INFO       = "#89b4fa"


class CVStandardizerApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("CV Standardizer")
        self.configure(bg=_BG)
        self.resizable(True, True)
        self.minsize(700, 560)
        self._selected_folder = tk.StringVar(value="No folder selected")
        self._is_processing   = False
        self._build_ui()
        self._center_window(820, 640)

    def _center_window(self, w: int, h: int) -> None:
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self) -> None:
        # Banner
        banner = tk.Frame(self, bg=_PRIMARY, padx=20, pady=14)
        banner.pack(fill="x")
        tk.Label(
            banner, text="CV Standardizer",
            font=font.Font(family="Helvetica", size=18, weight="bold"),
            bg=_PRIMARY, fg=_BTN_FG,
        ).pack(side="left")
        tk.Label(
            banner, text="Powered by Google Gemini  •  Direct PDF Analysis",
            font=("Helvetica", 9, "italic"),
            bg=_PRIMARY, fg="#a0b8d0",
        ).pack(side="right", padx=4)

        # Content
        content = tk.Frame(self, bg=_BG, padx=20, pady=16)
        content.pack(fill="both", expand=True)

        self._build_folder_section(content)
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=10)
        self._build_action_buttons(content)

        self._progress = ttk.Progressbar(content, mode="indeterminate")
        self._progress.pack(fill="x", pady=(6, 4))

        self._build_log_area(content)
        self._build_bottom_bar()

    def _build_folder_section(self, parent) -> None:
        row = tk.Frame(parent, bg=_BG)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(
            row, text="Select CV Folder:",
            font=("Helvetica", 10, "bold"),
            bg=_BG, fg=_PRIMARY,
        ).pack(side="left")
        self._browse_btn = tk.Button(
            row, text="Browse Folder",
            command=self._browse_folder,
            bg=_SECONDARY, fg=_BTN_FG,
            relief="flat", padx=14, pady=5,
            font=("Helvetica", 9, "bold"),
            cursor="hand2",
        )
        self._browse_btn.pack(side="right")

        path_frame = tk.Frame(parent, bg="#d9e8f5", relief="groove", bd=1)
        path_frame.pack(fill="x", pady=(0, 4))
        tk.Label(
            path_frame,
            textvariable=self._selected_folder,
            bg="#d9e8f5", fg=_PRIMARY,
            anchor="w", font=("Helvetica", 9),
            wraplength=680, justify="left",
            padx=10, pady=6,
        ).pack(fill="x")

    def _build_action_buttons(self, parent) -> None:
        row = tk.Frame(parent, bg=_BG)
        row.pack(fill="x", pady=(0, 4))
        self._generate_btn = tk.Button(
            row, text="⚙  Analyze & Generate Standardized CVs",
            command=self._start_processing,
            bg=_PRIMARY, fg=_BTN_FG,
            relief="flat", padx=20, pady=8,
            font=("Helvetica", 10, "bold"),
            cursor="hand2",
        )
        self._generate_btn.pack(side="left")
        tk.Button(
            row, text="🗑  Clear Log",
            command=self._clear_log,
            bg="#888", fg=_BTN_FG,
            relief="flat", padx=14, pady=8,
            font=("Helvetica", 9),
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

    def _build_log_area(self, parent) -> None:
        tk.Label(
            parent, text="Processing Log:",
            font=("Helvetica", 9, "bold"),
            bg=_BG, fg=_PRIMARY, anchor="w",
        ).pack(fill="x")
        self._log_text = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            bg=_LOG_BG, fg=_LOG_FG,
            font=("Courier", 9),
            relief="flat", bd=0,
            state="disabled",
            padx=10, pady=8,
        )
        self._log_text.pack(fill="both", expand=True, pady=(4, 0))
        self._log_text.tag_config("success", foreground=_SUCCESS)
        self._log_text.tag_config("error",   foreground=_ERROR)
        self._log_text.tag_config("warning", foreground=_WARNING)
        self._log_text.tag_config("info",    foreground=_INFO)
        self._log_text.tag_config("normal",  foreground=_LOG_FG)

    def _build_bottom_bar(self) -> None:
        bar = tk.Frame(self, bg=_PRIMARY, padx=20, pady=8)
        bar.pack(fill="x", side="bottom")
        tk.Button(
            bar, text="📂  Open Output Folder",
            command=open_output_folder,
            bg=_SECONDARY, fg=_BTN_FG,
            relief="flat", padx=14, pady=5,
            font=("Helvetica", 9, "bold"),
            cursor="hand2",
        ).pack(side="right")
        self._status_label = tk.Label(
            bar, text="Ready.",
            bg=_PRIMARY, fg="#a0b8d0",
            font=("Helvetica", 9),
        )
        self._status_label.pack(side="left")

    # ── Events ────────────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder containing CV PDFs")
        if folder:
            self._selected_folder.set(folder)
            self._log_message(f"Folder selected: {folder}", tag="info")
            self._set_status("Folder selected. Click Generate to start.")

    def _start_processing(self) -> None:
        if self._is_processing:
            messagebox.showwarning("Busy", "Processing is already in progress.")
            return
        folder = self._selected_folder.get()
        if not folder or folder == "No folder selected":
            messagebox.showerror("No Folder", "Please select a folder first.")
            return

        self._is_processing = True
        self._generate_btn.config(state="disabled", text="⏳  Processing...")
        self._browse_btn.config(state="disabled")
        self._progress.start(12)
        self._set_status("Processing CVs via Gemini... please wait.")
        self._log_message(
            "━" * 60 + "\nStarting CV processing...\n" + "━" * 60,
            tag="info",
        )
        threading.Thread(
            target=self._run_processing, args=(folder,), daemon=True
        ).start()

    def _run_processing(self, folder: str) -> None:
        try:
            summary = process_folder(folder, status_callback=self._thread_safe_log)
            self.after(0, self._on_done, summary)
        except EnvironmentError as exc:
            self.after(0, self._on_error, str(exc))
        except ValueError as exc:
            self.after(0, self._on_error, str(exc))
        except Exception as exc:
            self.after(0, self._on_error, f"Unexpected error: {exc}")

    def _on_done(self, summary: dict) -> None:
        self._stop_busy()
        success = summary["success_count"]
        failed  = summary["failed_count"]
        total   = summary["total_files"]

        tag = "success" if failed == 0 else ("warning" if success > 0 else "error")
        self._log_message(
            f"\n✔ Done! {success}/{total} CV(s) processed successfully.",
            tag=tag,
        )

        if summary.get("json_path"):
            self._log_message(f"  JSON  → {summary['json_path']}", tag="info")

        for p in summary.get("output_pdfs", []):
            self._log_message(f"  PDF   → {p}", tag="info")

        if summary["failed_files"]:
            self._log_message(
                "\n⚠ Failed:\n  " + "\n  ".join(summary["failed_files"]),
                tag="warning",
            )

        self._set_status(
            f"Done. {success}/{total} succeeded."
            + (f" {failed} failed." if failed else "")
        )

        if success == 0:
            messagebox.showwarning(
                "No Output",
                "No CVs were processed successfully.\nCheck the log for details.",
            )
        else:
            pdfs_text = "\n".join(
                f"  • {Path(p).name}" for p in summary.get("output_pdfs", [])
            )
            messagebox.showinfo(
                "Complete",
                f"Processing finished!\n\n"
                f"✔ Successful : {success}\n"
                f"✘ Failed     : {failed}\n\n"
                f"Individual PDFs generated:\n{pdfs_text}\n\n"
                f"All files saved in the 'output/' folder.",
            )

    def _on_error(self, message: str) -> None:
        self._stop_busy()
        self._log_message(f"\n✘ Error: {message}", tag="error")
        self._set_status("Error occurred. See log.")
        messagebox.showerror("Error", message)

    def _stop_busy(self) -> None:
        self._is_processing = False
        self._progress.stop()
        self._generate_btn.config(
            state="normal", text="⚙  Analyze & Generate Standardized CVs"
        )
        self._browse_btn.config(state="normal")

    # ── Logging ───────────────────────────────────────────────────────────────

    def _thread_safe_log(self, message: str) -> None:
        self.after(0, self._log_message, message)

    def _log_message(self, message: str, tag: str = "normal") -> None:
        self._log_text.config(state="normal")
        if tag == "normal":
            low = message.lower()
            if "✔" in message or "success" in low or "done" in low:
                tag = "success"
            elif "✘" in message or "fail" in low or "error" in low:
                tag = "error"
            elif "⚠" in message or "warn" in low:
                tag = "warning"
            elif "→" in message or "uploading" in low or "waiting" in low:
                tag = "info"
        self._log_text.insert("end", message + "\n", tag)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    def _set_status(self, message: str) -> None:
        self._status_label.config(text=message)


# ── Entry point ───────────────────────────────────────────────────────────────

def start_app() -> None:
    CVStandardizerApp().mainloop()