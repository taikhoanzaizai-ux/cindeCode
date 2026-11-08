"""Safe media pipeline: localhost Ollama + FFmpeg; no arbitrary AI-generated code execution."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = "taikhoanzaizai-ux/cindeCode"

def check_deps():
    return "FFmpeg: " + ("đã tìm thấy" if shutil.which("ffmpeg") else "CHƯA CÀI hoặc chưa thêm vào PATH") + " | FFprobe: " + ("OK" if shutil.which("ffprobe") else "thiếu")

def _request_json(url, payload=None):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL không hợp lệ")
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "CineCodeAIStudio/0.1"})
    with urlopen(req, timeout=120 if data else 15) as resp:
        return json.load(resp)

def build_plan(instructions, model, endpoint):
    host = urlparse(endpoint)
    if host.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Chỉ chấp nhận Ollama trên máy tính (localhost).")
    system = ("You are a safe Vietnamese video edit planner. Return ONLY a JSON object with keys "
              "'remove_silence' (boolean), 'title' (short string, max 80 chars), "
              "'notes' (short Vietnamese sentence). No code, no shell commands, no other keys. "
              "Only suggest operations supported by the app: silence trimming and a title card.")
    reply = _request_json(endpoint.rstrip("/") + "/api/chat", {
        "model": model, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": instructions}]
    })
    content = reply.get("message", {}).get("content", "")
    result = json.loads(content)
    return {
        "remove_silence": result.get("remove_silence") is True,
        "title": str(result.get("title", ""))[:80],
        "notes": str(result.get("notes", ""))[:500]
    }

def _cmd(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-2500:])
    return p.stdout

def _duration(video):
    return float(_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video]).strip())

def _kept_intervals(video, duration):
    # Detect silence using audio energy. If there is no audio stream, preserve entire video.
    process = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-af",
         "silencedetect=noise=-35dB:d=0.65", "-f", "null", "-"],
         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(process.stderr[-2000:])
    intervals, start = [], None
    for line in process.stderr.splitlines():
        match_s = re.search(r"silence_start:\s*([0-9.]+)", line)
        match_e = re.search(r"silence_end:\s*([0-9.]+)", line)
        if match_s: start = float(match_s.group(1))
        if match_e and start is not None:
            intervals.append((start, float(match_e.group(1))))
            start = None
    if start is not None: intervals.append((start, duration))
    kept, pos = [], 0.0
    for a, b in intervals:
        a, b = max(0, a - 0.12), min(duration, b + 0.12)
        if a - pos > 0.2: kept.append((pos, a))
        pos = max(pos, b)
    if duration - pos > 0.2: kept.append((pos, duration))
    return kept or [(0.0, duration)]

def _has_audio(video):
    return bool(_cmd(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", video]).strip())

def render_video(source, output, plan, log=lambda s: None):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Cần cài FFmpeg và FFprobe, rồi khởi động lại ứng dụng.")
    source = str(Path(source).resolve())
    output = Path(output).resolve()
    if source == str(output): raise ValueError("File đầu ra phải khác file đầu vào.")
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = _duration(source)
    if duration <= 0: raise ValueError("Video không có thời lượng hợp lệ.")
    segments = _kept_intervals(source, duration) if plan.get("remove_silence") else [(0.0, duration)]
    # Encode each segment to a common profile before concat. Use the source's audio if present.
    has_audio = _has_audio(source)
    log(f"Giữ {len(segments)} đoạn, trên tổng {duration:.1f} giây.")
    with tempfile.TemporaryDirectory(prefix="cinecode-", dir=str(output.parent)) as td:
        clips = []
        for i, (start, stop) in enumerate(segments):
            if stop - start < .1: continue
            clip = str(Path(td) / f"clip{i:04}.mp4")
            args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(start), "-i", source, "-t", str(stop - start),
                    "-map", "0:v:0", "-map", "0:a:0?"]
            if not has_audio: args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-map", "1:a:0", "-shortest"]
            args += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                     "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", clip]
            _cmd(args)
            clips.append(clip)
            log(f"Đã xử lý đoạn {i+1}/{len(segments)}")
        if not clips: raise RuntimeError("Không còn đoạn video hợp lệ.")
        manifest = Path(td) / "concat.txt"
        manifest.write_text("".join("file '" + Path(p).name + "'\n" for p in clips), encoding="utf-8")
        joined = str(Path(td) / "joined.mp4")
        _cmd(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "1", "-i", str(manifest), "-c", "copy", joined])
        # Title overlay uses FFmpeg's drawtext and requires an installed Unicode font. 
        # For portability, a title is drawn only if the font file exists.
        title = str(plan.get("title") or "").strip()[:80]
        if title:
            font_candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
                               Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
            font = next((p for p in font_candidates if p.is_file()), None)
            if font:
                title_file = Path(td) / "title.txt"
                title_file.write_text(title, encoding="utf-8")
                def esc(p): return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
                vf = "drawtext=fontfile='" + esc(font) + "':textfile='" + esc(title_file) + "':fontcolor=white:fontsize=h/22:x=(w-text_w)/2:y=h*0.83:box=1:boxcolor=black@0.5:boxborderw=15:enable='lt(t,4)'"
                _cmd(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", joined,
                      "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "copy", "-movflags", "+faststart", str(output)])
            else:
                log("Không tìm thấy font phù hợp; bỏ qua tiêu đề.")
                shutil.copy2(joined, output)
        else: shutil.copy2(joined, output)
    return str(output)

def check_update(current):
    # A new GitHub Release is necessary; code commits alone never trigger unverified updates.
    release = _request_json(f"https://api.github.com/repos/{REPO}/releases/latest")
    tag = str(release.get("tag_name", "")).lstrip("v")
    def numbers(v):
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    return release if numbers(tag) > numbers(current) else None

def fetch_update(release, base):
    """Download only. Do not silently execute arbitrary packages received from a network."""
    assets = release.get("assets", [])
    candidates = [a for a in assets if str(a.get("name", "")).endswith("-windows-portable.zip")]
    if not candidates: raise RuntimeError("Bản phát hành chưa có ZIP cho Windows.")
    asset = candidates[0]
    target_dir = Path(base) / "updates"
    target_dir.mkdir(exist_ok=True)
    target = target_dir / Path(asset["name"]).name
    url = asset["browser_download_url"]
    if urlparse(url).hostname not in ("github.com", "objects.githubusercontent.com"):
        raise RuntimeError("Nguồn tải không nằm trên GitHub.")
    req = Request(url, headers={"User-Agent": "CineCodeAIStudio/0.1"})
    with urlopen(req, timeout=180) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)
    return "Đã tải " + str(target) + ". Đóng ứng dụng, giải nén và thay các file chương trình (không ghi đè data/)."
