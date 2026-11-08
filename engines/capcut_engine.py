import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from services.subtitle_service import KARAOKE_STYLE

from .video_engine import probe_duration_seconds

_MICROSECONDS = 1_000_000
_MATERIAL_LISTS = [
    "ai_translates", "audio_balances", "audio_effects", "audio_fades",
    "audio_pannings", "audio_pitch_shifts", "audio_track_indexes", "audios",
    "beats", "canvases", "chromas", "color_curves", "common_mask",
    "digital_human_model_dressing", "digital_humans", "drafts", "effects",
    "flowers", "green_screens", "handwrites", "hsl", "hsl_curves", "images",
    "log_color_wheels", "loudnesses", "manual_beautys", "manual_deformations",
    "material_animations", "material_colors", "multi_language_refs",
    "placeholder_infos", "placeholders", "plugin_effects", "primary_color_wheels",
    "realtime_denoises", "shapes", "smart_crops", "smart_relights",
    "sound_channel_mappings", "speeds", "stickers", "tail_leaders",
    "text_templates", "texts", "time_marks", "transitions", "video_effects",
    "video_radius", "video_shadows", "video_strokes", "video_trackings", "videos",
    "vocal_beautifys", "vocal_separations",
]


def find_capcut_draft_dir() -> str:
    """คืนพาธ Drafts ของ CapCut Desktop; กำหนดเองได้ด้วย CAPCUT_DRAFT_DIR."""
    override = os.getenv("CAPCUT_DRAFT_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return str(path.resolve())
        raise FileNotFoundError("CAPCUT_DRAFT_DIR ไม่มีอยู่จริง: {}".format(path))

    local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    candidates = [
        local_app_data / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
        Path.home() / "Documents" / "JianyingPro Drafts",
        Path.home() / "Movies" / "JianyingPro Drafts",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate.resolve())
    raise FileNotFoundError(
        "ไม่พบโฟลเดอร์ CapCut Drafts โปรดเปิด CapCut อย่างน้อยหนึ่งครั้ง "
        "หรือกำหนด CAPCUT_DRAFT_DIR"
    )


def create_capcut_draft(project_name: str, raw_video_path: str, voice_audio_path: str,
                        chunks: list, capcut_draft_dir: str | None = None,
                        video_width: int = 1080, video_height: int = 1920,
                        padding: float = 1.0,
                        subtitle_style: dict | None = None) -> str:
    """สร้าง Draft จริง 3 tracks: วิดีโอ mute, เสียงพากย์ และซับ chunk-pop

    ความยาว Draft คือ min(ความยาววิดีโอ, ความยาวเสียงพากย์ + padding).
    ทุกช่วงเวลาใน draft_content.json ใช้ microseconds ตาม CapCut Desktop.
    """
    if not chunks:
        raise ValueError("ต้องมี subtitle chunks อย่างน้อยหนึ่งกลุ่ม")
    if padding < 0:
        raise ValueError("padding ต้องไม่ติดลบ")
    style = {**KARAOKE_STYLE, **(subtitle_style or {})}

    video_path = Path(raw_video_path).resolve()
    audio_path = Path(voice_audio_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError("ไม่พบวิดีโอต้นฉบับ: {}".format(video_path))
    if not audio_path.is_file():
        raise FileNotFoundError("ไม่พบเสียงพากย์: {}".format(audio_path))

    drafts_root = Path(capcut_draft_dir or find_capcut_draft_dir()).resolve()
    drafts_root.mkdir(parents=True, exist_ok=True)
    target_dir = _available_project_dir(drafts_root, project_name)
    target_dir.mkdir()
    resources_dir = target_dir / "Resources"
    resources_dir.mkdir()

    video_duration = probe_duration_seconds(str(video_path))
    audio_duration = probe_duration_seconds(str(audio_path))
    draft_duration = min(video_duration, audio_duration + padding)
    if draft_duration <= 0:
        raise ValueError("ความยาววิดีโอหรือเสียงพากย์ต้องมากกว่า 0")

    duration_us = _to_us(draft_duration)
    voice_duration_us = min(_to_us(audio_duration), duration_us)
    video_id = _id()
    audio_id = _id()
    draft_id = _id()
    speed_video_id = _id()
    speed_audio_id = _id()
    channel_video_id = _id()
    channel_audio_id = _id()
    vocal_separation_id = _id()
    font_path = _prepare_font(resources_dir)

    materials = {name: [] for name in _MATERIAL_LISTS}
    materials["canvases"].append({
        "id": _id(), "type": "canvas_color", "color": "", "blur": 0.0,
        "image": "", "album_image": "", "image_id": "", "image_name": "",
        "source_platform": 0, "team_id": "",
    })
    materials["videos"].append(_video_material(
        video_id, video_path, _to_us(video_duration), video_width, video_height))
    materials["audios"].append(_audio_material(audio_id, audio_path, _to_us(audio_duration)))
    materials["speeds"].extend([
        {"id": speed_video_id, "type": "speed", "mode": 0, "speed": 1.0,
         "curve_speed": None},
        {"id": speed_audio_id, "type": "speed", "mode": 0, "speed": 1.0,
         "curve_speed": None},
    ])
    materials["sound_channel_mappings"].extend([
        {"id": channel_video_id, "type": "none", "audio_channel_mapping": 0,
         "is_config_open": False},
        {"id": channel_audio_id, "type": "none", "audio_channel_mapping": 0,
         "is_config_open": False},
    ])
    materials["vocal_separations"].append({
        "id": vocal_separation_id, "type": "vocal_separation", "choice": 0,
        "removed_sounds": [], "time_range": None, "production_path": "",
        "final_algorithm": "", "enter_from": "",
    })

    video_segment = _base_segment(
        video_id, 0, duration_us, source_duration=duration_us,
        render_index=0, track_render_index=0, volume=0.0)
    video_segment["extra_material_refs"] = [
        speed_video_id, channel_video_id, vocal_separation_id,
    ]
    audio_segment = _base_segment(
        audio_id, 0, voice_duration_us, source_duration=voice_duration_us,
        render_index=0, track_render_index=0, volume=1.0)
    audio_segment["extra_material_refs"] = [speed_audio_id, channel_audio_id]
    audio_segment["clip"] = None

    text_segments = []
    for chunk in chunks:
        chunk_segments, chunk_materials = _build_chunk_pop_segment(
            chunk, font_path, len(text_segments), style)
        text_segments.extend(chunk_segments)
        materials["texts"].extend(chunk_materials)

    now_us = int(time.time() * 1_000_000)
    draft = {
        "canvas_config": {
            "background": None, "height": video_height, "ratio": "original",
            "width": video_width,
        },
        "color_space": 0,
        "config": _draft_config(),
        "cover": None,
        "create_time": 0,
        "draft_type": "video",
        "duration": duration_us,
        "extra_info": None,
        "fps": 30.0,
        "free_render_index_mode_on": False,
        "group_container": None,
        "id": draft_id,
        "is_drop_frame_timecode": False,
        "keyframe_graph_list": [],
        "keyframes": {
            "adjusts": [], "audios": [], "effects": [], "filters": [],
            "handwrites": [], "stickers": [], "texts": [], "videos": [],
        },
        "last_modified_platform": _platform_info(),
        "lyrics_effects": [],
        "materials": materials,
        "mutable_config": None,
        "name": target_dir.name,
        "new_version": "189.0.0",
        "path": _json_path(target_dir / "draft_content.json"),
        "platform": _platform_info(),
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "smart_ads_info": None,
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": [],
        "tracks": [
            _track("video", [video_segment]),
            _track("audio", [audio_segment]),
            _track("text", text_segments),
        ],
        "uneven_animation_template_info": None,
        "update_time": now_us,
        "version": 360000,
    }

    validate_draft_content(draft)
    draft_json_path = target_dir / "draft_content.json"
    _write_json_atomic(draft_json_path, draft)
    with draft_json_path.open("r", encoding="utf-8") as file:
        validate_draft_content(json.load(file))

    metadata = _draft_metadata(
        target_dir, drafts_root, draft_id, target_dir.name, duration_us,
        now_us, video_path, audio_path, video_duration, audio_duration,
        video_width, video_height,
    )
    _write_json_atomic(target_dir / "draft_meta_info.json", metadata)
    _write_json_atomic(target_dir / "draft_virtual_store.json", {"drafts": []})
    _update_root_metadata(drafts_root, target_dir, draft_id, target_dir.name,
                          duration_us, now_us)

    print("  [CapCut] สร้าง Draft สำเร็จ: {}".format(target_dir))
    print("  [CapCut] Auto-Trim: {:.3f}s (voice {:.3f}s + padding {:.1f}s)".format(
        draft_duration, audio_duration, padding))
    return str(target_dir)


def validate_draft_content(draft: dict) -> None:
    """ตรวจ schema หลัก, references, เวลา และการทับซ้อนของ segments."""
    required = {"canvas_config", "duration", "fps", "materials", "tracks"}
    missing = required.difference(draft)
    if missing:
        raise ValueError("draft_content ขาด key: {}".format(", ".join(sorted(missing))))
    if not isinstance(draft["duration"], int) or draft["duration"] <= 0:
        raise ValueError("draft duration ต้องเป็น microseconds แบบ int และมากกว่า 0")

    material_ids = set()
    for name, items in draft["materials"].items():
        if not isinstance(items, list):
            raise ValueError("materials.{} ต้องเป็น list".format(name))
        for material in items:
            material_id = material.get("id")
            if not material_id:
                raise ValueError("material ใน {} ไม่มี id".format(name))
            if material_id in material_ids:
                raise ValueError("material id ซ้ำ: {}".format(material_id))
            material_ids.add(material_id)

    track_types = [track.get("type") for track in draft["tracks"]]
    if track_types != ["video", "audio", "text"]:
        raise ValueError("tracks ต้องเรียง video, audio, text")
    for track in draft["tracks"]:
        previous_end = 0
        for segment in track.get("segments", []):
            material_id = segment.get("material_id")
            if material_id not in material_ids:
                raise ValueError("segment อ้าง material ที่ไม่มีอยู่: {}".format(material_id))
            for ref in segment.get("extra_material_refs", []):
                if ref not in material_ids:
                    raise ValueError("segment อ้าง extra material ที่ไม่มีอยู่: {}".format(ref))
            timerange = segment.get("target_timerange", {})
            start = timerange.get("start")
            duration = timerange.get("duration")
            if not isinstance(start, int) or not isinstance(duration, int):
                raise ValueError("target_timerange ต้องเป็น int microseconds")
            if start < 0 or duration <= 0 or start + duration > draft["duration"]:
                raise ValueError("segment อยู่นอกขอบเขต draft")
            if start < previous_end:
                raise ValueError("segments ทับซ้อนกันใน track {}".format(track["type"]))
            previous_end = start + duration

    video_segment = draft["tracks"][0]["segments"][0]
    if video_segment.get("volume") != 0.0:
        raise ValueError("วิดีโอต้นฉบับต้อง volume = 0.0")
    if draft["tracks"][1]["segments"][0]["target_timerange"]["start"] != 0:
        raise ValueError("เสียงพากย์ต้องเริ่มที่ 0")

    for text in draft["materials"]["texts"]:
        content = json.loads(text["content"])
        if not content.get("text") or not content.get("styles"):
            raise ValueError("text material ไม่มีข้อความหรือ styles")
        for style in content["styles"]:
            start, end = style["range"]
            if not 0 <= start < end <= len(content["text"]):
                raise ValueError("ช่วง rich-text style ไม่ถูกต้อง")


def _build_chunk_pop_segment(chunk: dict, font_path: Path, render_offset: int,
                             style: dict) -> tuple:
    """หนึ่ง chunk = หนึ่ง segment เพื่อกัน rich-text สลับคำและซ้อนใน CapCut."""
    words = chunk.get("words") or []
    if not words:
        raise ValueError("subtitle chunk ต้องมี sub-word timings")
    start_us = _to_us(float(chunk["start_time"]))
    end_us = _to_us(float(chunk["end_time"]))
    if end_us <= start_us:
        raise ValueError("subtitle chunk ต้องมีเวลามากกว่า 0")

    material = _text_material(
        chunk["text"], words, float(chunk["start_time"]), font_path, style)
    segment = _base_segment(
        material["id"], start_us, end_us - start_us, source_duration=None,
        render_index=14000 + render_offset, track_render_index=2)
    segment["source_timerange"] = None
    segment["clip"]["transform"] = {"x": 0.0, "y": style["capcut_y"]}
    segment["enable_adjust"] = False
    segment["enable_lut"] = False
    return [segment], [material]


def _text_material(text: str, words: list, chunk_start: float,
                   font_path: Path, style: dict) -> dict:
    # หนึ่ง chunk = หนึ่งสี เพื่อเลี่ยง rich-text karaoke ของ CapCut
    capcut_font_size = float(style["font_size"]) * 0.225
    content = {
        "text": text,
        "styles": [_rich_text_style(
            0, len(text), style["active_color"], font_path, capcut_font_size)],
    }
    relative_start_ms = [max(0, int(round((word["start"] - chunk_start) * 1000)))
                         for word in words]
    relative_end_ms = [max(0, int(round((word["end"] - chunk_start) * 1000)))
                       for word in words]
    font_file = _json_path(font_path)
    return {
        "id": _id(), "name": "", "type": "text",
        "content": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        "base_content": "", "recognize_text": text, "recognize_task_id": "",
        "recognize_model": "", "punc_model": "",
        "words": {
            "start_time": relative_start_ms, "end_time": relative_end_ms,
            "text": [word["word"] for word in words],
        },
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0,
        "combo_info": {"text_templates": []},
        "caption_template_info": _empty_resource_info(),
        "layer_weight": 1, "letter_spacing": 0.0, "text_curve": None,
        "text_loop_on_path": False, "offset_on_path": 0.0,
        "enable_path_typesetting": False, "text_exceeds_path_process_type": 0,
        "text_typesetting_paths": None, "text_typesetting_paths_file": "",
        "text_typesetting_path_index": 0, "line_spacing": 0.25,
        "has_shadow": False, "shadow_color": "", "shadow_alpha": 0.0,
        "shadow_smoothing": 0.0, "shadow_distance": 5.0,
        "shadow_point": {"x": 0.0, "y": 0.0}, "shadow_angle": -45.0,
        "shadow_thickness_projection_enable": False,
        "shadow_thickness_projection_angle": 0.0,
        "shadow_thickness_projection_distance": 0.0,
        "border_alpha": 1.0, "border_color": "#FF000000",
        "border_width": float(style["border_px"]) / float(style["font_size"]),
        "border_mode": 0, "style_name": "",
        "text_color": _hex_to_argb(style["active_color"]), "text_alpha": 1.0,
        "font_name": style["font"], "font_title": style["font"],
        "font_size": capcut_font_size, "font_path": font_file, "font_id": "",
        "font_resource_id": "", "initial_scale": 1.0, "font_url": "",
        "font_fallbacks": style["font_fallbacks"],
        "typesetting": 0, "alignment": 1, "line_feed": 1,
        "use_effect_default_color": False, "is_rich_text": False,
        "shape_clip_x": False, "shape_clip_y": False,
        "ktv_color": "", "text_to_audio_ids": [],
        "bold_width": 0.008, "italic_degree": 10, "underline": False,
        "underline_width": 0.05, "underline_offset": 0.22,
        "sub_type": 0, "check_flag": 47, "text_size": 30,
        "font_category_name": "", "font_source_platform": 0,
        "font_third_resource_id": "", "font_category_id": "",
        "add_type": 0, "operation_type": 0, "recognize_type": 0,
        "fonts": [{
            "id": _id(), "resource_id": "", "third_resource_id": "",
            "category_id": "", "category_name": "", "source_platform": 0,
            "path": font_file, "effect_id": "", "title": style["font"],
            "team_id": "", "file_uri": "", "request_id": "",
        }],
        "background_color": "#00000000", "background_alpha": 0.0, "background_style": 0,
        "background_round_radius": 0.0, "background_width": 0.14,
        "background_height": 0.14, "background_vertical_offset": 0.0,
        "background_horizontal_offset": 0.0, "background_fill": "",
        "single_char_bg_enable": False, "single_char_bg_color": "",
        "single_char_bg_alpha": 1.0, "single_char_bg_round_radius": 0.3,
        "single_char_bg_width": 0.0, "single_char_bg_height": 0.0,
        "single_char_bg_vertical_offset": 0.0,
        "single_char_bg_horizontal_offset": 0.0,
        "font_team_id": "", "tts_auto_update": False,
        "text_preset_resource_id": "", "group_id": "", "preset_id": "",
        "preset_name": "", "preset_category": "", "preset_category_id": "",
        "preset_index": 0, "preset_has_set_alignment": False,
        "force_apply_line_max_width": True, "language": "th-TH",
        "relevance_segment": [], "original_size": [], "fixed_width": -1.0,
        "fixed_height": -1.0, "autoAdaptCanvasEnabled": False,
        "line_max_width": 0.9, "oneline_cutoff": True, "cutoff_postfix": "",
        "subtitle_template_original_fontsize": 0.0, "subtitle_keywords": None,
        "inner_padding": -1.0, "multi_language_current": "none", "source_from": "",
        "is_lyric_effect": False, "lyric_group_id": "",
        "lyrics_template": _empty_resource_info(), "is_batch_replace": False,
        "is_words_linear": False, "ssml_content": "", "subtitle_keywords_config": None,
        "sub_template_id": -1, "translate_original_text": "", "adjust_params": [],
    }


def _rich_text_style(start: int, end: int, color: str, font_path: Path,
                     font_size: float) -> dict:
    return {
        "fill": {"content": {"render_type": "solid", "solid": {
            "color": _hex_to_rgb(color),
        }}},
        "font": {"path": _json_path(font_path), "id": ""},
        "size": font_size,
        "range": [start, end],
    }


def _video_material(material_id: str, path: Path, duration_us: int,
                    width: int, height: int) -> dict:
    return {
        "id": material_id, "type": "video", "path": _json_path(path),
        "material_name": path.name, "duration": duration_us, "width": width,
        "height": height, "has_audio": True, "has_sound_separated": False,
        "category_id": "", "category_name": "local", "check_flag": 62978047,
        "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0,
                 "upper_left_x": 0.0, "upper_left_y": 0.0,
                 "upper_right_x": 1.0, "upper_right_y": 0.0},
        "crop_ratio": "free", "crop_scale": 1.0, "extra_type_option": 1,
        "formula_id": "", "freeze": None, "intensifies_audio_path": "",
        "intensifies_path": "", "is_ai_generate_content": False,
        "is_copyright": False, "is_text_edit_overdub": False,
        "is_unified_beauty_mode": False, "local_id": "", "local_material_from": "",
        "local_material_id": "", "material_id": "", "material_url": "",
        "media_path": "", "multi_camera_info": None, "object_locked": None,
        "origin_material_id": "", "picture_from": "none",
        "picture_set_category_id": "", "picture_set_category_name": "",
        "request_id": "", "reverse_intensifies_path": "", "reverse_path": "",
        "smart_match_info": None, "smart_motion": None, "source": 0,
        "source_platform": 0, "stable": {"matrix_path": "", "stable_level": 0,
        "time_range": {"duration": 0, "start": 0}}, "surface_trackings": [],
        "team_id": "", "unique_id": "", "video_algorithm": None,
        "aigc_type": "none", "audio_fade": None,
    }


def _audio_material(material_id: str, path: Path, duration_us: int) -> dict:
    return {
        "id": material_id, "type": "audio", "path": _json_path(path),
        "material_name": path.name, "duration": duration_us, "category_id": "",
        "category_name": "local", "check_flag": 1, "copyright_limit": "none",
        "effect_id": "", "formula_id": "", "intensifies_path": "",
        "is_ai_clone_tone": False, "is_text_edit_overdub": False, "is_ugc": False,
        "local_material_id": "", "material_id": "", "material_url": "",
        "media_path": "", "music_id": "", "query": "", "recognize_task_id": "",
        "request_id": "", "resource_id": "", "search_id": "", "sound_effect_id": "",
        "source_platform": 0, "team_id": "", "text_id": "", "tone_category_id": "",
        "tone_category_name": "", "tone_effect_id": "", "tone_effect_name": "",
        "tone_id": "", "tone_name": "", "tone_platform": "", "tone_type": "",
        "tone_url": "", "video_id": "", "wave_points": [], "app_id": 0,
    }


def _base_segment(material_id: str, start_us: int, duration_us: int,
                  source_duration: int | None, render_index: int,
                  track_render_index: int, volume: float = 1.0) -> dict:
    return {
        "id": _id(), "caption_info": None, "cartoon": False,
        "clip": {
            "alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
        },
        "color_correct_alg_result": "", "common_keyframes": [], "desc": "",
        "digital_human_template_group_id": "", "enable_adjust": True,
        "enable_adjust_mask": False, "enable_color_adjust_pro": False,
        "enable_color_correct_adjust": False, "enable_color_curves": True,
        "enable_color_match_adjust": False, "enable_color_wheels": True,
        "enable_hsl": False, "enable_hsl_curves": True, "enable_lut": True,
        "enable_mask_shadow": False, "enable_mask_stroke": False,
        "enable_smart_color_adjust": False, "enable_video_mask": True,
        "extra_material_refs": [], "group_id": "", "hdr_settings": None,
        "intensifies_audio": False, "is_loop": False,
        "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [],
        "last_nonzero_volume": 1.0, "lyric_keyframes": None,
        "material_id": material_id, "raw_segment_id": "", "render_index": render_index,
        "render_timerange": {"duration": 0, "start": 0},
        "responsive_layout": {"enable": False, "horizontal_pos_layout": 0,
                              "size_layout": 0, "target_follow": "",
                              "vertical_pos_layout": 0},
        "reverse": False, "source": "segmentsourcenormal",
        "source_timerange": (None if source_duration is None else {
            "duration": source_duration, "start": 0,
        }),
        "speed": 1.0, "state": 0,
        "target_timerange": {"duration": duration_us, "start": start_us},
        "template_id": "", "template_scene": "default", "track_attribute": 0,
        "track_render_index": track_render_index,
        "uniform_scale": {"on": True, "value": 1.0}, "visible": True,
        "volume": volume, "segment_color_tag": "",
    }


def _track(track_type: str, segments: list) -> dict:
    return {
        "id": _id(), "type": track_type, "segments": segments, "flag": 1,
        "attribute": 0, "name": "", "is_default_name": True,
    }


def _draft_config() -> dict:
    return {
        "adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1,
        "export_range": None, "extract_audio_last_index": 1,
        "lyrics_recognition_id": "", "lyrics_sync": True, "lyrics_taskinfo": [],
        "maintrack_adsorb": True, "material_save_mode": 0,
        "multi_language_current": "none", "multi_language_list": [],
        "multi_language_main": "none", "multi_language_mode": "none",
        "original_sound_last_index": 1, "record_audio_last_index": 1,
        "sticker_max_index": 1, "subtitle_keywords_config": None,
        "subtitle_recognition_id": "", "subtitle_sync": True,
        "subtitle_taskinfo": [], "system_font_list": [], "use_float_render": False,
        "video_mute": False, "zoom_info_params": None,
    }


def _platform_info() -> dict:
    return {
        "app_id": 359289, "app_source": "cc", "app_version": "9.2.0",
        "device_id": "", "hard_disk_id": "", "mac_address": "",
        "os": "windows" if os.name == "nt" else "other", "os_version": "",
    }


def _draft_metadata(target_dir: Path, drafts_root: Path, draft_id: str,
                    name: str, duration_us: int, now_us: int, video_path: Path,
                    audio_path: Path, video_duration: float, audio_duration: float,
                    width: int, height: int) -> dict:
    video = _metadata_media(video_path, video_duration, width, height, "video")
    audio = _metadata_media(audio_path, audio_duration, 0, 0, "audio")
    return {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "cloud_package_completed_time": "", "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False, "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "", "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "",
                                  "draft_enterprise_id": "", "draft_enterprise_name": "",
                                  "enterprise_material": []},
        "draft_fold_path": _json_path(target_dir), "draft_id": draft_id,
        "draft_is_ae_produce": False, "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False, "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False, "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false", "draft_is_invisible": False,
        "draft_is_web_article_video": False,
        "draft_materials": [{"type": 0, "value": [video]},
                            {"type": 1, "value": [audio]}],
        "draft_materials_copied_info": [], "draft_name": name,
        "draft_need_rename_folder": False, "draft_new_version": "",
        "draft_removable_storage_device": "", "draft_root_path": str(drafts_root),
        "draft_segment_extra_info": {}, "draft_timeline_materials_size_":
            video_path.stat().st_size + audio_path.stat().st_size,
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": duration_us,
    }


