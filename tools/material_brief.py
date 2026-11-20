"""Preview a folder of local evidence in one call before asking the manager."""
import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory, mkdtemp

from ingest import extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--audio-model", help="локальная модель Whisper для речи")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    media_notes = []
    for path in sorted(args.folder.iterdir()):
        if not path.is_file() or path.is_symlink() or path.name.startswith("."):
            continue
        print(f"\n[{path.name}]")
        ext = path.suffix.lower()
        try:
            if ext in {".md", ".txt", ".pdf", ".docx", ".xlsx", ".csv", ".tsv"}:
                body, warnings = extract(path)
                print(body[:6000])
                if len(body) > 6000:
                    print("Показано начало; для остальных данных откройте исходник.")
                for warning in warnings:
                    print(warning)
            elif ext in {".wav", ".mp3", ".m4a", ".flac"} and args.audio_model:
                with TemporaryDirectory() as tmp:
                    out = Path(tmp) / "transcript"
                    cmd = [sys.executable, str(Path(__file__).with_name("strateg.py")), "media",
                           "--input", str(path), "--output", str(out), "--model", args.audio_model]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
                    transcript = (out / "transcript.md").read_text(encoding="utf-8")
                    media_notes.append(f"{path.name}\n{transcript[:6000]}")
                    if len(transcript) > 6000:
                        print("Показано начало расшифровки; проверьте полную запись.")
            elif ext in {".mov", ".mp4", ".mkv", ".webm"}:
                import av
                import imageio_ffmpeg
                with av.open(str(path)) as video:
                    stream = video.streams.video[0]
                    duration = (float(stream.duration * stream.time_base) if stream.duration
                                else float(video.duration or 0) / 1000000)
                if duration <= 0:
                    raise ValueError("Не определена длительность видео")
                sheet = Path(mkdtemp(prefix="strateg-frames-")) / "frames.jpg"
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-loglevel", "error",
                                "-i", str(path), "-vf", f"fps=9/{duration},scale=480:-2,tile=3x3",
                                "-frames:v", "1", str(sheet)], check=True, timeout=60)
                if not sheet.is_file():
                    raise ValueError("Лист кадров не создан")
                media_notes.append(f"Просмотрите {sheet} — кадры {path.name} по времени слева направо.")
            else:
                print("Откройте оригинал; для видео извлеките кадры командой media --frames-only.")
        except (ImportError, IndexError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Извлечь не удалось: {exc}")
    if media_notes:
        print("\n".join(media_notes))


if __name__ == "__main__":
    main()
