# /api/index.py
import os
import re
import uuid
import zipfile
import tempfile
import json
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, Response
from io import BytesIO

# ── yt-dlp & requests ──
try:
    import yt_dlp
    HAS_YT_DLP = True
except ImportError:
    HAS_YT_DLP = False

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Flask App ──
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# ── Temporary Directory (Vercel compatible) ──
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "vortexdl_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True, parents=True)

# ── In-Memory Store (Serverless compatible) ──
progress_store = {}
batch_store = {}

# ── Cache for info (short-term) ──
INFO_CACHE = {}
INFO_CACHE_TTL = 300

# ═══════════════════════════════════════════════════════════════════
# PLATFORM REGISTRY
# ═══════════════════════════════════════════════════════════════════
PLATFORMS = {
    "youtube.com":      ("YouTube",      "▶",   "#ff0000"),
    "youtu.be":         ("YouTube",      "▶",   "#ff0000"),
    "tiktok.com":       ("TikTok",       "♪",   "#69c9d0"),
    "instagram.com":    ("Instagram",    "◈",   "#e1306c"),
    "facebook.com":     ("Facebook",     "f",   "#1877f2"),
    "fb.watch":         ("Facebook",     "f",   "#1877f2"),
    "twitter.com":      ("Twitter/X",    "𝕏",   "#1da1f2"),
    "x.com":            ("Twitter/X",    "𝕏",   "#1da1f2"),
    "reddit.com":       ("Reddit",       "⬆",   "#ff4500"),
    "vimeo.com":        ("Vimeo",        "V",   "#1ab7ea"),
    "dailymotion.com":  ("Dailymotion",  "D",   "#0066dc"),
    "twitch.tv":        ("Twitch",       "⬛",  "#9146ff"),
    "pinterest.com":    ("Pinterest",    "P",   "#e60023"),
    "linkedin.com":     ("LinkedIn",     "in",  "#0a66c2"),
    "soundcloud.com":   ("SoundCloud",   "☁",   "#ff5500"),
    "rumble.com":       ("Rumble",       "R",   "#85c742"),
    "bilibili.com":     ("Bilibili",     "B",   "#00a1d6"),
    "ted.com":          ("TED",          "T",   "#e62b1e"),
    "loom.com":         ("Loom",         "L",   "#625df5"),
    "ucshare.com":      ("UCShare",       "U",   "#f5a623"),
    "uc.cn":            ("UCShare",       "U",   "#f5a623"),
}

def detect_platform(url: str):
    u = url.lower()
    for kw, (name, emoji, color) in PLATFORMS.items():
        if kw in u:
            return name, emoji, color
    return None

def get_format_selector(fmt: str) -> str:
    return {
        "360p":   "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
        "720p":   "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "1080p":  "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "mp3":    "bestaudio/best",
    }.get(fmt, "bestvideo[height<=720]+bestaudio/best")

def base_ydl_opts(hook=None) -> dict:
    o = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        "noplaylist": True,
        "extract_flat": False,
    }
    if hook:
        o["progress_hooks"] = [hook]
    return o

def pick_thumbnail(info: dict) -> str:
    t = info.get("thumbnail") or ""
    if not t and info.get("thumbnails"):
        thumbs = [x for x in info["thumbnails"] if x.get("url")]
        if thumbs:
            thumbs.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)
            t = thumbs[0]["url"]
    return t

# ═══════════════════════════════════════════════════════════════════
# UCShare CUSTOM EXTRACTOR
# ═══════════════════════════════════════════════════════════════════
def is_ucshare(url: str) -> bool:
    u = url.lower()
    return "ucshare.com" in u or "uc.cn" in u or "share.uc.cn" in u