def _metadata_media(path: Path, duration: float, width: int, height: int,
                    media_type: str) -> dict:
    now = int(time.time())
    duration_us = _to_us(duration)
    return {
        "ai_group_type": "", "create_time": now, "duration": duration_us,
        "enter_from": 0, "extra_info": path.name, "file_Path": _json_path(path),
        "height": height, "id": _id(), "import_time": now,
        "import_time_ms": int(time.time() * 1_000_000), "item_source": 1,
        "md5": "", "metetype": media_type,
        "roughcut_time_range": {"duration": duration_us, "start": 0},
        "sub_time_range": {"duration": -1, "start": -1}, "type": 0,
        "width": width,
    }


def _update_root_metadata(drafts_root: Path, target_dir: Path, draft_id: str,
                          name: str, duration_us: int, now_us: int) -> None:
    root_path = drafts_root / "root_meta_info.json"
    root = {"all_draft_store": []}
    if root_path.exists():
        with root_path.open("r", encoding="utf-8") as file:
            root = json.load(file)
    entries = root.setdefault("all_draft_store", [])
    entries[:] = [entry for entry in entries
                  if entry.get("draft_id") != draft_id
                  and Path(entry.get("draft_fold_path", "")) != target_dir]
    entries.insert(0, {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "", "draft_cover": "",
        "draft_fold_path": _json_path(target_dir), "draft_id": draft_id,
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_infinite_canvas_draft": False, "draft_is_invisible": False,
        "draft_is_pippit_draft": False, "draft_is_web_article_video": False,
        "draft_json_file": _json_path(target_dir / "draft_content.json"),
        "draft_name": name, "draft_new_version": "",
        "draft_root_path": _json_path(drafts_root), "draft_timeline_materials_size": 0,
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "", "pippit_id": "",
        "pippit_user_name": "", "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": duration_us,
    })
    _write_json_atomic(root_path, root)


