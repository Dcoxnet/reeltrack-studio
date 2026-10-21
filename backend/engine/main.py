#!/usr/bin/env python3
"""Instagram Reels -> названия песен и опционально полные MP3.

Сохраняет все 46 ссылок в songs.csv и song_names.txt, даже когда
распознавание не удалось. Работает только с медиа, доступными для загрузки.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote_plus

from shazamio import Shazam
from yt_dlp import YoutubeDL


BASE = Path(__file__).resolve().parent
COLUMNS = [
    "n", "reel", "status", "artist", "song", "youtube", "mp3", "score", "alternatives", "error"
]
BAD_TAGS = [
    "cover", "karaoke", "nightcore", "sped up", "slowed", "8d audio", "instrumental",
    "reverb", "remix", "live", "reaction", "tutorial", "loop", "1 hour", "60 minutes",
    "tiktok edit", "shorts", "fanmade", "fan made", "edit audio",
]
NOISE = {"official", "audio", "video", "hd", "hq", "lyrics", "lyric", "feat", "ft", "music", "remastered"}


@dataclass
class Track:
    artist: str
    song: str


@dataclass
class Candidate:
    url: str
    title: str
    channel: str
    duration: float | None
    score: float


def normal(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text, re.UNICODE))


def words(text: str) -> set[str]:
    return {x for x in normal(text).split() if x not in NOISE}


def safe_filename(text: str, limit: int = 145) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:limit].rstrip(" .") or "track")


def read_links(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл со ссылками: {path}")
    seen: set[str] = set()
    links: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.search(r"instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)", line)
        if not match:
            print(f"⚠ Пропускаю неподходящую ссылку: {line}")
            continue
        url = f"https://www.instagram.com/reel/{match.group(1)}/"
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def read_csv(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return {row["reel"]: row for row in csv.DictReader(f) if row.get("reel")}


def write_csv(path: Path, links: list[str], results: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for i, url in enumerate(links, 1):
            writer.writerow({"n": i, "reel": url, **results.get(url, {})})
    temp.replace(path)


def write_song_lists(base: Path, links: list[str], results: dict[str, dict[str, str]]) -> None:
    """Экспорт удобного списка. Строка на КАЖДЫЙ Reel с самого начала запуска."""
    columns = ["n", "artist", "song", "status", "instagram", "youtube_search", "youtube", "alternatives", "mp3", "error"]
    status_ru = {
        "DOWNLOADED": "Скачано", "IDENTIFIED": "Распознано", "FOUND_FULL_TRACK": "Найдена полная версия",
        "CHECK_MANUALLY": "Проверить вручную", "NOT_RECOGNIZED": "Не распознано",
        "ERROR": "Ошибка", "STARTED": "Обрабатывается", "": "В очереди",
    }
    csv_path = base / "songs.csv"
    temp_csv = csv_path.with_suffix(".csv.tmp")
    temp_txt = (base / "song_names.txt.tmp")
    with temp_csv.open("w", newline="", encoding="utf-8-sig") as file, temp_txt.open("w", encoding="utf-8") as text_file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for i, reel in enumerate(links, 1):
            row = results.get(reel) or {}
            artist = (row.get("artist") or "").strip()
            song = (row.get("song") or "").strip()
            status = row.get("status") or ""
            writer.writerow({
                "n": i, "artist": artist, "song": song, "status": status_ru.get(status, status),
                "instagram": reel,
                "youtube_search": f"https://www.youtube.com/results?search_query={quote_plus(artist + ' ' + song)}" if artist and song else "",
                "youtube": row.get("youtube") or "",
                "alternatives": row.get("alternatives") or "",
                "mp3": row.get("mp3") or "", "error": row.get("error") or "",
            })
            if artist and song:
                text_file.write(f"{i:02d}. {artist} — {song}\n")
            else:
                placeholder = status_ru.get(status, status)
                text_file.write(f"{i:02d}. [{placeholder.upper()}] {reel}\n")
    temp_csv.replace(csv_path)
    temp_txt.replace(base / "song_names.txt")


def ffprobe_duration(path: Path) -> float | None:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True, check=False
    )
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def make_sample(audio: Path, output: Path, start: float) -> None:
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(audio),
         "-t", "11.7", "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(output)],
        capture_output=True, text=True
    )
    if p.returncode != 0 or not output.exists() or output.stat().st_size < 30000:
        raise RuntimeError(f"Не удалось получить образец: {p.stderr.strip()[-250:]}")


def yt_opts(browser: str | None, **kwargs) -> dict:
    opt = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 25,
    }
    if browser:
        if browser == "zen" or browser.startswith("zen:"):
            # Zen uses Firefox's cookies.sqlite, but in a separate profile folder.
            if browser.startswith("zen:"):
                profile = Path(browser[4:]).expanduser()
                if not (profile / "cookies.sqlite").is_file():
                    raise RuntimeError(f"Zen profile has no cookies.sqlite: {profile}")
            else:
                roots = [Path.home() / ".zen", Path.home() / ".config" / "zen" / "Profiles"]
                if sys.platform == "darwin":
                    roots += [
                        Path.home() / "Library" / "Application Support" / "zen" / "Profiles",
                        Path.home() / "Library" / "Application Support" / "Zen" / "Profiles",
                    ]
                elif sys.platform == "win32" and os.environ.get("APPDATA"):
                    roots.append(Path(os.environ["APPDATA"]) / "zen" / "Profiles")
                profiles = [
                    directory for root in roots if root.is_dir()
                    for directory in root.iterdir()
                    if directory.is_dir() and (directory / "cookies.sqlite").is_file()
                ]
                if not profiles:
                    raise RuntimeError(
                        "Профиль Zen не найден. Открой about:support в Zen и проверь «Папка профиля»."
                    )
                # Most recently updated cookie DB is usually the active profile.
                profile = max(profiles, key=lambda p: (p / "cookies.sqlite").stat().st_mtime)
            opt["cookiesfrombrowser"] = ("firefox", str(profile))
        else:
            opt["cookiesfrombrowser"] = (browser,)
    opt.update(kwargs)
    return opt


def download_reel(url: str, n: int, cache: Path, browser: str | None) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    existing = list(cache.glob("reel.mp3"))
    if existing:
        return existing[0]
    opt = yt_opts(
        browser,
        format="bestaudio/best",
        outtmpl=str(cache / "reel.%(ext)s"),
        postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    )
    with YoutubeDL(opt) as ydl:
        ydl.extract_info(url, download=True)
    result = cache / "reel.mp3"
    if not result.exists():
        raise RuntimeError("Instagram не отдал аудио. Проверь ссылку и вход в аккаунт.")
    return result


async def recognize(shazam: Shazam, audio: Path, sample_dir: Path) -> Track | None:
    duration = ffprobe_duration(audio)
    # Несколько отрезков: музыка может начаться не с первой секунды.
    positions = [2.0, 0.0, 13.0, 27.0]
    checked = set()
    recognized: list[Track] = []
    for pos in positions:
        if duration is not None and duration < pos + 6:
            continue
        if pos in checked:
            continue
        checked.add(pos)
        sample = sample_dir / f"sample_{int(pos)}.wav"
        try:
            make_sample(audio, sample, pos)
            result = await shazam.recognize(str(sample))
            track = (result or {}).get("track") or {}
            song = (track.get("title") or "").strip()
            artist = (track.get("subtitle") or "").strip()
            if song and artist:
                found = Track(artist=artist, song=song)
                recognized.append(found)
                # Прекращаем только после 2 согласующихся распознаваний.
                if len(recognized) >= 2 and normal(recognized[-1].artist + recognized[-1].song) == normal(recognized[-2].artist + recognized[-2].song):
                    return found
        except Exception as exc:
            print(f"    Shazam на {pos:.0f} сек.: {type(exc).__name__}: {str(exc)[:100]}")
        finally:
            sample.unlink(missing_ok=True)
    if not recognized:
        return None
    names = {(normal(t.artist), normal(t.song)) for t in recognized}
    if len(names) > 1:
        raise RuntimeError("Shazam обнаружил разные песни в одном Reel — требуется проверка вручную")
    return recognized[0]


def score_candidate(track: Track, entry: dict) -> Candidate | None:
    title = str(entry.get("title") or "")
    channel = str(entry.get("channel") or entry.get("uploader") or "")
    duration = entry.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    video_id = entry.get("id") or ""
    url = entry.get("webpage_url") or entry.get("url") or ""
    if isinstance(url, str) and not url.startswith("http") and video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
    if not url:
        return None
    if duration is not None and (duration < 85 or duration > 900):
        return None
    title_norm = normal(title)
    song_norm = normal(track.song)
    artist_norm = normal(track.artist)
    search_words = words(track.song)
    found_words = words(title)
    coverage = len(search_words & found_words) / max(1, len(search_words))
    ratio = SequenceMatcher(None, song_norm, title_norm).ratio()
    song_exact = bool(song_norm and song_norm in title_norm)
    artist_in_title = artist_norm in title_norm if artist_norm else False
    artist_in_channel = artist_norm in normal(channel) if artist_norm else False
    # artist may be "A & B"; one of them appearing is a weak positive.
    artist_parts = words(track.artist)
    partial_artist = bool(artist_parts and (artist_parts & (words(channel) | words(title))))
    score = coverage * 0.43 + (0.20 if song_exact else ratio * 0.12)
    score += (0.21 if artist_in_title else 0) + (0.20 if artist_in_channel else 0)
    score += 0.08 if partial_artist and not (artist_in_title or artist_in_channel) else 0
    if "official audio" in title_norm or "provided to youtube" in normal(channel):
        score += 0.08
    if "topic" in normal(channel) or "vevo" in normal(channel):
        score += 0.06
    for unwanted in BAD_TAGS:
        if unwanted in title_norm and unwanted not in song_norm:
            score -= 0.27
    if duration is None:
        score -= 0.03  # не подтверждена полноразмерность
    if not (artist_in_title or artist_in_channel or partial_artist):
        score -= 0.22
    return Candidate(url=url, title=title, channel=channel, duration=duration, score=round(score, 3))


def youtube_candidates(track: Track) -> list[Candidate]:
    queries = [
        f"ytsearch12:{track.artist} {track.song} official audio",
        f"ytsearch8:{track.artist} {track.song}",
    ]
    entries: list[dict] = []
    for query in queries:
        try:
            with YoutubeDL(yt_opts(None, extract_flat="in_playlist", skip_download=True, ignoreerrors=True)) as ydl:
                result = ydl.extract_info(query, download=False) or {}
                entries.extend([x for x in (result.get("entries") or []) if x])
        except Exception as exc:
            print(f"    Ошибка поиска YouTube: {str(exc)[:170]}")
    candidates: dict[str, Candidate] = {}
    for entry in entries:
        candidate = score_candidate(track, entry)
        if candidate and (candidate.url not in candidates or candidate.score > candidates[candidate.url].score):
            candidates[candidate.url] = candidate
    return sorted(candidates.values(), key=lambda c: c.score, reverse=True)


def get_full_mp3(candidate: Candidate, target: Path, browser: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # ID помогает избежать затрагивания уже существующих файлов.
    temp_template = str(target.parent / (target.stem + ".dl.%(ext)s"))
    try:
        options = yt_opts(
            browser,
            format="bestaudio/best",
            outtmpl=temp_template,
            postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            overwrites=True,
        )
        with YoutubeDL(options) as ydl:
            ydl.extract_info(candidate.url, download=True)
        downloaded = target.parent / (target.stem + ".dl.mp3")
        if not downloaded.exists():
            raise RuntimeError("YouTube не отдал MP3 после конвертации")
        actual_duration = ffprobe_duration(downloaded)
        if actual_duration is not None and actual_duration < 85:
            downloaded.unlink(missing_ok=True)
            raise RuntimeError(f"Загруженная запись всего {actual_duration:.0f} сек — это не полная песня")
        downloaded.replace(target)
    finally:
        for file in target.parent.glob(target.stem + ".dl.*"):
            file.unlink(missing_ok=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram Reels → распознать песни → найти и скачать ПОЛНЫЕ MP3")
    parser.add_argument("--reels", default="reels.txt", help="Файл со ссылками, по одной на строку")
    parser.add_argument("--cookies-browser", choices=["safari", "chrome", "firefox", "edge", "brave", "zen"],
                        help="Браузер, где открыт Instagram (нужно, если Instagram ограничил доступ)")
    parser.add_argument("--youtube-cookies-browser", choices=["safari", "chrome", "firefox", "edge", "brave", "zen"],
                        help="Браузер с доступом к YouTube при необходимости")
    parser.add_argument("--zen-profile", help="Необязательно: полный путь к профилю Zen из about:support")
    parser.add_argument("--keep-reel-audio", action="store_true", help="Оставлять временные фрагменты аудио")
    parser.add_argument("--search-only", action="store_true", help="Не скачивать полные треки, только распознать и найти")
    parser.add_argument("--identify-only", action="store_true", help="Быстро распознать имена песен, не искать и не скачивать полные записи")
    parser.add_argument("--force", action="store_true", help="Повторно обработать все Reels")
    parser.add_argument("--limit", type=int, help="Обработать только первые N ссылок для проверки")
    args = parser.parse_args()
    if args.zen_profile:
        for key in ("cookies_browser", "youtube_cookies_browser"):
            if getattr(args, key) == "zen":
                setattr(args, key, "zen:" + args.zen_profile)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        install_hint = (
            "Установи FFmpeg и добавь папку bin в PATH."
            if sys.platform == "win32" else
            "Установи пакет ffmpeg через пакетный менеджер (например, sudo pacman -S ffmpeg на CachyOS)."
            if sys.platform.startswith("linux") else
            "Установи FFmpeg: brew install ffmpeg"
        )
        sys.exit(install_hint)
    reels = Path(args.reels)
    if not reels.is_absolute():
        reels = BASE / reels
    all_links = read_links(reels)
    links = all_links[:max(0, args.limit)] if args.limit is not None else all_links
    if not links:
        sys.exit("В reels.txt нет Instagram-ссылок")
    # Здесь всегда используются ВСЕ ссылки, даже при --limit N:
    # отчёт сразу показывает 46 строк и не теряет результаты прошлых запусков.
    full_dir = BASE / "full_mp3"
    temp_dir = BASE / "cache"
    report_path = BASE / "results.csv"
    full_dir.mkdir(exist_ok=True)
    temp_dir.mkdir(exist_ok=True)
    results = read_csv(report_path)
    write_csv(report_path, all_links, results)
    write_song_lists(BASE, all_links, results)
    print(f"Всего Reels для обработки: {len(links)} (в списке: {len(all_links)}). Полные MP3: {full_dir}")
    print(f"Список песен: {BASE / 'song_names.txt'}")
    print(f"Таблица с ссылками: {BASE / 'songs.csv'}\n")
    try:
        # Shazam 0.8.x не является async context manager (нет __aenter__).
        shazam = Shazam()
        for n, reel in enumerate(links, 1):
            old = results.get(reel) or {}
            if not args.force and old.get("status") == "DOWNLOADED" and old.get("mp3") and (BASE / old["mp3"]).exists():
                print(f"[{n}/{len(links)}] Уже скачано: {old.get('artist')} — {old.get('song')}")
                continue
            if args.identify_only and not args.force and old.get("artist") and old.get("song"):
                print(f"[{n}/{len(links)}] Уже распознано: {old['artist']} — {old['song']}")
                continue
            print(f"[{n}/{len(links)}] {reel}", flush=True)
            data = {
                "status": "STARTED", "artist": "", "song": "", "youtube": "",
                "mp3": "", "score": "", "alternatives": "", "error": "",
            }
            individual_cache = temp_dir / f"{n:03d}"
            try:
                if not args.force and old.get("artist") and old.get("song"):
                    track = Track(artist=old["artist"], song=old["song"])
                    print(f"  Использую ранее распознанную песню: {track.artist} — {track.song}")
                else:
                    print("  1/3 Получаю фрагмент из Instagram...", flush=True)
                    audio = download_reel(reel, n, individual_cache, args.cookies_browser)
                    print("  2/3 Определяю песню с помощью Shazam...", flush=True)
                    track = await recognize(shazam, audio, individual_cache)
                if track is None:
                    data["status"] = "NOT_RECOGNIZED"
                    data["error"] = "Shazam не распознал музыку; возможно, это оригинальный звук или речь"
                else:
                    data.update(artist=track.artist, song=track.song)
                    print(f"      {track.artist} — {track.song}")
                    # Зафиксировать название немедленно, ДО поиска YouTube и скачивания.
                    data["status"] = "IDENTIFIED"
                    results[reel] = data.copy()
                    write_csv(report_path, all_links, results)
                    write_song_lists(BASE, all_links, results)
                    if args.identify_only:
                        print("  Название сохранено в song_names.txt и songs.csv")
                    else:
                        print("  3/3 Ищу ПОЛНУЮ версию...", flush=True)
                        candidates = youtube_candidates(track)
                        data["alternatives"] = " | ".join(
                            f"{c.score:.2f} {c.title} ({c.url})" for c in candidates[:3]
                        )
                        if not candidates or candidates[0].score < 0.73:
                            data["status"] = "CHECK_MANUALLY"
                            data["error"] = "Нет достаточно уверенного совпадения среди полных записей"
                        else:
                            best = candidates[0]
                            if len(candidates) > 1 and best.score < 0.94 and candidates[1].score >= best.score - 0.02 and best.title != candidates[1].title:
                                data["status"] = "CHECK_MANUALLY"
                                data["error"] = "Слишком похожие кандидаты, требуется ручная проверка"
                            else:
                                data.update(youtube=best.url, score=f"{best.score:.3f}")
                                if args.search_only:
                                    data["status"] = "FOUND_FULL_TRACK"
                                else:
                                    out_name = safe_filename(f"{track.artist} - {track.song}") + ".mp3"
                                    full_track_path = full_dir / out_name
                                    if not full_track_path.exists() or args.force:
                                        print(f"      Загружаю: {best.title} [{best.duration or '?'} сек]", flush=True)
                                        get_full_mp3(best, full_track_path, args.youtube_cookies_browser)
                                    data.update(status="DOWNLOADED", mp3=str(full_track_path.relative_to(BASE)))
            except Exception as exc:
                # Если удалось распознать песню, НЕ теряем её название из-за ошибки YouTube.
                data["status"] = "ERROR"
                data["error"] = f"{type(exc).__name__}: {str(exc)[:350]}"
                print(f"      ⚠ Ошибка: {data['error']}")
            finally:
                if not args.keep_reel_audio:
                    shutil.rmtree(individual_cache, ignore_errors=True)
                results[reel] = data
                write_csv(report_path, all_links, results)
                write_song_lists(BASE, all_links, results)
                print(f"      → {data['status']}\n", flush=True)
    except KeyboardInterrupt:
        print("\nОстановлено. Названия и ссылки уже сохранены. Запусти снова.")
        return
    print(f"Готово! Полный отчёт: {report_path}")
    print(f"Названия: {BASE / 'song_names.txt'}")
    print(f"Таблица: {BASE / 'songs.csv'}")
    print(f"Распознано: {sum(bool((results.get(url) or {}).get('song')) for url in all_links)} из {len(all_links)}")
    print(f"Полные MP3: {sum((results.get(url) or {}).get('status') == 'DOWNLOADED' for url in all_links)} из {len(all_links)}")
    print("Нераспознанные и сомнительные треки ищи в songs.csv по статусу.")


if __name__ == "__main__":
    asyncio.run(main())
