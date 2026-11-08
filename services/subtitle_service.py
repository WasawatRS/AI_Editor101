import json
import math
import re
import unicodedata

from pythainlp import word_tokenize

KARAOKE_STYLE = {
    "font": "Mitr",
    "font_fallbacks": ["Prompt", "Kanit", "sans-serif"],
    "font_size": 72,  # ปรับให้อยู่ในช่วง 65-80 px
    "base_color": "#FFFFFF",
    "active_color": "#FF2E61",
    "border_color": "#000000",
    "border_px": 4.5,
    "shadow_opacity": 0.0,
    "canvas": [1080, 1920],
    "x_center": 540,
    "y_top": 420,
    # CapCut ใช้แกน Y ติดลบเมื่อเลื่อนขึ้นจากกึ่งกลาง: 420 px จากขอบบน
    "capcut_y": -0.5625,
}

_PHRASE_STARTERS = {"และ", "แต่", "ที่", "ว่า", "จะ", "ไม่", "ถ้า", "แล้ว"}
_LATIN_FRAGMENT = re.compile(r"[A-Za-z0-9.+_-]+\Z")
_SENTENCE_PUNCTUATION = {"!", "?", "!!!", "??", ".", "…"}


def build_micro_chunk_subtitles(
        alignment: dict, max_words: int = 4, min_duration: float = 1.0,
        max_duration: float = 1.8, pause_threshold: float = 0.25,
        max_chars: int = 24) -> list:
    """สร้างซับ 2-4 คำจาก ElevenLabs โดยไม่แยก Thai grapheme และไม่ซ้อนเวลา"""
    if not 2 <= max_words <= 4:
        raise ValueError("max_words ต้องอยู่ระหว่าง 2-4")
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("ช่วง duration ไม่ถูกต้อง")

    characters, starts, ends = _normalise_alignment(alignment)
    if not characters:
        return []

    words = _reconstruct_words(characters, starts, ends)
    groups = []
    current = []

    def flush():
        if current:
            groups.append(list(current))
            current.clear()

    for word in words:
        if current:
            gap = max(0.0, word["start"] - current[-1]["end"])
            candidate_duration = word["end"] - current[0]["start"]
            candidate_chars = sum(len(item["word"]) for item in current + [word])
            should_flush = (
                gap >= pause_threshold
                or len(current) >= max_words
                or (word["word"] in _PHRASE_STARTERS and len(current) >= 2)
                or (len(current) >= 2 and candidate_duration > max_duration)
                or (len(current) >= 2 and candidate_chars > max_chars)
            )
            if should_flush:
                flush()

        current.append(word)
        if word["word"] in _SENTENCE_PUNCTUATION or word["word"].endswith(("!", "?", "…")):
            flush()

    flush()
    groups = _merge_short_groups(groups, min_duration, max_duration, max_chars)
    return _enforce_no_overlap([_make_chunk(group) for group in groups])