def _prepare_font(resources_dir: Path) -> Path:
    source = Path(__file__).resolve().parent.parent / "fonts" / "Mitr-SemiBold.ttf"
    if not source.is_file():
        raise FileNotFoundError("ไม่พบฟอนต์ Mitr: {}".format(source))
    destination = resources_dir / source.name
    shutil.copy2(source, destination)
    return destination


def _available_project_dir(root: Path, project_name: str) -> Path:
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", project_name).strip(" .")
    safe_name = safe_name or "AI_Video"
    candidate = root / safe_name
    suffix = 2
    while candidate.exists():
        candidate = root / "{}_{}".format(safe_name, suffix)
        suffix += 1
    return candidate


def _empty_resource_info() -> dict:
    return {
        "resource_id": "", "third_resource_id": "", "resource_name": "",
        "category_id": "", "category_name": "", "effect_id": "", "request_id": "",
        "path": "", "is_new": False, "source_platform": 0,
    }


def _hex_to_argb(color: str) -> str:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError("สีต้องเป็น #RRGGBB: {}".format(color))
    return "#FF" + value.upper()


def _hex_to_rgb(color: str) -> list:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError("สีต้องเป็น #RRGGBB: {}".format(color))
    return [round(int(value[index:index + 2], 16) / 255.0, 6)
            for index in (0, 2, 4)]


def _json_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _to_us(seconds: float) -> int:
    return int(round(seconds * _MICROSECONDS))


def _id() -> str:
    return str(uuid.uuid4()).upper()


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
