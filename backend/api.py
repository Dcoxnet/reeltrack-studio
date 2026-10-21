"""Local-only API for ReelTrack Studio. No user cookies or media leave the computer."""
from __future__ import annotations

import asyncio
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "engine"
SCRIPT = ENGINE / "main.py"
REELS = ENGINE / "reels.txt"
RESULTS = ENGINE / "results.csv"
SONGS = ENGINE / "songs.csv"
NAMES = ENGINE / "song_names.txt"
AUDIO = ENGINE / "full_mp3"
LINK_RE = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)", re.I)

app = FastAPI(title="ReelTrack Studio", version="0.1.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

class LinksBody(BaseModel):
    text: str = Field(max_length=100000)

class RunBody(BaseModel):
    mode: str = "identify"
    browser: str = "zen"
    limit: int | None = Field(default=None, ge=1, le=500)

class TrackEdit(BaseModel):
    artist: str = Field(min_length=1, max_length=180)
    song: str = Field(min_length=1, max_length=180)

proc: asyncio.subprocess.Process | None = None
logs: list[str] = []
job_mode: str | None = None
started_at: str | None = None
last_exit_code: int | None = None
current_index: int = 0
running: bool = False
lock = asyncio.Lock()


def read_links() -> list[str]:
    return [x.strip() for x in REELS.read_text(encoding="utf-8").splitlines() if x.strip()] if REELS.exists() else []


def read_records() -> list[dict]:
    if not RESULTS.exists():
        return [{"n": i, "reel": url, "status": "", "artist": "", "song": ""}
                for i, url in enumerate(read_links(), 1)]
    with RESULTS.open("r", encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    records_by_reel = {r.get("reel"): r for r in records}
    return [{**records_by_reel.get(url, {}), "n": i, "reel": url}
            for i, url in enumerate(read_links(), 1)]


def count_status(records: list[dict]) -> dict:
    return {
        "total": len(records),
        "recognized": sum(bool((r.get("song") or "").strip() and (r.get("artist") or "").strip()) for r in records),
        "downloaded": sum(r.get("status") == "DOWNLOADED" for r in records),
        "manual": sum(r.get("status") == "CHECK_MANUALLY" for r in records),
        "unrecognized": sum(r.get("status") == "NOT_RECOGNIZED" for r in records),
        "errors": sum(r.get("status") == "ERROR" for r in records),
    }


def player_link(record: dict) -> str | None:
    mp3 = record.get("mp3") or ""
    if not mp3:
        return None
    p = (ENGINE / mp3).resolve()
    if p.suffix.lower() != ".mp3" or not p.is_relative_to(AUDIO.resolve()) or not p.is_file():
        return None
    return f"/api/audio/{record['n']}"


def snapshot() -> dict:
    records = read_records()
    tracks = []
    for row in records:
        tracks.append({
            "n": int(row["n"]), "reel": row.get("reel", ""), "status": row.get("status", ""),
            "artist": row.get("artist", ""), "song": row.get("song", ""),
            "youtube": row.get("youtube", ""), "alternatives": row.get("alternatives", ""),
            "score": row.get("score", ""), "error": row.get("error", ""),
            "audio": player_link(row),
        })
    return {
        "tracks": tracks,
        "counts": count_status(records),
        "job": {"running": running, "mode": job_mode, "started_at": started_at,
                "exit_code": last_exit_code, "current_index": current_index, "logs": logs[-120:]},
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def state():
    return snapshot()


@app.post("/api/reels")
async def save_reels(payload: LinksBody):
    if running:
        raise HTTPException(status_code=409, detail="Останови обработку перед изменением списка")
    found: list[str] = []
    for line in payload.text.splitlines():
        if not line.strip():
            continue
        m = LINK_RE.search(line)
        if not m:
            raise HTTPException(422, detail=f"Не Instagram Reel: {line[:90]}")
        url = f"https://www.instagram.com/reel/{m.group(1)}/"
        if url not in found:
            found.append(url)
    if not found:
        raise HTTPException(422, detail="Вставь хотя бы одну ссылку на Instagram Reel")
    if len(found) > 500:
        raise HTTPException(422, detail="Максимум 500 ссылок за один список")
    ENGINE.mkdir(parents=True, exist_ok=True)
    REELS.write_text("\n".join(found) + "\n", encoding="utf-8")
    return {"count": len(found), "data": snapshot()}


async def collect_output(process: asyncio.subprocess.Process):
    global current_index, running, last_exit_code
    assert process.stdout
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        message = line.decode("utf-8", errors="replace").rstrip()
        if message:
            logs.append(message)
            if len(logs) > 500:
                del logs[:len(logs) - 500]
            match = re.search(r"\[(\d+)/(\d+)\]", message)
            if match:
                current_index = int(match.group(1))
    code = await process.wait()
    last_exit_code = code
    running = False
    logs.append(f"Задача завершена: код {code}")


@app.post("/api/run")
async def run(body: RunBody):
    global proc, running, last_exit_code, job_mode, started_at, current_index
    if body.mode not in {"identify", "search", "download"}:
        raise HTTPException(422, detail="Некорректный режим")
    if body.browser not in {"none", "zen", "firefox", "chrome", "safari", "edge", "brave"}:
        raise HTTPException(422, detail="Некорректный браузер")
    async with lock:
        if running:
            raise HTTPException(409, detail="Задача уже выполняется")
        if not read_links():
            raise HTTPException(422, detail="Сначала добавь ссылки")
        if not SCRIPT.exists():
            raise HTTPException(500, detail="Не найден Python-движок")
        args = [sys.executable, "-u", str(SCRIPT)]
        if body.mode == "identify": args.append("--identify-only")
        if body.mode == "search": args.append("--search-only")
        if body.limit: args += ["--limit", str(body.limit)]
        if body.browser != "none":
            args += ["--cookies-browser", body.browser, "--youtube-cookies-browser", body.browser]
        logs.clear()
        current_index = 0
        last_exit_code = None
        job_mode = body.mode
        started_at = datetime.now(timezone.utc).isoformat()
        proc = await asyncio.create_subprocess_exec(*args, cwd=ENGINE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        running = True
        asyncio.create_task(collect_output(proc))
    return {"started": True, "data": snapshot()}


@app.post("/api/stop")
async def stop():
    if proc is not None and running and proc.returncode is None:
        proc.terminate()
        logs.append("Получен запрос на остановку")
        return {"stopping": True}
    return {"stopping": False}


@app.patch("/api/tracks/{number}")
async def edit_track(number: int, body: TrackEdit):
    if running:
        raise HTTPException(409, detail="Редактировать можно после остановки задачи")
    links = read_links()
    if number < 1 or number > len(links):
        raise HTTPException(404, detail="Reel не найден")
    old_rows: dict[str, dict] = {}
    fieldnames = ["n", "reel", "status", "artist", "song", "youtube", "mp3", "score", "alternatives", "error"]
    if RESULTS.exists():
        with RESULTS.open("r", encoding="utf-8-sig", newline="") as f:
            old_rows = {r["reel"]: r for r in csv.DictReader(f) if r.get("reel")}
    reel = links[number - 1]
    row = {**old_rows.get(reel, {}), "n": str(number), "reel": reel,
           "status": "IDENTIFIED", "artist": body.artist.strip(), "song": body.song.strip(),
           "youtube": "", "mp3": "", "score": "", "alternatives": "", "error": ""}
    old_rows[reel] = row
    with RESULTS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, url in enumerate(links, 1):
            writer.writerow({**old_rows.get(url, {}), "n": i, "reel": url})
    # Rebuild exports with exactly the same logic as the engine.
    sys.path.insert(0, str(ENGINE))
    from main import write_song_lists
    write_song_lists(ENGINE, links, old_rows)
    return snapshot()


@app.get("/api/audio/{number}")
def get_audio(number: int):
    tracks = read_records()
    if number < 1 or number > len(tracks):
        raise HTTPException(404, detail="Файл не найден")
    record = tracks[number - 1]
    if not player_link(record):
        raise HTTPException(404, detail="MP3 не найден")
    path = ENGINE / record["mp3"]
    return FileResponse(path, media_type="audio/mpeg", filename=path.name,
                        content_disposition_type="inline")


@app.get("/api/export/{kind}")
def export(kind: str):
    allowed = {"names": (NAMES, "text/plain"), "songs": (SONGS, "text/csv"),
               "results": (RESULTS, "text/csv")}
    if kind not in allowed:
        raise HTTPException(404, detail="Неизвестный экспорт")
    path, mime = allowed[kind]
    if not path.exists():
        raise HTTPException(404, detail="Запусти распознавание для создания отчёта")
    return FileResponse(path, media_type=mime, filename=path.name)
