"""CindeCode Studio: a portable, local-first Windows video workbench."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.error
import urllib.request
import webbrowser

APP_VERSION = "0.1.0"
REPO = "taikhoanzaizai-ux/cindeCode"
OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"
VIDEO_TYPES = [("Videos", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All files", "*.*")]
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SETTINGS_FILE = DATA / "settings.json"


def find_executable(name: str) -> str | None:
    local = ROOT / "tools" / (name + (".exe" if os.name == "nt" else ""))
    return str(local) if local.is_file() else shutil.which(name)


def run_command(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=(
                              subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))


def ollama_request(endpoint: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(OLLAMA_URL + endpoint, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def read_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def secs(value: str) -> float:
    """Parse seconds or HH:MM:SS(.mmm)."""
    value = value.strip()
    if not value:
        return 0.0
    items = value.split(":")
    if len(items) > 3:
        raise ValueError("Mốc thời gian không hợp lệ.")
    try:
        parts = [float(p) for p in items]
    except ValueError as exc:
        raise ValueError("Thời gian phải là số giây hoặc HH:MM:SS.") from exc
    if any(x < 0 for x in parts):
        raise ValueError("Thời gian không được âm.")
    result = 0.0
    for v in parts:
        result = result * 60 + v
    return result


def safe_subtitle(s: str) -> str:
    """Text is passed as a value, never as shell code."""
    return s.replace("\r", " ").replace("\n", " ").strip()


def ffmpeg_render(source: Path, target: Path, start: float, end: float | None,
                  ratio: str, caption: str, log) -> None:
    exe = find_executable("ffmpeg")
    if not exe:
        raise RuntimeError("Chưa tìm thấy FFmpeg. Cài FFmpeg hoặc đặt ffmpeg.exe trong thư mục tools.")
    if source.resolve() == target.resolve():
        raise ValueError("Không được ghi đè video gốc.")
    if end is not None and end <= start:
        raise ValueError("Thời điểm kết thúc phải lớn hơn bắt đầu.")
    filters = []
    if ratio != "Gốc":
        w, h = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[ratio]
        filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        filters.append("setsar=1")
    if caption:
        # drawtext requires fonts and platform-specific escaping; add a simple
        # SRT overlay via a temporary sidecar file instead.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="cindecode-") as tmp:
            srt = Path(tmp) / "caption.srt"
            # Keep subtitle path straightforward for FFmpeg on Windows via cwd.
            duration = (end-start) if end is not None else 36000
            def stamp(t: float) -> str:
                milliseconds = int(max(t, 0) * 1000)
                hours, milliseconds = divmod(milliseconds, 3600000)
                minutes, milliseconds = divmod(milliseconds, 60000)
                seconds, milliseconds = divmod(milliseconds, 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
            srt.write_text(f"1\n00:00:00,000 --> {stamp(duration)}\n{safe_subtitle(caption)}\n", encoding="utf-8")
            # A temporary copy next to output avoids escaping Windows drive colons.
            overlay = target.parent / (target.stem + ".caption.tmp.srt")
            try:
                shutil.copyfile(srt, overlay)
                subtitle_expr = overlay.name.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
                filters.append(f"subtitles='{subtitle_expr}'")
                _execute_ffmpeg(exe, source, target, start, end, filters, log, target.parent)
            finally:
                overlay.unlink(missing_ok=True)
    else:
        _execute_ffmpeg(exe, source, target, start, end, filters, log, target.parent)


def _execute_ffmpeg(exe, source, target, start, end, filters, log, cwd):
    cmd = [exe, "-hide_banner", "-y", "-ss", str(start), "-i", str(source)]
    if end is not None:
        cmd.extend(["-t", str(end-start)])
    if filters:
        cmd.extend(["-vf", ",".join(filters)])
    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)])
    log("Đang xuất MP4 bằng FFmpeg…")
    # Never shell=True, never execute generated model text.
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
    if proc.returncode:
        target.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg lỗi:\n" + proc.stderr[-2200:])
    log("Đã xuất: " + str(target))


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CindeCode AI Studio " + APP_VERSION)
        self.geometry("1020x720")
        self.minsize(800, 620)
        self.settings = read_settings()
        self.events: queue.Queue = queue.Queue()
        self.video = tk.StringVar()
        self.output = tk.StringVar(value=str(ROOT / "exports"))
        self.model = tk.StringVar(value=self.settings.get("model", DEFAULT_MODEL))
        self.start_time = tk.StringVar(value="0")
        self.end_time = tk.StringVar()
        self.ratio = tk.StringVar(value="Gốc")
        self.status = tk.StringVar(value="Sẵn sàng")
        self._build()
        self.after(120, self.poll_events)
        self.after(300, self.check_dependencies)

    def log(self, message):
        self.events.put(("log", message))

    def async_task(self, fn):
        def worker():
            try:
                fn()
            except Exception as exc:
                self.log("LỖI: " + str(exc))
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _build(self):
        pad = {"padx": 10, "pady": 6}
        header = ttk.Frame(self)
        header.pack(fill="x", padx=14, pady=12)
        ttk.Label(header, text="CindeCode AI Studio", font=("Segoe UI", 19, "bold")).pack(side="left")
        ttk.Button(header, text="Kiểm tra cập nhật", command=self.check_update).pack(side="right")
        ttk.Button(header, text="Kiểm tra môi trường", command=self.check_dependencies).pack(side="right", padx=8)

        pane = ttk.Notebook(self)
        pane.pack(fill="both", expand=True, padx=14)
        edit = ttk.Frame(pane)
        ai = ttk.Frame(pane)
        pane.add(edit, text="Dựng video")
        pane.add(ai, text="AI / Ollama")

        src = ttk.LabelFrame(edit, text="Video nguồn")
        src.pack(fill="x", padx=10, pady=8)
        ttk.Entry(src, textvariable=self.video).pack(side="left", fill="x", expand=True, **pad)
        ttk.Button(src, text="Chọn video", command=self.select_video).pack(side="left", **pad)
        ttk.Button(src, text="Xem trước", command=self.preview).pack(side="left", **pad)

        settings = ttk.LabelFrame(edit, text="Cắt video và tỷ lệ")
        settings.pack(fill="x", padx=10, pady=8)
        ttk.Label(settings, text="Bắt đầu (giây hoặc HH:MM:SS)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(settings, textvariable=self.start_time, width=17).grid(row=0, column=1, **pad)
        ttk.Label(settings, text="Kết thúc (để trống = hết)").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(settings, textvariable=self.end_time, width=17).grid(row=0, column=3, **pad)
        ttk.Label(settings, text="Tỷ lệ khung hình").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.ratio, values=["Gốc", "16:9", "9:16", "1:1"], width=14,
                     state="readonly").grid(row=1, column=1, **pad)
        ttk.Label(settings, text="Chữ trên video (tùy chọn)").grid(row=2, column=0, sticky="w", **pad)
        self.caption = ttk.Entry(settings, width=65)
        self.caption.grid(row=2, column=1, columnspan=3, sticky="ew", **pad)
        settings.columnconfigure(3, weight=1)

        dest = ttk.LabelFrame(edit, text="Xuất video — chọn ổ D:, E: hoặc thư mục bất kỳ")
        dest.pack(fill="x", padx=10, pady=8)
        ttk.Entry(dest, textvariable=self.output).pack(side="left", fill="x", expand=True, **pad)
        ttk.Button(dest, text="Chọn thư mục", command=self.select_output).pack(side="left", **pad)
        ttk.Button(edit, text="XUẤT VIDEO MP4", command=self.render).pack(pady=12)

        row = ttk.Frame(ai)
        row.pack(fill="x", padx=14, pady=12)
        ttk.Label(row, text="Mô hình local: ").pack(side="left")
        ttk.Entry(row, textvariable=self.model, width=28).pack(side="left", padx=4)
        ttk.Button(row, text="Kiểm tra Ollama", command=self.check_ollama).pack(side="left", padx=4)
        ttk.Button(row, text="Tải Qwen Coder", command=self.pull_model).pack(side="left", padx=4)
        ttk.Label(ai, text="Nhập yêu cầu để AI lập kế hoạch dựng phim. Phiên bản này KHÔNG tự thực thi mã AI.",
                  foreground="#555").pack(anchor="w", padx=14)
        self.prompt = tk.Text(ai, height=5, wrap="word")
        self.prompt.pack(fill="x", padx=14, pady=8)
        self.prompt.insert("1.0", "Hãy đề xuất kịch bản 1 phút, cảnh quay, âm thanh và hiệu ứng dựng video.")
        ttk.Button(ai, text="Tạo kế hoạch với Qwen", command=self.ask_model).pack(pady=4)
        self.response = tk.Text(ai, height=15, wrap="word")
        self.response.pack(fill="both", expand=True, padx=14, pady=8)

        bottom = ttk.LabelFrame(self, text="Trạng thái / Nhật ký")
        bottom.pack(fill="both", padx=14, pady=10)
        ttk.Label(bottom, textvariable=self.status).pack(anchor="w", padx=8)
        self.logs = tk.Text(bottom, height=6, wrap="word", state="disabled")
        self.logs.pack(fill="both", expand=True, padx=6, pady=4)

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.status.set(value)
                    self.logs.configure(state="normal")
                    self.logs.insert("end", value + "\n")
                    self.logs.see("end")
                    self.logs.configure(state="disabled")
                elif kind == "response":
                    self.response.delete("1.0", "end")
                    self.response.insert("1.0", value)
                elif kind == "error":
                    messagebox.showerror("CindeCode", value)
                elif kind == "update":
                    self._update_dialog(value)
        except queue.Empty:
            pass
        self.after(120, self.poll_events)

    def select_video(self):
        item = filedialog.askopenfilename(filetypes=VIDEO_TYPES)
        if item:
            self.video.set(item)

    def select_output(self):
        folder = filedialog.askdirectory(initialdir=self.output.get() if Path(self.output.get()).exists() else str(ROOT))
        if folder:
            self.output.set(folder)

    def preview(self):
        source = Path(self.video.get())
        if not source.is_file():
            messagebox.showwarning("Chọn video", "Chọn video nguồn trước.")
            return
        player = find_executable("ffplay")
        if player:
            subprocess.Popen([player, "-autoexit", str(source)])
        elif os.name == "nt":
            os.startfile(str(source))
        else:
            webbrowser.open(source.as_uri())

    def render(self):
        source = Path(self.video.get())
        if not source.is_file():
            messagebox.showwarning("Chọn video", "Chọn video nguồn trước.")
            return
        try:
            start = secs(self.start_time.get())
            end = secs(self.end_time.get()) if self.end_time.get().strip() else None
            if end is not None and end <= start:
                raise ValueError("Thời gian kết thúc phải lớn hơn bắt đầu.")
        except ValueError as exc:
            messagebox.showerror("Lỗi thời gian", str(exc))
            return
        out = Path(self.output.get())
        ratio = self.ratio.get()
        cap = self.caption.get()
        def work():
            out.mkdir(parents=True, exist_ok=True)
            target = out / (source.stem + "_cindecode.mp4")
            ffmpeg_render(source, target, start, end, ratio, cap, self.log)
        self.async_task(work)

    def check_dependencies(self):
        ffmpeg = find_executable("ffmpeg")
        player = find_executable("ffplay")
        self.log("FFmpeg: " + (ffmpeg or "CHƯA CÀI"))
        self.log("FFplay: " + (player or "Dùng trình phát mặc định"))
        self.check_ollama()

    def check_ollama(self):
        def work():
            try:
                data = ollama_request("/api/tags", timeout=5)
                names = [m.get("name", "") for m in data.get("models", [])]
                self.log("Ollama hoạt động. Models: " + (", ".join(names) or "chưa có"))
            except Exception:
                self.log("Ollama chưa chạy tại 127.0.0.1:11434. Cài và mở Ollama trước.")
        self.async_task(work)

    def pull_model(self):
        name = self.model.get().strip()
        if not name or any(ch.isspace() for ch in name):
            messagebox.showerror("Model", "Tên mô hình không hợp lệ.")
            return
        if not messagebox.askyesno("Tải mô hình", f"Tải {name} qua Ollama? File có thể nặng nhiều GB."):
            return
        def work():
            self.log("Đang tải model " + name + "…")
            ollama_request("/api/pull", {"name": name, "stream": False}, timeout=7200)
            self.log("Đã tải model: " + name)
        self.async_task(work)

    def ask_model(self):
        content = self.prompt.get("1.0", "end").strip()
        name = self.model.get().strip()
        if not content or not name:
            return
        self.settings["model"] = name
        save_settings(self.settings)
        def work():
            self.log("Qwen đang lập kế hoạch…")
            result = ollama_request("/api/generate", {
                "model": name, "stream": False,
                "system": "Bạn là trợ lý đạo diễn và biên tập video. Trả lời tiếng Việt; "
                          "đưa timeline, khung hình, chữ, âm thanh, tài nguyên cần có. "
                          "Không giả định đã tạo tệp hoặc chạy lệnh.",
                "prompt": content
            }, timeout=600)
            self.events.put(("response", result.get("response", "(Không có kết quả)")))
            self.log("Đã nhận kế hoạch từ Qwen.")
        self.async_task(work)

    def check_update(self):
        def work():
            request = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/latest",
                headers={"User-Agent": "CindeCode-Studio"})
            try:
                with urllib.request.urlopen(request, timeout=15) as res:
                    release = json.load(res)
                self.events.put(("update", release))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    self.log("Chưa có GitHub Release. Không tự tải mã từ nhánh main để thực thi.")
                else:
                    raise
        self.async_task(work)

    def _update_dialog(self, release):
        version = str(release.get("tag_name", "")).lstrip("v")
        assets = release.get("assets") or []
        url = release.get("html_url", f"https://github.com/{REPO}/releases")
        if not version or version == APP_VERSION:
            messagebox.showinfo("Cập nhật", "Bạn đang dùng phiên bản " + APP_VERSION)
        elif messagebox.askyesno("Có phiên bản mới", f"Hiện tại: {APP_VERSION}\nGitHub: {version}\n"
                                 "Mở trang Release để tải và kiểm tra bản phát hành?"):
            webbrowser.open(url)
        # Deliberately no execution of downloaded unverified code.


if __name__ == "__main__":
    Studio().mainloop()
