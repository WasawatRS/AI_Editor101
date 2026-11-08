import json
import os
import shutil
import subprocess

import config


def run_ffmpeg(args: list) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed: {}\n{}".format(" ".join(cmd), result.stderr.strip()))


def probe_duration_seconds(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError("ffprobe failed: {}".format(result.stderr.strip()))
    return float(result.stdout.strip())


def make_dummy_video(output_path: str, width: int = 1080, height: int = 1920,
                     duration: int = 10, label: str = "AI PIPELINE TEST") -> str:
    run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size={}x{}:rate=30".format(width, height),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", "drawtext=text='{}':fontsize=72:fontcolor=white:x=(w-text_w)/2:y=h/3:box=1:boxcolor=black@0.5:boxborderw=20".format(label),
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest",
        output_path,
    ])
    return output_path


def assemble_video(video_path: str, voice_path: str, output_path: str,
                   padding: float = 1.0, burn_subtitles_srt: str | None = None) -> dict:
    """Mute เสียงเดิม -> วางเสียงพากย์ -> ตัดหางคลิปที่เกิน (Audio End + padding)"""
    video_dur = probe_duration_seconds(video_path)
    voice_dur = probe_duration_seconds(voice_path)
    trim_duration = min(video_dur, round(voice_dur + padding, 3))

    vf_args = []
    burn_tmp = None
    if burn_subtitles_srt and (" " in burn_subtitles_srt):
        # subtitle/ass filter ของ FFmpeg ปัญหาช่องว่างในพาธ -> คัดลอกไปพาธชั่วคราวที่ปลอดช่องว่าง
        burn_tmp = os.path.join(config.BASE_DIR, "_burn_subs_tmp")
        burn_tmp += os.path.splitext(burn_subtitles_srt)[1]
        shutil.copyfile(burn_subtitles_srt, burn_tmp)
        burn_subtitles_srt = burn_tmp
    if burn_subtitles_srt:
        path_in_filter = burn_subtitles_srt.replace("\\", "/").replace(":", "\\:")
        fonts_dir = os.path.join(config.BASE_DIR, "fonts")
        fonts_dir_in_filter = fonts_dir.replace("\\", "/").replace(":", "\\:")
        if burn_subtitles_srt.lower().endswith(".ass"):
            vf_args = ["-vf", "ass='{}'".format(path_in_filter)]
            if os.path.isdir(fonts_dir):
                vf_args[1] += ":fontsdir='{}'".format(fonts_dir_in_filter)
        else:
            vf_args = ["-vf", "subtitles='{}'".format(path_in_filter)]
            if os.path.isdir(fonts_dir):
                vf_args[1] += ":fontsdir='{}'".format(fonts_dir_in_filter)

    args = [
        "-i", video_path,
        "-i", voice_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-t", str(trim_duration),
        *vf_args,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        output_path,
    ]
    run_ffmpeg(args)

    if burn_tmp:
        shutil.rmtree(burn_tmp, ignore_errors=True)
        if os.path.exists(burn_tmp):
            os.remove(burn_tmp)

    return {
        "output_path": output_path,
        "video_duration_seconds": round(video_dur, 3),
        "voice_duration_seconds": round(voice_dur, 3),
        "final_duration_seconds": trim_duration,
        "trimmed_seconds": round(video_dur - trim_duration, 3),
    }