def _normalise_alignment(alignment: dict) -> tuple:
    if not isinstance(alignment, dict):
        raise TypeError("alignment ต้องเป็น dict")
    characters = list(alignment.get("characters", []))
    starts = list(alignment.get(
        "starts", alignment.get("character_start_times_seconds", [])))
    ends = list(alignment.get(
        "ends", alignment.get("character_end_times_seconds", [])))
    if not (len(characters) == len(starts) == len(ends)):
        raise ValueError("characters, start times และ end times ต้องมีจำนวนเท่ากัน")

    clean_starts = []
    clean_ends = []
    for index, (start, end) in enumerate(zip(starts, ends)):
        try:
            start = float(start)
            end = float(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("timestamp ตัวที่ {} ไม่ใช่ตัวเลข".format(index)) from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError("timestamp ตัวที่ {} ไม่ถูกต้อง".format(index))
        clean_starts.append(start)
        clean_ends.append(end)
    return characters, clean_starts, clean_ends


def _build_grapheme_clusters(characters: list, starts: list, ends: list) -> list:
    """รวมสระ/วรรณยุกต์กับตัวก่อนหน้า พร้อมเก็บเวลาแบบไม่แยก index."""
    clusters = []
    for character, start, end in zip(characters, starts, ends):
        extends_previous = bool(clusters) and (
            unicodedata.category(character).startswith("M")
            or unicodedata.combining(character) != 0
            or character in "\u200c\u200d\ufe0e\ufe0f"
            or clusters[-1]["text"].endswith("\u200d")
        )
        if extends_previous:
            clusters[-1]["text"] += character
            clusters[-1]["end"] = end
        else:
            clusters.append({"text": character, "start": start, "end": end})
    return clusters


def _reconstruct_words(characters: list, starts: list, ends: list) -> list:
    clusters = _build_grapheme_clusters(characters, starts, ends)
    full_text = "".join(cluster["text"] for cluster in clusters)
    tokens = word_tokenize(full_text, engine="newmm", keep_whitespace=True)
    words = []
    char_cursor = 0
    cluster_cursor = 0
    pending_space = False

    for token in tokens:
        if not full_text.startswith(token, char_cursor):
            raise ValueError("ผลตัดคำไม่ตรงกับสคริปต์ที่ตำแหน่ง {}".format(char_cursor))
        token_end = char_cursor + len(token)
        first_cluster = cluster_cursor
        covered = ""
        while cluster_cursor < len(clusters) and len(covered) < len(token):
            cluster_text = clusters[cluster_cursor]["text"]
            if len(covered) + len(cluster_text) > len(token):
                raise ValueError("พยายามตัดกลาง grapheme: {}".format(cluster_text))
            covered += cluster_text
            cluster_cursor += 1
        if covered != token:
            raise ValueError("จับคู่ grapheme กับคำไม่ครบ: {}".format(token))
        char_cursor = token_end

        if not token.strip():
            pending_space = True
            continue
        item = {
            "word": token,
            "start": clusters[first_cluster]["start"],
            "end": clusters[cluster_cursor - 1]["end"],
            "space_before": pending_space,
        }
        pending_space = False
        if _is_punctuation(token) and words:
            words[-1]["word"] += token
            words[-1]["end"] = item["end"]
        else:
            words.append(item)

    if char_cursor != len(full_text) or cluster_cursor != len(clusters):
        raise ValueError("ผลตัดคำไม่ครอบคลุมสคริปต์เต็ม")
    return _merge_latin_fragments(words)


def _is_punctuation(text: str) -> bool:
    return bool(text) and all(unicodedata.category(char).startswith("P") for char in text)


def _merge_latin_fragments(words: list) -> list:
    """กัน ESP32-S3, RLCD-4.2 และ Type-C ถูกแยกเป็นหลายชิป."""
    merged = []
    for item in words:
        if merged:
            previous = merged[-1]
            if (_LATIN_FRAGMENT.fullmatch(previous["word"])
                    and _LATIN_FRAGMENT.fullmatch(item["word"])):
                previous["word"] += item["word"]
                previous["end"] = item["end"]
                continue
        merged.append(item)
    return merged


def _merge_short_groups(groups: list, min_duration: float,
                        max_duration: float, max_chars: int) -> list:
    if not groups:
        return []

    merged = []
    for group in groups:
        if merged and _can_merge(merged[-1], group, max_duration, max_chars):
            previous_duration = merged[-1][-1]["end"] - merged[-1][0]["start"]
            if previous_duration < min_duration or len(merged[-1]) == 1 or len(group) == 1:
                merged[-1].extend(group)
                continue
        merged.append(list(group))

    if len(merged) > 1 and len(merged[-1]) == 1:
        if _can_merge(merged[-2], merged[-1], max_duration, max_chars):
            merged[-2].extend(merged[-1])
            merged.pop()
    return merged


def _can_merge(first: list, second: list, max_duration: float, max_chars: int) -> bool:
    if len(first) + len(second) > 4:
        return False
    if sum(len(item["word"]) for item in first + second) > max_chars:
        return False
    return second[-1]["end"] - first[0]["start"] <= max_duration


def _enforce_no_overlap(chunks: list) -> list:
    """แก้เวลาปัดเศษ/alignment ที่ชนกัน และปฏิเสธข้อมูลที่แก้โดยไม่เพี้ยนไม่ได้."""
    previous_end = 0.0
    for index, chunk in enumerate(chunks):
        start = max(float(chunk["start_time"]), previous_end)
        end = float(chunk["end_time"])
        if index + 1 < len(chunks):
            end = min(end, float(chunks[index + 1]["start_time"]))
        if end <= start:
            raise ValueError("ซับมีเวลาซ้อนหรือ duration เป็นศูนย์: {}".format(chunk["text"]))
        chunk["start_time"] = round(start, 3)
        chunk["end_time"] = round(end, 3)
        chunk["words"][0]["start"] = max(chunk["words"][0]["start"], start)
        chunk["words"][-1]["end"] = min(chunk["words"][-1]["end"], end)
        previous_end = end
    return chunks


def hex_to_ass(hex_color: str, alpha: str = "00") -> str:
    """แปลง #RRGGBB เป็นสี ASS (&HAABBGGRR - เรียง BGR)."""
    value = hex_color.lstrip("#")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return "&H{}{}{}{}".format(alpha, blue, green, red).upper()


def save_srt(chunks: list, srt_path: str) -> str:
    with open(srt_path, "w", encoding="utf-8") as file:
        for index, chunk in enumerate(chunks, start=1):
            file.write("{}\n{} --> {}\n{}\n\n".format(
                index,
                _format_ts(chunk["start_time"]),
                _format_ts(chunk["end_time"]),
                chunk["text"],
            ))
    return srt_path


def save_chunks_json(chunks: list, json_path: str) -> str:
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(chunks, file, ensure_ascii=False, indent=2)
    return json_path


def save_ass(chunks: list, ass_path: str, style: dict = None) -> str:
    """สร้าง ASS แบบ chunk-pop เพื่อเลี่ยงบั๊ก Thai karaoke shaping ของ renderer."""
    settings = {**KARAOKE_STYLE, **(style or {})}
    canvas_width, canvas_height = settings["canvas"]
    outline = settings["border_px"]

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: {}".format(canvas_width),
        "PlayResY: {}".format(canvas_height),
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Karaoke,{font},{size},{active},{base},{border},&H{shadow_a}000000,"
        "-1,0,0,0,100,100,0,0,1,{outline},0,8,60,60,60,1".format(
            font=settings["font"],
            size=settings["font_size"],
            active=hex_to_ass(settings["active_color"]),
            base=hex_to_ass(settings["base_color"]),
            border=hex_to_ass(settings["border_color"]),
            shadow_a="{:02X}".format(int((1 - settings["shadow_opacity"]) * 255)),
            outline=outline,
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events = []
    previous_end = 0.0
    for chunk in chunks:
        if chunk["start_time"] < previous_end or chunk["end_time"] <= chunk["start_time"]:
            raise ValueError("ASS No Overlap Rule ล้มเหลว: {}".format(chunk["text"]))
        text = "{{\\an8\\pos({},{})}}{}".format(
            settings["x_center"], settings["y_top"], _ass_escape(chunk["text"]))
        events.append("Dialogue: 0,{},{},Karaoke,,0,0,0,,{}".format(
            _format_ass_ts(chunk["start_time"]),
            _format_ass_ts(chunk["end_time"]),
            text,
        ))
        previous_end = chunk["end_time"]

    with open(ass_path, "w", encoding="utf-8") as file:
        file.write("\n".join(header + events) + "\n")
    return ass_path


def _ass_escape(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _make_chunk(items: list) -> dict:
    text_parts = []
    words = []
    cursor = 0
    for index, item in enumerate(items):
        separator = ""
        if index and item.get("space_before"):
            previous = items[index - 1]["word"]
            if _is_ascii_word(previous) and _is_ascii_word(item["word"]):
                separator = " "
        if separator:
            text_parts.append(separator)
            cursor += len(separator)
        start_offset = cursor
        text_parts.append(item["word"])
        cursor += len(item["word"])
        words.append({
            "word": item["word"],
            "start": round(item["start"], 3),
            "end": round(item["end"], 3),
            "start_offset": start_offset,
            "end_offset": cursor,
        })

    return {
        "text": "".join(text_parts),
        "start_time": round(items[0]["start"], 3),
        "end_time": round(items[-1]["end"], 3),
        "words": words,
    }


def _is_ascii_word(text: str) -> bool:
    return bool(text) and text[0].isascii() and text[-1].isascii() and any(
        char.isalnum() for char in text)


def _format_ass_ts(seconds: float) -> str:
    """ASS ต้องเป็น H:MM:SS.cc (centisecond 2 หลัก) ห้ามใช้ millisecond 3 หลัก."""
    centiseconds = int(round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return "{}:{:02d}:{:02d}.{:02d}".format(hours, minutes, secs, centiseconds)


def _format_ts(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, secs, milliseconds)