import yt_dlp
import sys
import os
import threading
import queue
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def get_ffmpeg_path():
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "ffmpeg_bin")


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name if name else "audio"


class YTDownloaderGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("URL Converter")
        self.geometry("800x560")
        self.minsize(700, 500)

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self.stop_requested = False

        self.output_dir = tk.StringVar(value=os.getcwd())
        self.url_var = tk.StringVar(value="")

        self.use_custom_name = tk.BooleanVar(value=False)
        self.custom_name_var = tk.StringVar(value="")
        self.use_numbering = tk.BooleanVar(value=False)
        self.track_number_var = tk.IntVar(value=1)

        self.auto_increment = tk.BooleanVar(value=True)

        self._build_ui()
        self._poll_queue()
        self._update_option_states()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = 10

        style = ttk.Style(self)
        try:
            style.configure("Big.TButton", padding=(14, 10), font=("Segoe UI", 11, "bold"))
        except Exception:
            style.configure("Big.TButton", padding=(14, 10))

        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", padx=pad, pady=(pad, 0))

        ttk.Label(frm_top, text="YouTube URL:").pack(anchor="w")
        self.url_entry = ttk.Entry(frm_top, textvariable=self.url_var)
        self.url_entry.pack(fill="x", pady=(4, 0))
        self.url_entry.focus_set()

        frm_dir = ttk.Frame(self)
        frm_dir.pack(fill="x", padx=pad, pady=(pad, 0))

        ttk.Label(frm_dir, text="Output folder:").grid(row=0, column=0, sticky="w")
        self.dir_entry = ttk.Entry(frm_dir, textvariable=self.output_dir)
        self.dir_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(frm_dir, text="Browse…", command=self.choose_dir).grid(
            row=1, column=1, padx=(8, 0), pady=(4, 0)
        )
        frm_dir.columnconfigure(0, weight=1)

        frm_opts = ttk.LabelFrame(self, text="Options")
        frm_opts.pack(fill="x", padx=pad, pady=(pad, 0))

        row1 = ttk.Frame(frm_opts)
        row1.pack(fill="x", padx=pad, pady=(8, 4))
        ttk.Checkbutton(
            row1,
            text="Use custom name",
            variable=self.use_custom_name,
            command=self._update_option_states
        ).pack(side="left")
        self.name_entry = ttk.Entry(row1, textvariable=self.custom_name_var)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))

        row2 = ttk.Frame(frm_opts)
        row2.pack(fill="x", padx=pad, pady=(4, 10))

        ttk.Checkbutton(
            row2,
            text="Numbering",
            variable=self.use_numbering,
            command=self._update_option_states
        ).pack(side="left")

        ttk.Label(row2, text="No.:").pack(side="left", padx=(12, 4))
        self.spin_nr = tk.Spinbox(
            row2, from_=1, to=999, width=5, textvariable=self.track_number_var
        )
        self.spin_nr.pack(side="left")

        self.cb_auto = ttk.Checkbutton(
            row2,
            text="Auto-increment number after download",
            variable=self.auto_increment,
            command=self._update_option_states
        )
        self.cb_auto.pack(side="left", padx=(12, 0))

        self.preview_lbl = ttk.Label(row2, text="")
        self.preview_lbl.pack(side="left", padx=(12, 0))
        self._update_preview()

        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill="x", padx=pad, pady=(pad, 0))

        self.btn_start = ttk.Button(
            frm_btn,
            text="Start download",
            style="Big.TButton",
            command=self.start_download
        )
        self.btn_start.pack(side="left")

        self.btn_cancel = ttk.Button(
            frm_btn,
            text="Cancel",
            command=self.request_stop,
            state="disabled"
        )
        self.btn_cancel.pack(side="left", padx=(10, 0), pady=(2, 0))

        self.btn_clear_log = ttk.Button(
            frm_btn,
            text="Clear log",
            command=self.clear_log
        )
        self.btn_clear_log.pack(side="left", padx=(10, 0), pady=(2, 0))

        frm_prog = ttk.Frame(self)
        frm_prog.pack(fill="x", padx=pad, pady=(pad, 0))

        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=100)
        self.progress.pack(fill="x")

        self.lbl_status = ttk.Label(frm_prog, text="Ready.")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        frm_log = ttk.Frame(self)
        frm_log.pack(fill="both", expand=True, padx=pad, pady=pad)

        ttk.Label(frm_log, text="Log:").pack(anchor="w")
        self.txt_log = tk.Text(frm_log, height=10, wrap="word")
        self.txt_log.pack(fill="both", expand=True, pady=(4, 0))
        self.txt_log.configure(state="disabled")

        self.txt_log.tag_configure("ok", foreground="green")
        self.txt_log.tag_configure("error", foreground="red")
        self.txt_log.tag_configure("normal", foreground="black")

        self.custom_name_var.trace_add("write", lambda *_: self._update_preview())
        self.track_number_var.trace_add("write", lambda *_: self._update_preview())
        self.use_custom_name.trace_add("write", lambda *_: self._update_preview())
        self.use_numbering.trace_add("write", lambda *_: self._update_preview())
        self.auto_increment.trace_add("write", lambda *_: self._update_option_states())

    def choose_dir(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    def _update_option_states(self):
        self.name_entry.configure(
            state=("normal" if self.use_custom_name.get() else "disabled")
        )
        self.spin_nr.configure(
            state=("normal" if self.use_numbering.get() else "disabled")
        )
        self.cb_auto.configure(
            state=("normal" if self.use_numbering.get() else "disabled")
        )
        self._update_preview()

    def _update_preview(self):
        parts = []
        if self.use_numbering.get():
            parts.append(f"{int(self.track_number_var.get()):03d} -")

        if self.use_custom_name.get():
            parts.append(sanitize_filename(self.custom_name_var.get()))
        else:
            parts.append("%(title)s")

        self.preview_lbl.configure(text="Preview: " + " ".join(parts) + ".mp3")

    # ---------------- Log ----------------
    def log(self, text, tag="normal"):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    # ---------------- Download ----------------
    def build_outtmpl(self, out_dir: str) -> str:
        prefix = ""
        if self.use_numbering.get():
            prefix = f"{int(self.track_number_var.get()):03d} - "

        if self.use_custom_name.get():
            base = prefix + sanitize_filename(self.custom_name_var.get())
        else:
            base = prefix + "%(title)s"

        return os.path.join(out_dir, base + ".%(ext)s")

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing", "Please enter a YouTube URL.")
            return

        out_dir = self.output_dir.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showwarning("Output folder", "Please select a valid output folder.")
            return

        if self.use_custom_name.get() and not self.custom_name_var.get().strip():
            messagebox.showwarning(
                "Name missing",
                "Please enter a name or disable the custom name option."
            )
            return

        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Running", "A download is already in progress.")
            return

        self.stop_requested = False
        self.progress["value"] = 0
        self.set_status("Starting…")

        self.log(f"Starting download: {url}", "normal")
        self.log(
            f"Saving as: {self.preview_lbl.cget('text').replace('Preview: ', '')}",
            "normal"
        )

        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        self.worker_thread = threading.Thread(
            target=self._download_worker, args=(url, out_dir), daemon=True
        )
        self.worker_thread.start()

    def request_stop(self):
        self.stop_requested = True
        self.log("Cancel requested…", "error")
        self.set_status("Cancel requested…")

    def _progress_hook_factory(self):
        def progress_hook(d):
            if self.stop_requested:
                raise Exception("Cancelled by user")

            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    percent = downloaded / total * 100
                    self.msg_queue.put(("progress", percent))
                    self.msg_queue.put(("status", f"Downloading: {percent:.2f}%"))
            elif status == "finished":
                self.msg_queue.put(("status", "Download finished, converting to MP3…"))
                self.msg_queue.put(
                    ("log", ("Download finished, converting to MP3...", "normal"))
                )
        return progress_hook

    def _download_worker(self, url, out_dir):
        ffmpeg_path = get_ffmpeg_path()
        ydl_opts["ffmpeg_location"] = ffmpeg_path if os.path.exists(ffmpeg_path) else "ffmpeg"
        outtmpl = self.build_outtmpl(out_dir)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "progress_hooks": [self._progress_hook_factory()],
            "nocheckcertificate": True,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/117.0.0.0 Safari/537.36"
            ),
            "ffmpeg_location": ffmpeg_path,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            self.msg_queue.put(("progress", 100))
            self.msg_queue.put(("status", "Done!"))
            self.msg_queue.put(("log", ("Download completed!", "ok")))
            self.msg_queue.put(("success", None))

        except Exception as e:
            self.msg_queue.put(("status", "Error / Cancelled."))
            self.msg_queue.put(("log", (f"Error: {e}", "error")))

        finally:
            self.msg_queue.put(("done", None))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()

                if kind == "progress":
                    self.progress["value"] = max(0, min(100, float(payload)))

                elif kind == "status":
                    self.set_status(str(payload))

                elif kind == "log":
                    text, tag = payload
                    self.log(str(text), tag)

                elif kind == "success":
                    if self.use_numbering.get() and self.auto_increment.get():
                        try:
                            current = int(self.track_number_var.get())
                            if current < 999:
                                self.track_number_var.set(current + 1)
                        except Exception:
                            pass
                    self._update_preview()

                elif kind == "done":
                    self.btn_start.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")

        except queue.Empty:
            pass

        self.after(100, self._poll_queue)


if __name__ == "__main__":
    app = YTDownloaderGUI()
    app.mainloop()