def ucshare_extract_info(url: str) -> dict:
    if not HAS_REQUESTS:
        raise Exception("Library 'requests' tidak terinstall")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
        "Referer": "https://www.ucshare.com/",
    }

    resp = _req.get(url, headers=headers, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text

    video_url = None
    for pat in [
        r'"url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
        r'"videoUrl"\s*:\s*"(https?://[^"]+)"',
        r'"video_url"\s*:\s*"(https?://[^"]+)"',
        r'<video[^>]+src=["\']([^"\']+)["\']',
        r'source\s+src=["\']([^"\']+mp4[^"\']*)["\']',
        r'"playUrl"\s*:\s*"(https?://[^"]+)"',
        r'"play_url"\s*:\s*"(https?://[^"]+)"',
        r'data-src=["\']([^"\']+mp4[^"\']*)["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            candidate = m.group(1).replace('\\/', '/').replace('\\u0026', '&')
            if candidate.startswith("http"):
                video_url = candidate
                break

    if not video_url:
        raise Exception("Tidak dapat menemukan URL video di halaman UCShare")

    title = "UCShare Video"
    for pat in [
        r'<title>([^<]+)</title>',
        r'"title"\s*:\s*"([^"]+)"',
        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
        r'<h1[^>]*>([^<]+)</h1>',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            t = m.group(1).strip()
            if t and t.lower() not in ("ucshare", "share", "video"):
                title = t
                break

    thumbnail = ""
    for pat in [
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        r'"thumbnail"\s*:\s*"([^"]+)"',
        r'"cover"\s*:\s*"([^"]+)"',
        r'"poster"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            thumbnail = m.group(1).replace('\\/', '/').replace('\\u0026', '&')
            break

    uploader = "UCShare User"
    for pat in [
        r'"author"\s*:\s*"([^"]+)"',
        r'"nickname"\s*:\s*"([^"]+)"',
        r'"username"\s*:\s*"([^"]+)"',
        r'"name"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            u = m.group(1).strip()
            if u:
                uploader = u
                break

    return {
        "title": title,
        "uploader": uploader,
        "thumbnail": thumbnail,
        "duration": None,
        "video_url": video_url,
        "ext": "mp4",
    }

def ucshare_download(url: str, out_path: str, hook_fn=None) -> dict:
    info = ucshare_extract_info(url)
    video_url = info["video_url"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": url,
    }

    out_file = Path(out_path)
    with _req.get(video_url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(out_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*64):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if hook_fn and total > 0:
                        pct = int(downloaded / total * 100)
                        hook_fn({
                            "status": "downloading",
                            "downloaded_bytes": downloaded,
                            "total_bytes": total,
                            "speed": None
                        })

    if hook_fn:
        hook_fn({"status": "finished"})

    return info

def safe_fname(info: dict, fallback="video") -> str:
    t = re.sub(r'[^\w\s\-.]', '', info.get("title", fallback))
    return t.strip()[:60] or fallback

# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE (Compressed)
# ═══════════════════════════════════════════════════════════════════
HTML = '''<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>VortexDL - Universal Downloader</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono&display=swap" rel="stylesheet">
<style>
:root{--bg:#080b10;--surface:#0e1319;--card:#141920;--border:#1e2730;--accent:#ff2d44;--accent2:#ff6b35;--text:#e8edf3;--muted:#5a6a7a;--dim:#2a3540;--success:#00e5a0;--warn:#ffb830;--error:#ff6b7a;--radius:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh}
.wrap{max-width:800px;margin:0 auto;padding:36px 20px 80px;position:relative;z-index:1}
header{text-align:center;margin-bottom:40px}
.logo-icon{width:46px;height:46px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:12px;display:grid;place-items:center;font-size:20px;margin:0 auto 12px}
h1{font-size:clamp(1.8rem,4vw,2.8rem);font-weight:800;background:linear-gradient(135deg,#fff 30%,var(--accent) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tagline{color:var(--muted);font-family:'DM Mono',monospace;font-size:.8rem;margin-top:4px}
.tab-bar{display:flex;gap:8px;margin-bottom:24px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px}
.tab-btn{flex:1;padding:10px;border:none;background:transparent;color:var(--muted);font-weight:700;border-radius:9px;cursor:pointer}
.tab-btn.active{background:var(--card);color:var(--text)}
.card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:28px}
.input-row{display:flex;gap:10px;margin-bottom:6px}
.url-input{flex:1;background:var(--surface);border:1.5px solid var(--border);border-radius:var(--radius);padding:14px;color:var(--text);font-family:'DM Mono',monospace}
.url-input:focus{border-color:var(--accent);outline:none}
.btn-red{padding:13px 20px;background:linear-gradient(135deg,var(--accent),#c0001a);color:#fff;border:none;border-radius:var(--radius);font-weight:700;cursor:pointer}
.btn-red:disabled{opacity:.5;cursor:not-allowed}
.btn-full{width:100%;margin-top:18px;display:flex;align-items:center;justify-content:center;gap:9px}
.det-bar{display:none;align-items:center;gap:9px;margin-top:10px;padding:9px 14px;background:var(--surface);border-radius:9px;border:1px solid var(--border);font-family:'DM Mono',monospace;font-size:.8rem}
.det-bar.show{display:flex}
.det-dot{width:9px;height:9px;border-radius:50%}
.err-box{display:none;background:rgba(255,45,68,.08);border:1px solid rgba(255,45,68,.3);border-radius:10px;padding:12px 16px;margin-top:14px;color:var(--error);font-family:'DM Mono',monospace}
.err-box.show{display:block}
.loader{display:none;flex-direction:column;align-items:center;gap:14px;padding:28px 0}
.loader.show{display:flex}
.spinner{width:40px;height:40px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.preview{display:none;margin-top:20px}
.preview.show{display:block}
.thumb-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden;margin-bottom:16px}
.thumb-wrap{position:relative;width:100%;padding-top:42%;background:var(--dim)}
.thumb-wrap img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.plat-tag{position:absolute;top:10px;left:10px;padding:4px 11px;border-radius:7px;font-family:'DM Mono',monospace;font-size:.7rem;font-weight:600}
.thumb-meta{padding:14px 18px}
.vid-title{font-size:1rem;font-weight:700;margin-bottom:8px}
.meta-row{display:flex;gap:14px;font-family:'DM Mono',monospace;font-size:.73rem;color:var(--muted)}
.sec-label{font-size:.68rem;font-weight:700;color:var(--muted);text-transform:uppercase;margin-bottom:9px;font-family:'DM Mono',monospace}
.fmt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:7px;margin-bottom:10px}
.fmt-btn{background:var(--surface);border:1.5px solid var(--border);border-radius:10px;padding:9px 6px;text-align:center;cursor:pointer}
.fmt-btn.sel{border-color:var(--accent);background:rgba(255,45,68,.12)}
.fmt-btn input{display:none}
.fi{font-size:1.2rem;display:block}
.fl{display:block;font-size:.8rem;font-weight:600}
.fs{display:block;font-size:.66rem;font-family:'DM Mono',monospace;color:var(--muted)}
.divider{display:flex;align-items:center;gap:9px;margin:14px 0;color:var(--dim);font-family:'DM Mono',monospace}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--border)}
.prog-wrap{display:none;margin-top:14px}
.prog-wrap.show{display:block}
.prog-info{display:flex;justify-content:space-between;font-family:'DM Mono',monospace;font-size:.73rem;color:var(--muted);margin-bottom:7px}
.prog-bg{height:5px;background:var(--dim);border-radius:999px;overflow:hidden}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:999px;width:0%}
.prog-fill.indet{width:30%!important;animation:slide 1.5s infinite}
@keyframes slide{0%{margin-left:-35%}100%{margin-left:100%}}
#batchPane{display:none}
#batchPane.show{display:block}
.batch-textarea{width:100%;min-height:140px;background:var(--surface);border:1.5px solid var(--border);border-radius:var(--radius);padding:14px;color:var(--text);font-family:'DM Mono',monospace;resize:vertical}
.batch-textarea:focus{border-color:var(--accent);outline:none}
.batch-fmt-row{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
.bfmt{padding:7px 14px;background:var(--surface);border:1.5px solid var(--border);border-radius:8px;font-family:'DM Mono',monospace;font-weight:600;color:var(--muted);cursor:pointer}
.bfmt.sel{border-color:var(--accent);color:var(--accent)}
.batch-summary{display:none;align-items:center;gap:10px;margin-top:12px;padding:10px 16px;background:var(--surface);border-radius:10px;border:1px solid var(--border);font-family:'DM Mono',monospace}
.batch-summary.show{display:flex}
.bs-num{font-weight:700;color:var(--accent)}
.overall-bar{margin-top:16px;display:none}
.overall-bar.show{display:block}
.overall-label{font-family:'DM Mono',monospace;font-size:.72rem;color:var(--muted);display:flex;justify-content:space-between;margin-bottom:6px}
.overall-track{height:8px;background:var(--dim);border-radius:999px;overflow:hidden}
.overall-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2),var(--success));border-radius:999px;width:0%}
.queue-list{margin-top:20px;display:flex;flex-direction:column;gap:10px}
.q-item{display:grid;grid-template-columns:72px 1fr auto;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px;position:relative}
.q-item::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px}
.q-item.waiting::before{background:var(--dim)}
.q-item.fetching::before{background:var(--warn)}
.q-item.running::before{background:var(--accent)}
.q-item.done::before{background:var(--success)}
.q-item.error::before{background:var(--error)}
.q-thumb{width:72px;height:48px;border-radius:7px;object-fit:cover;background:var(--dim)}
.q-body{min-width:0}
.q-title{font-size:.85rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q-meta{display:flex;gap:10px;font-family:'DM Mono',monospace;font-size:.68rem;color:var(--muted)}
.q-prog-mini{margin-top:6px;height:3px;background:var(--dim);border-radius:999px}
.q-prog-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:999px;width:0%}
.q-status{text-align:right}
.status-badge{display:inline-flex;padding:3px 9px;border-radius:999px;font-family:'DM Mono',monospace;font-size:.65rem;font-weight:600}
.sb-waiting{background:var(--dim);color:var(--muted)}
.sb-fetching{background:rgba(255,184,48,.15);color:var(--warn)}
.sb-running{background:rgba(255,45,68,.15);color:var(--accent)}
.sb-done{background:rgba(0,229,160,.12);color:var(--success)}
.sb-error{background:rgba(255,45,68,.12);color:var(--error)}
.q-dl-btn{margin-top:6px;padding:3px 10px;font-family:'DM Mono',monospace;font-size:.68rem;font-weight:600;background:rgba(0,229,160,.12);color:var(--success);border:1px solid rgba(0,229,160,.3);border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}
.batch-actions{display:flex;gap:8px;margin-top:20px;flex-wrap:wrap}
.btn-outline{padding:10px 18px;background:transparent;border:1.5px solid var(--border);border-radius:10px;color:var(--muted);font-weight:600;cursor:pointer}
.btn-zip{padding:10px 18px;background:linear-gradient(135deg,#00c87a,#00a060);border:none;border-radius:10px;color:#fff;font-weight:700;cursor:pointer;display:none}
.btn-zip.show{display:inline-flex}
.stats-strip{display:none;gap:16px;margin-top:12px;flex-wrap:wrap}
.stats-strip.show{display:flex}
.stat-pill{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 14px;font-family:'DM Mono',monospace;font-size:.72rem}
footer{text-align:center;margin-top:52px;font-family:'DM Mono',monospace;font-size:.7rem;color:var(--muted)}
@media(max-width:540px){.card{padding:18px}.input-row{flex-direction:column}.btn-red{width:100%}}
</style></head>
<body>
<div class="wrap">
<header>
<div class="logo-icon">⚡</div>
<h1>VortexDL</h1>
<p class="tagline">// universal video downloader</p>
</header>
<div class="tab-bar">
<button class="tab-btn active" id="tabSingle" onclick="switchTab('single')">🎬 Single</button>
<button class="tab-btn" id="tabBatch" onclick="switchTab('batch')">📦 Batch</button>
</div>
<div class="card">
<div id="singlePane">
<div class="input-row">
<input type="url" id="sUrl" class="url-input" placeholder="Paste URL video..." autocomplete="off">
<button class="btn-red" id="sBtnFetch" onclick="singleFetch()">Get Info</button>
</div>
<div class="det-bar" id="sDetBar"><div class="det-dot" id="sDetDot"></div><span id="sDetLabel"></span><span style="color:var(--success);margin-left:auto">✓</span></div>
<div class="loader" id="sLoader"><div class="spinner"></div><p style="font-family:'DM Mono';font-size:.8rem;color:var(--muted);margin-top:10px">Mengambil info...</p></div>
<div class="err-box" id="sErr"></div>
<div class="preview" id="sPreview">
<div class="thumb-card">
<div class="thumb-wrap"><img id="sThumb" src="" alt="thumb"><span class="plat-tag" id="sPlatTag"></span></div>
<div class="thumb-meta">
<p class="vid-title" id="sTitle"></p>
<div class="meta-row"><span id="sUploader"></span><span id="sDur"></span></div>
</div>
</div>
<p class="sec-label">Format</p>
<div class="fmt-grid">
<label class="fmt-btn" onclick="selFmt(this,'s')"><input type="radio" name="sFmt" value="360p"><span class="fi">📺</span><span class="fl">360p</span></label>
<label class="fmt-btn sel" onclick="selFmt(this,'s')"><input type="radio" name="sFmt" value="720p" checked><span class="fi">🎥</span><span class="fl">720p</span></label>
<label class="fmt-btn" onclick="selFmt(this,'s')"><input type="radio" name="sFmt" value="1080p"><span class="fi">🎞</span><span class="fl">1080p</span></label>
<label class="fmt-btn" onclick="selFmt(this,'s')"><input type="radio" name="sFmt" value="mp3"><span class="fi">🎵</span><span class="fl">MP3</span></label>
</div>
<button class="btn-red btn-full" id="sBtnDl" onclick="singleDl()" disabled>⬇ DOWNLOAD</button>
<div class="prog-wrap" id="sProgWrap">
<div class="prog-info"><span id="sProgStatus">...</span><span id="sProgPct">0%</span></div>
<div class="prog-bg"><div class="prog-fill" id="sProgFill"></div></div>
</div>
</div>
</div>
<div id="batchPane">
<textarea class="batch-textarea" id="bTextarea" placeholder="Paste links (satu per baris, max 20)"></textarea>
<p class="sec-label" style="margin-top:16px">Format</p>
<div class="batch-fmt-row">
<button class="bfmt sel" onclick="selBFmt(this,'360p')">360p</button>
<button class="bfmt" onclick="selBFmt(this,'720p')">720p</button>
<button class="bfmt" onclick="selBFmt(this,'1080p')">1080p</button>
<button class="bfmt" onclick="selBFmt(this,'mp3')">MP3</button>
</div>
<div class="batch-summary" id="bSummary"><span class="bs-num" id="bCount">0</span> link</div>
<div class="err-box" id="bErr"></div>
<div class="batch-actions">
<button class="btn-red" id="bBtnStart" onclick="batchStart()">⚡ Start</button>
<button class="btn-outline" onclick="batchClear()">🗑 Clear</button>
<button class="btn-zip" id="bBtnZip" onclick="batchZip()">🗜 ZIP</button>
</div>
<div class="stats-strip" id="bStats">
<div class="stat-pill">✅ <span id="statDone">0</span></div>
<div class="stat-pill">⏳ <span id="statPending">0</span></div>
<div class="stat-pill">❌ <span id="statErr">0</span></div>
</div>
<div class="overall-bar" id="overallBar">
<div class="overall-label"><span id="overallStatus">...</span><span id="overallPct">0%</span></div>
<div class="overall-track"><div class="overall-fill" id="overallFill"></div></div>
</div>
<div class="queue-list" id="queueList"></div>
</div>
</div>
<footer><p>⚡ VortexDL v4.0 · Flask + yt-dlp</p></footer>
</div>
<script>
const PLATS=[["youtube.com","YouTube","#ff0000"],["youtu.be","YouTube","#ff0000"],["tiktok.com","TikTok","#69c9d0"],["instagram.com","Instagram","#e1306c"],["facebook.com","Facebook","#1877f2"],["twitter.com","Twitter","#1da1f2"],["x.com","Twitter","#1da1f2"],["ucshare.com","UCShare","#f5a623"],["uc.cn","UCShare","#f5a623"]];
function detectPlat(u){const l=u.toLowerCase();for(const[k,n,c]of PLATS)if(l.includes(k))return{name:n,color:c};return null}
function fmtDur(s){if(!s)return'';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),t=Math.floor(s%60);return h>0?`${h}:${String(m).padStart(2,'0')}:${String(t).padStart(2,'0')}`:`${m}:${String(t).padStart(2,'0')}`}
function triggerDownload(b,f){const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=f;document.body.appendChild(a);a.click();URL.revokeObjectURL(a.href);a.remove()}
function getFilename(r,f){const d=r.headers.get('Content-Disposition')||'';const m=d.match(/filename\\*?=(?:UTF-8'')?["']?([^"';\\r\\n]+)["']?/i);return m?decodeURIComponent(m[1].trim()):f}
function switchTab(t){document.getElementById('singlePane').style.display=t==='single'?'':'none';document.getElementById('batchPane').classList.toggle('show',t==='batch');document.getElementById('tabSingle').classList.toggle('active',t==='single');document.getElementById('tabBatch').classList.toggle('active',t==='batch')}
let sCurrentUrl='',sPollInterval=null;
document.getElementById('sUrl').addEventListener('input',function(){const p=detectPlat(this.value.trim());const b=document.getElementById('sDetBar');if(p){b.classList.add('show');document.getElementById('sDetDot').style.background=p.color;document.getElementById('sDetLabel').textContent=p.name}else b.classList.remove('show')});
document.getElementById('sUrl').addEventListener('keydown',e=>{if(e.key==='Enter')singleFetch()});
function selFmt(el,p){document.querySelectorAll('.fmt-btn').forEach(b=>b.classList.remove('sel'));el.classList.add('sel')}
function showSErr(m){const e=document.getElementById('sErr');e.innerHTML='⚠ '+m;e.classList.add('show')}
function hideSErr(){document.getElementById('sErr').classList.remove('show')}
async function singleFetch(){const url=document.getElementById('sUrl').value.trim();if(!url){showSErr('Masukkan URL');return}const p=detectPlat(url);if(!p){showSErr('Platform tidak dikenali');return}hideSErr();sCurrentUrl=url;document.getElementById('sLoader').classList.add('show');document.getElementById('sPreview').classList.remove('show');document.getElementById('sBtnFetch').disabled=true;try{const resp=await fetch('/api/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});const data=await resp.json();document.getElementById('sLoader').classList.remove('show');if(!data.success){showSErr(data.error||'Gagal');return}const info=data.info;document.getElementById('sThumb').src=info.thumbnail||'https://placehold.co/640x360/0e1319/333';document.getElementById('sPlatTag').textContent=p.name;document.getElementById('sPlatTag').style.cssText=`background:${p.color}22;color:${p.color}`;document.getElementById('sTitle').textContent=info.title||'Tanpa Judul';document.getElementById('sUploader').textContent=info.uploader||'Unknown';const dur=fmtDur(info.duration);if(dur)document.getElementById('sDur').textContent='· '+dur;document.getElementById('sPreview').classList.add('show');document.getElementById('sBtnDl').disabled=false}catch(e){document.getElementById('sLoader').classList.remove('show');showSErr('Error jaringan')}finally{document.getElementById('sBtnFetch').disabled=false}}
async function singleDl(){if(!sCurrentUrl)return;const fmt=document.querySelector('input[name="sFmt"]:checked')?.value||'720p';const sid=Math.random().toString(36).substring(2);const btn=document.getElementById('sBtnDl');btn.disabled=true;btn.innerHTML='⏳ Processing...';const pw=document.getElementById('sProgWrap'),pf=document.getElementById('sProgFill'),ps=document.getElementById('sProgStatus'),pp=document.getElementById('sProgPct');pw.classList.add('show');pf.classList.add('indet');if(sPollInterval)clearInterval(sPollInterval);sPollInterval=setInterval(async()=>{try{const r=await fetch(`/api/progress/${sid}`);const d=await r.json();if(d.percent!==undefined){pf.classList.remove('indet');pf.style.width=d.percent+'%';pp.textContent=d.percent+'%';ps.textContent=d.status||'...' }}catch{}},800);try{const resp=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:sCurrentUrl,format:fmt,session_id:sid})});clearInterval(sPollInterval);if(!resp.ok){const e=await resp.json().catch(()=>({}));showSErr(e.error||'Gagal');pw.classList.remove('show')}else{pf.style.width='100%';ps.textContent='✓ Selesai';pp.textContent='100%';const blob=await resp.blob();triggerDownload(blob,getFilename(resp,'video.mp4'))}}catch(e){clearInterval(sPollInterval);showSErr('Download gagal');pw.classList.remove('show')}finally{btn.disabled=false;btn.innerHTML='⬇ DOWNLOAD'}}
let bFmt='720p',bItems=[],bRunning=false,bDoneFiles=[];
function selBFmt(el,f){document.querySelectorAll('.bfmt').forEach(b=>b.classList.remove('sel'));el.classList.add('sel');bFmt=f}
document.getElementById('bTextarea').addEventListener('input',parseTextarea);
function parseTextarea(){const lines=document.getElementById('bTextarea').value.split('\\n').map(l=>l.trim()).filter(l=>l.length>0);const valid=lines.filter(l=>detectPlat(l));const summary=document.getElementById('bSummary');if(valid.length>0){summary.classList.add('show');document.getElementById('bCount').textContent=valid.length}else summary.classList.remove('show')}
function showBErr(m){const e=document.getElementById('bErr');e.innerHTML='⚠ '+m;e.classList.add('show')}
function hideBErr(){document.getElementById('bErr').classList.remove('show')}
function batchClear(){document.getElementById('bTextarea').value='';document.getElementById('queueList').innerHTML='';document.getElementById('bSummary').classList.remove('show');document.getElementById('bStats').classList.remove('show');document.getElementById('overallBar').classList.remove('show');document.getElementById('bBtnZip').classList.remove('show');hideBErr();bItems=[];bDoneFiles=[];bRunning=false;updateStats()}
async function batchStart(){if(bRunning)return;const lines=document.getElementById('bTextarea').value.split('\\n').map(l=>l.trim()).filter(l=>l.length>0);const valid=lines.filter(l=>detectPlat(l));if(valid.length===0){showBErr('Tidak ada URL valid');return}if(valid.length>20){showBErr('Max 20 link');return}hideBErr();bItems=[];bDoneFiles=[];bRunning=true;document.getElementById('bBtnStart').disabled=true;document.getElementById('bBtnZip').classList.remove('show');document.getElementById('overallBar').classList.add('show');document.getElementById('bStats').classList.add('show');document.getElementById('queueList').innerHTML='';for(const url of valid){const id='b_'+Math.random().toString(36).substring(2,8);const plat=detectPlat(url);bItems.push({id,url,status:'waiting',info:null,plat,file_id:null});renderQItem(bItems[bItems.length-1])}updateStats();updateOverall();for(const item of bItems){setItemStatus(item,'fetching','');try{const resp=await fetch('/api/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:item.url})});const data=await resp.json();if(data.success){item.info=data.info;updateQItemInfo(item);setItemStatus(item,'queued','')}else setItemStatus(item,'error','Gagal')}}catch(e){setItemStatus(item,'error','Error')}updateStats();updateOverall()}for(const item of bItems){if(item.status==='error')continue;setItemStatus(item,'running','');updateStats();updateOverall();const sid=Math.random().toString(36).substring(2);item.file_id=sid;const poll=setInterval(async()=>{try{const r=await fetch(`/api/progress/${sid}`);const d=await r.json();setItemProgress(item.id,d.percent||0)}catch{}},800);try{const resp=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:item.url,format:bFmt,session_id:sid,save_for_zip:true})});clearInterval(poll);if(!resp.ok){const e=await resp.json().catch(()=>({}));setItemStatus(item,'error','Gagal')}else{setItemProgress(item.id,100);setItemStatus(item,'done','');const blob=await resp.blob();const fname=getFilename(resp,`video_${item.id}.mp4`);bDoneFiles.push({id:item.id,blob,fname});addItemDlBtn(item.id,blob,fname)}}catch(e){clearInterval(poll);setItemStatus(item,'error','Error')}updateStats();updateOverall();await new Promise(r=>setTimeout(r,600))}bRunning=false;document.getElementById('bBtnStart').disabled=false;if(bDoneFiles.length>1)document.getElementById('bBtnZip').classList.add('show');updateOverall()}
async function batchZip(){if(bDoneFiles.length===0)return;const btn=document.getElementById('bBtnZip');btn.disabled=true;btn.innerHTML='⏳ ZIP...';try{const ids=bDoneFiles.map(f=>f.id);const resp=await fetch('/api/batch_zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_ids:ids})});if(resp.ok){const blob=await resp.blob();triggerDownload(blob,getFilename(resp,'vortexdl_batch.zip'))}else alert('ZIP gagal')}catch(e){alert('ZIP error')}finally{btn.disabled=false;btn.innerHTML='🗜 ZIP'}}
function renderQItem(item){const qList=document.getElementById('queueList');const el=document.createElement('div');el.className='q-item waiting';el.id='qi_'+item.id;const plat=item.plat||{};el.innerHTML=`<div class="q-thumb" style="background:${plat.color||'var(--dim)'}22"></div><div class="q-body"><div class="q-title" id="qt_${item.id}">${item.url.substring(0,40)}</div><div class="q-meta"><span style="color:${plat.color||'var(--muted)'}">${plat.name||'Unknown'}</span></div><div class="q-prog-mini"><div class="q-prog-fill" id="qp_${item.id}"></div></div><div id="qdl_${item.id}"></div></div><div class="q-status"><span class="status-badge sb-waiting" id="qb_${item.id}">⏸</span></div>`;qList.appendChild(el)}
function updateQItemInfo(item){const info=item.info;if(!info)return;const title=(info.title||'').substring(0,40)||item.url.substring(0,30);const el_t=document.getElementById('qt_'+item.id);if(el_t)el_t.textContent=title;if(info.thumbnail){const tp=document.getElementById('qi_'+item.id)?.querySelector('.q-thumb');if(tp){tp.style.backgroundImage=`url(${info.thumbnail})`;tp.style.backgroundSize='cover';tp.style.backgroundPosition='center'}}}
const STATUS_MAP={waiting:['waiting','sb-waiting','⏸'],fetching:['fetching','sb-fetching','🔍'],queued:['queued','sb-queued','🕐'],running:['running','sb-running','⬇'],done:['done','sb-done','✓'],error:['error','sb-error','✗']};
function setItemStatus(item,status,msg){item.status=status;const el=document.getElementById('qi_'+item.id);const badge=document.getElementById('qb_'+item.id);if(!el||!badge)return;const[cls,bcls,label]=STATUS_MAP[status]||STATUS_MAP.waiting;el.className='q-item '+cls;badge.className='status-badge '+bcls;badge.textContent=label}
function setItemProgress(id,pct){const fill=document.getElementById('qp_'+id);if(!fill)return;if(pct>=100){fill.style.width='100%'}else if(pct>0){fill.style.width=pct+'%'}}
function addItemDlBtn(id,blob,fname){const cont=document.getElementById('qdl_'+item.id);if(!cont)return;const btn=document.createElement('a');btn.className='q-dl-btn';btn.textContent='⬇ Save';btn.href=URL.createObjectURL(blob);btn.download=fname;cont.appendChild(btn)}
function updateStats(){const done=bItems.filter(i=>i.status==='done').length;const pending=bItems.filter(i=>['waiting','queued','running','fetching'].includes(i.status)).length;const err=bItems.filter(i=>i.status==='error').length;document.getElementById('statDone').textContent=done;document.getElementById('statPending').textContent=pending;document.getElementById('statErr').textContent=err}
function updateOverall(){const total=bItems.length;if(total===0)return;const done=bItems.filter(i=>['done','error'].includes(i.status)).length;const pct=Math.round(done/total*100);document.getElementById('overallFill').style.width=pct+'%';document.getElementById('overallPct').textContent=pct+'%';document.getElementById('overallStatus').textContent=pct===100?`✓ ${total} selesai`:`${done}/${total}`}}
</script>
</body>
</html>'''

# ═══════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    
    if not url:
        return jsonify({"success": False, "error": "URL kosong"})
    
    if not detect_platform(url):
        return jsonify({"success": False, "error": "Platform tidak dikenali"})
    
    cache_key = f"info_{hash(url)}"
    if cache_key in INFO_CACHE:
        return jsonify({"success": True, "info": INFO_CACHE[cache_key]})
    
    if is_ucshare(url):
        try:
            info = ucshare_extract_info(url)
            result = {
                "title": info["title"],
                "uploader": info["uploader"],
                "duration": info["duration"],
                "thumbnail": info["thumbnail"],
                "platform": "UCShare",
            }
            INFO_CACHE[cache_key] = result
            return jsonify({"success": True, "info": result})
        except Exception as e:
            return jsonify({"success": False, "error": f"UCShare: {str(e)[:100]}"})
    
    if not HAS_YT_DLP:
        return jsonify({"success": False, "error": "yt-dlp tidak tersedia"})
    
    opts = base_ydl_opts()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries") or []
        if entries:
            first = next((e for e in entries if e), info)
            thumb = pick_thumbnail(first) or pick_thumbnail(info)
            title = info.get("title") or first.get("title") or "Tanpa Judul"
            uploader = info.get("uploader") or first.get("uploader") or "Unknown"
            duration = first.get("duration")
        else:
            thumb = pick_thumbnail(info)
            title = info.get("title") or "Tanpa Judul"
            uploader = info.get("uploader") or "Unknown"
            duration = info.get("duration")

        plat = detect_platform(url)
        result = {
            "title": title,
            "uploader": uploader,
            "duration": duration,
            "thumbnail": thumb,
            "platform": plat[0] if plat else "Unknown",
        }
        INFO_CACHE[cache_key] = result
        return jsonify({"success": True, "info": result})

    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if "private" in msg:
            err = "Konten private"
        elif "removed" in msg or "deleted" in msg:
            err = "Konten dihapus"
        elif "age" in msg:
            err = "Verifikasi usia diperlukan"
        elif "unavailable" in msg:
            err = "Konten tidak tersedia"
        else:
            err = "Gagal memuat konten"
        return jsonify({"success": False, "error": err})
    except Exception as e:
        return jsonify({"success": False, "error": f"Error: {str(e)[:80]}"})

@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    fmt = data.get("format", "720p")
    session_id = data.get("session_id", str(uuid.uuid4()))
    save_zip = data.get("save_for_zip", False)
    
    if not url or not detect_platform(url):
        return jsonify({"error": "URL tidak valid"}), 400

    progress_store[session_id] = {"percent": 0, "status": "Mempersiapkan..."}

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl = d.get("downloaded_bytes", 0)
            pct = int(dl / total * 100) if total > 0 else 0
            progress_store[session_id] = {"percent": min(pct, 95), "status": "Downloading..."}
        elif d["status"] == "finished":
            progress_store[session_id] = {"percent": 98, "status": "Memproses..."}

    is_audio = fmt == "mp3"
    safe_sid = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)

    if is_ucshare(url):
        try:
            out_file = DOWNLOAD_DIR / f"{safe_sid}_ucshare.mp4"
            progress_store[session_id] = {"percent": 0, "status": "Menghubungi UCShare..."}
            info = ucshare_download(str(url), str(out_file), hook_fn=hook)

            if not out_file.exists():
                return jsonify({"error": "File tidak ditemukan"}), 500

            progress_store[session_id] = {"percent": 100, "status": "✓ Selesai"}
            title = re.sub(r'[^\w\s\-.]', '', info.get("title", "video")).strip()[:60] or "video"
            dl_name = f"{title}.mp4"

            if save_zip:
                batch_store[session_id] = {"path": str(out_file), "name": dl_name}

            with open(out_file, 'rb') as f:
                file_data = f.read()

            if session_id not in batch_store:
                try:
                    out_file.unlink(missing_ok=True)
                except:
                    pass
            
            progress_store.pop(session_id, None)

            return Response(
                file_data,
                mimetype="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{dl_name}"',
                    "Content-Length": str(len(file_data))
                }
            )

        except Exception as e:
            progress_store.pop(session_id, None)
            return jsonify({"error": f"UCShare error: {str(e)[:100]}"}), 400

    if not HAS_YT_DLP:
        progress_store.pop(session_id, None)
        return jsonify({"error": "yt-dlp tidak tersedia"}), 500

    out_tmpl = str(DOWNLOAD_DIR / f"{safe_sid}_%(title)s.%(ext)s")

    opts = base_ydl_opts(hook)
    opts["outtmpl"] = out_tmpl
    opts["format"] = get_format_selector(fmt)

    if is_audio:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            prepared = ydl.prepare_filename(info)

        ext = "mp3" if is_audio else "mp4"
        candidate = Path(prepared).with_suffix(f".{ext}")
        
        if not candidate.exists():
            matches = list(DOWNLOAD_DIR.glob(f"{safe_sid}_*.{ext}"))
            if not matches:
                matches = list(DOWNLOAD_DIR.glob(f"{safe_sid}_*"))
            if matches:
                candidate = matches[0]
            else:
                progress_store.pop(session_id, None)
                return jsonify({"error": "File tidak ditemukan"}), 500

        progress_store[session_id] = {"percent": 100, "status": "✓ Selesai"}
        title = safe_fname(info)
        dl_name = f"{title}.{ext}"
        mime = "audio/mpeg" if is_audio else "video/mp4"

        if save_zip:
            batch_store[session_id] = {"path": str(candidate), "name": dl_name}

        with open(candidate, 'rb') as f:
            file_data = f.read()

        if session_id not in batch_store:
            try:
                candidate.unlink(missing_ok=True)
            except:
                pass
        
        progress_store.pop(session_id, None)

        return Response(
            file_data,
            mimetype=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{dl_name}"',
                "Content-Length": str(len(file_data))
            }
        )

    except yt_dlp.utils.DownloadError as e:
        progress_store.pop(session_id, None)
        return jsonify({"error": "Download gagal"}), 400
    except Exception as e:
        progress_store.pop(session_id, None)
        return jsonify({"error": f"Error: {str(e)[:80]}"}), 500

@app.route("/api/progress/<session_id>")
def api_progress(session_id):
    return jsonify(progress_store.get(session_id, {"percent": 0, "status": "..."}))

@app.route("/api/batch_zip", methods=["POST"])
def api_batch_zip():
    data = request.get_json() or {}
    file_ids = data.get("file_ids", [])
    
    files = []
    for fid in file_ids:
        entry = batch_store.get(fid)
        if entry and Path(entry["path"]).exists():
            files.append(entry)

    if not files:
        return jsonify({"error": "Tidak ada file untuk ZIP"}), 400

    zip_id = str(uuid.uuid4())[:8]
    zip_path = DOWNLOAD_DIR / f"vortexdl_batch_{zip_id}.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in files:
                zf.write(entry["path"], entry["name"])

        with open(zip_path, 'rb') as f:
            zip_data = f.read()

        try:
            zip_path.unlink(missing_ok=True)
            for entry in files:
                try:
                    Path(entry["path"]).unlink(missing_ok=True)
                except:
                    pass
                keys_to_remove = [k for k, v in batch_store.items() if v == entry]
                for k in keys_to_remove:
                    batch_store.pop(k, None)
        except:
            pass

        return Response(
            zip_data,
            mimetype="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="VortexDL_Batch_{zip_id}.zip"',
                "Content-Length": str(len(zip_data))
            }
        )

    except Exception as e:
        return jsonify({"error": f"ZIP error: {str(e)[:80]}"}), 500

# ═══════════════════════════════════════════════════════════════════
# VERCEL SERVERLESS ENTRY POINT (WAJIB!)
# ═══════════════════════════════════════════════════════════════════
application = app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
