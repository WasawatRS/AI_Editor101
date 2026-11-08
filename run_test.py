import glob
import json
import os
import sys
import time

import config
from engines import capcut_engine, video_engine
from services import elevenlabs_service, gemini_service, subtitle_service

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def find_first_video(input_dir: str) -> str:
    exts = ("*.mp4", "*.mov", "*.mkv", "*.webm", "*.avi")
    for pattern in exts:
        matches = sorted(glob.glob(os.path.join(input_dir, pattern)))
        if matches:
            return matches[0]
    return ""


def main() -> None:
    t0 = time.time()
    print("=" * 60)
    print("▶ AI Video Automation End-to-End Pipeline")
    print("=" * 60)

    config.validate_config()
    capcut_draft_dir = capcut_engine.find_capcut_draft_dir()
    print("[1/5] .env validate ผ่าน | Voice: {} | Model: {}".format(
        config.ELEVENLABS_VOICE_ID, config.ELEVENLABS_MODEL_ID))
    print("      CapCut Drafts: {}".format(capcut_draft_dir))

    os.makedirs(config.INPUT_DIR, exist_ok=True)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    video_path = find_first_video(config.INPUT_DIR)
    if not video_path:
        print("[2/5] ไม่พบวิดีโอใน input_videos/ -> สร้าง Dummy Video 10 วินาที...")
        video_path = video_engine.make_dummy_video(
            os.path.join(config.INPUT_DIR, "ESP32 S3 RLCD 4.2.mp4"))
    product_name = os.path.splitext(os.path.basename(video_path))[0]
    print("[2/5] วิดีโอทดสอบ: {} | สินค้า: \"{}\"".format(
        os.path.basename(video_path), product_name))

    run_dir = os.path.join(config.OUTPUT_DIR, product_name)
    os.makedirs(run_dir, exist_ok=True)

    print("[3/5] Gemini: วิเคราะห์วิดีโอ + เขียนบทพากย์...")
    script = gemini_service.generate_sales_script(video_path, product_name)
    script_path = os.path.join(run_dir, "script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print("      บทพากย์ ({} วินาที):".format(script["total_estimated_seconds"]))
    for k, v in script["script_sections"].items():
        print("      - {}: {}".format(k, v))

    print("[4/5] ElevenLabs: พากย์เสียง + Alignment...")
    voice = elevenlabs_service.generate_speech_with_timestamps(
        script["full_speech_text"],
        os.path.join(run_dir, "voice_full.mp3"))
    print("      เสียงพากย์: {} | ความยาว {} วินาที".format(
        os.path.basename(voice["audio_path"]), voice["duration_seconds"]))

    chunks = subtitle_service.build_micro_chunk_subtitles(voice["alignment"], max_words=4)
    srt_path = subtitle_service.save_srt(
        chunks, os.path.join(run_dir, "subtitles.srt"))
    ass_path = subtitle_service.save_ass(
        chunks, os.path.join(run_dir, "subtitles_karaoke.ass"))
    subtitle_service.save_chunks_json(
        chunks, os.path.join(run_dir, "subtitles.json"))
    print("      ซับ {} กลุ่ม -> {} + {}".format(
        len(chunks), os.path.basename(srt_path), os.path.basename(ass_path)))

    print("[5/5] สร้างวิดีโอและ CapCut Draft: Mute + Karaoke + Auto-Trim...")
    final_video = os.path.join(run_dir, "final.mp4")
    result = video_engine.assemble_video(
        video_path, voice["audio_path"], final_video,
        padding=1.0, burn_subtitles_srt=ass_path)

    draft_dir = capcut_engine.create_capcut_draft(
        product_name, video_path, voice["audio_path"], chunks, capcut_draft_dir)
    draft_json_path = os.path.join(draft_dir, "draft_content.json")
    with open(draft_json_path, "r", encoding="utf-8") as file:
        capcut_engine.validate_draft_content(json.load(file))
    print("      ตรวจสอบ draft_content.json ผ่านแล้ว")

    elapsed = time.time() - t0
    print("-" * 60)
    print("✅ สำเร็จ! ใช้เวลารวม {:.1f} วินาที".format(elapsed))
    print("   ไฟล์ผลลัพธ์ (ทั้งหมดอยู่ใน {}/):".format(product_name))
    print("   - วิดีโอตัดต่อแล้ว : {}".format(result["output_path"]))
    print("   - เสียงพากย์      : {}".format(voice["audio_path"]))
    print("   - ซับคาราโอเกะ ASS : {}".format(ass_path))
    print("   - ซับไตเติล SRT   : {}".format(srt_path))
    print("   - สคริปต์         : {}".format(script_path))
    print("   - CapCut Draft    : {}".format(draft_dir))
    print("   เปิด/รีสตาร์ท CapCut Desktop แล้วเลือก Draft นี้เพื่อตรวจงานและ Export ได้ทันที")
    print("   คลิปดิบ {:.1f}s -> ตัดเหลือ {:.1f}s (ตัดทิ้ง {:.1f}s)".format(
        result["video_duration_seconds"], result["final_duration_seconds"],
        result["trimmed_seconds"]))
    print("=" * 60)


if __name__ == "__main__":
    main()
