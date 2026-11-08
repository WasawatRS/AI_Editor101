import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import set_key

import config
from engines import capcut_engine, video_engine
from services import elevenlabs_service, gemini_service, product_service, subtitle_service

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SETTINGS_PATH = Path(config.OUTPUT_DIR) / "ui_settings.json"
ENV_PATH = Path(config.BASE_DIR) / ".env"
DEFAULT_SETTINGS = {
    "voice_id": "",
    "capcut_draft_dir": "",
    "subtitle_color": "#FF2E61",
    "font_size": 72,
    "subtitle_y": 420,
    "padding": 1.0,
}


def list_input_videos() -> list[Path]:
    input_dir = Path(config.INPUT_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    return sorted(
        (path for path in input_dir.iterdir()
         if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda path: path.name.lower(),
    )


def save_uploaded_videos(uploaded_files: list) -> list[Path]:
    saved = []
    input_dir = Path(config.INPUT_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    for uploaded in uploaded_files:
        filename = Path(uploaded.name).name
        destination = input_dir / filename
        if destination.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"ไฟล์ {filename} ไม่ใช่วิดีโอที่รองรับ")
        destination = _available_path(destination)
        destination.write_bytes(uploaded.getvalue())
        saved.append(destination)
    return saved


def load_ui_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    settings["voice_id"] = config.ELEVENLABS_VOICE_ID
    try:
        settings["capcut_draft_dir"] = capcut_engine.find_capcut_draft_dir()
    except FileNotFoundError:
        pass
    if SETTINGS_PATH.is_file():
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    settings[key] = saved[key]
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_ui_settings(settings: dict) -> None:
    clean = {}
    for key in DEFAULT_SETTINGS:
        if key in settings:
            clean[key] = settings[key]
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(clean.get("subtitle_color", ""))):
        raise ValueError("สีซับต้องเป็น #RRGGBB")
    clean["font_size"] = int(clean["font_size"])
    clean["subtitle_y"] = int(clean["subtitle_y"])
    clean["padding"] = float(clean["padding"])
    
    if not 55 <= clean["font_size"] <= 85:
        raise ValueError("ขนาดฟอนต์ต้องอยู่ระหว่าง 55-85 px")
    if not 350 <= clean["subtitle_y"] <= 500:
        raise ValueError("ตำแหน่ง Y ต้องอยู่ระหว่าง 350-500 px")
    if not 0 <= clean["padding"] <= 3:
        raise ValueError("Padding ต้องอยู่ระหว่าง 0-3 วินาที")
    capcut_dir = str(clean.get("capcut_draft_dir", "")).strip()
    if capcut_dir and not Path(capcut_dir).is_dir():
        raise ValueError("พาธ CapCut Drafts ไม่มีอยู่จริง")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def save_api_credentials(gemini_api_key: str = "", elevenlabs_api_key: str = "",
                         env_path: str | None = None) -> list:
    candidates = {
        "GEMINI_API_KEY": str(gemini_api_key or "").strip(),
        "ELEVENLABS_API_KEY": str(elevenlabs_api_key or "").strip(),
    }
    updates = {name: value for name, value in candidates.items() if value}
    if not updates:
        raise ValueError("กรอก API Key อย่างน้อยหนึ่งรายการ")
    for value in updates.values():
        if any(character.isspace() for character in value):
            raise ValueError("API Key ต้องไม่มีช่องว่างหรือขึ้นบรรทัดใหม่")

    destination = Path(env_path) if env_path else ENV_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    for name, value in updates.items():
        set_key(str(destination), name, value, quote_mode="always")
        os.environ[name] = value
        setattr(config, name, value)
    return list(updates)


def process_video(video_path: str, product_name: str, settings: dict,
                  product_link: str = "", reuse_run_dir: str | None = None,
                  progress=None) -> dict:
    video = Path(video_path).resolve()
    if not video.is_file():
        raise FileNotFoundError(f"ไม่พบวิดีโอต้นฉบับ: {video}")
    product_name = product_name.strip() or video.stem
    product_link = product_service.validate_product_link(product_link)
    capcut_dir = str(settings.get("capcut_draft_dir", "")).strip()
    capcut_dir = capcut_dir or capcut_engine.find_capcut_draft_dir()
    if not Path(capcut_dir).is_dir():
        raise FileNotFoundError("พาธ CapCut Drafts ไม่ถูกต้อง")
    if not reuse_run_dir:
        config.validate_config()

    run_dir = _new_run_dir(product_name)
    run_id = run_dir.name
    _notify(progress, "script", f"กำลังวิเคราะห์วิดีโอและเขียนสคริปต์ {product_name}")

    caption = ""
    hashtags = []
    social_caption = ""
    if reuse_run_dir:
        source_dir = Path(reuse_run_dir).resolve()
        source_audio = source_dir / "voice_full.mp3"
        source_alignment = Path(str(source_audio) + ".align.json")
        if not source_audio.is_file() or not source_alignment.is_file():
            raise FileNotFoundError("งานต้นฉบับไม่มีเสียงหรือ alignment สำหรับใช้ซ้ำ")
        audio_path = run_dir / "voice_full.mp3"
        shutil.copy2(source_audio, audio_path)
        alignment = json.loads(source_alignment.read_text(encoding="utf-8"))
        voice = {"audio_path": str(audio_path), "alignment": alignment}
        source_script = source_dir / "script.json"
        if source_script.is_file():
            shutil.copy2(source_script, run_dir / "script.json")
        caption, hashtags, social_caption = _caption_from_run(source_dir)
        _notify(progress, "voice", "ใช้เสียงและ alignment จากงานเดิม ไม่เรียก API")
    else:
        script = gemini_service.generate_sales_script(str(video), product_name)
        (run_dir / "script.json").write_text(
            json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        caption = script.get("caption", product_name)
        hashtags = script.get("hashtags", [])
        social_caption = script.get("social_caption", "")
        _notify(progress, "voice", f"กำลังสร้างเสียงพากย์ ElevenLabs ({product_name})")
        voice = elevenlabs_service.generate_speech_with_timestamps(
            script["full_speech_text"], str(run_dir / "voice_full.mp3"),
            voice_id=str(settings.get("voice_id", "")).strip() or None)
        alignment = voice["alignment"]

    if social_caption:
        (run_dir / "caption.txt").write_text(social_caption + "\n", encoding="utf-8")

    _notify(progress, "subtitle", f"กำลังสร้างซับไตเติลภาษาไทย ({product_name})")
    chunks = subtitle_service.build_micro_chunk_subtitles(alignment, max_words=4)
    style = _subtitle_style(settings)
    subtitle_service.save_srt(chunks, str(run_dir / "subtitles.srt"))
    subtitle_service.save_ass(chunks, str(run_dir / "subtitles_karaoke.ass"), style=style)
    subtitle_service.save_chunks_json(chunks, str(run_dir / "subtitles.json"))

    _notify(progress, "render", f"กำลังเรนเดอร์วิดีโอ MP4 ({product_name})")
    final_path = run_dir / "final.mp4"
    result = video_engine.assemble_video(
        str(video), voice["audio_path"], str(final_path),
        padding=float(settings.get("padding", 1.0)),
        burn_subtitles_srt=str(run_dir / "subtitles_karaoke.ass"))

    _notify(progress, "capcut", f"กำลังสร้าง CapCut Draft ({product_name})")
    draft_dir = capcut_engine.create_capcut_draft(
        f"{product_name}_{run_id}", str(video), voice["audio_path"],
        chunks, capcut_dir, padding=float(settings.get("padding", 1.0)),
        subtitle_style=style)
    with open(Path(draft_dir) / "draft_content.json", "r", encoding="utf-8") as file:
        capcut_engine.validate_draft_content(json.load(file))

    review = product_service.record_review(product_name, product_link)
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "product_name": product_name,
        "product_link": product_link.strip(),
        "review_count": review["count"],
        "caption": caption,
        "hashtags": hashtags,
        "social_caption": social_caption,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_video": str(video),
        "run_dir": str(run_dir.resolve()),
        "final_video": str(final_path.resolve()),
        "voice_audio": str(Path(voice["audio_path"]).resolve()),
        "draft_dir": str(Path(draft_dir).resolve()),
        "duration_seconds": result["final_duration_seconds"],
        "reused_voice": bool(reuse_run_dir),
        "subtitle_style": style,
    }
    (run_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _notify(progress, "complete", f"สร้าง {product_name} เสร็จสมบูรณ์")
    return metadata


def scan_library() -> list:
    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for product_dir in (path for path in output_dir.iterdir() if path.is_dir()):
        candidates = [product_dir]
        candidates.extend(path for path in product_dir.iterdir() if path.is_dir())
        for run_dir in candidates:
            final_path = run_dir / "final.mp4"
            if not final_path.is_file():
                fallback = run_dir / "final_fixed.mp4"
                final_path = fallback if fallback.is_file() else None
            if final_path is None:
                continue
            metadata_path = run_dir / "run_metadata.json"
            metadata = {}
            if metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    metadata = {}
            stat = final_path.stat()
            entries.append({
                "run_id": metadata.get("run_id", run_dir.name),
                "product_name": metadata.get("product_name", product_dir.name),
                "product_link": metadata.get("product_link", ""),
                "review_count": metadata.get("review_count", 0),
                "caption": metadata.get("caption", ""),
                "hashtags": metadata.get("hashtags", []),
                "social_caption": metadata.get("social_caption", ""),
                "created_at": metadata.get(
                    "created_at", datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")),
                "source_video": metadata.get("source_video", ""),
                "run_dir": str(run_dir.resolve()),
                "final_video": str(final_path.resolve()),
                "voice_audio": metadata.get("voice_audio", ""),
                "draft_dir": metadata.get("draft_dir", ""),
                "duration_seconds": metadata.get("duration_seconds", 0),
                "reused_voice": metadata.get("reused_voice", False),
                "has_metadata": bool(metadata),
                "file_size": stat.st_size,
            })
    return sorted(entries, key=lambda item: item["created_at"], reverse=True)


def delete_run(run_dir: str) -> None:
    target = Path(run_dir).resolve()
    output_dir = Path(config.OUTPUT_DIR).resolve()
    if output_dir not in target.parents:
        raise ValueError("สามารถลบได้เฉพาะโฟลเดอร์ที่อยู่ภายใน output เท่านั้น")
    shutil.rmtree(target)


def _caption_from_run(run_dir: Path) -> tuple:
    caption = ""
    hashtags = []
    social_caption = ""
    for filename in ("run_metadata.json", "script.json"):
        path = run_dir / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        caption = caption or str(data.get("caption", "")).strip()
        hashtags = hashtags or list(data.get("hashtags", []))
        social_caption = social_caption or str(data.get("social_caption", "")).strip()
    if not social_caption and caption:
        social_caption = caption
        if hashtags:
            social_caption += " " + " ".join(hashtags)
    return caption, hashtags, social_caption


def _subtitle_style(settings: dict) -> dict:
    subtitle_y = int(settings.get("subtitle_y", 420))
    return {
        "active_color": str(settings.get("subtitle_color", "#FF2E61")).upper(),
        "font_size": int(settings.get("font_size", 72)),
        "border_px": 4.5,
        "y_top": subtitle_y,
        "capcut_y": -((1920 / 2 - subtitle_y) / (1920 / 2)),
    }


def _new_run_dir(product_name: str) -> Path:
    safe_product = _safe_name(product_name)
    base = Path(config.OUTPUT_DIR) / safe_product
    base.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = base / run_id
    suffix = 2
    while destination.exists():
        destination = base / f"{run_id}_{suffix}"
        suffix += 1
    destination.mkdir()
    return destination


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    try:
        cleaned.encode("ascii")
        return cleaned or "AI_Video"
    except UnicodeEncodeError:
        short_hash = hashlib.md5(value.encode("utf-8")).hexdigest()[:8]
        return f"item_{short_hash}"


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{suffix}{path.suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1


def _notify(callback, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)