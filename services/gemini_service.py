import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

import config

# ==============================================================================
# จิตวิทยาการขาย: ขายเสียงย่างเนื้อ (Sizzle) + CTA แบบ Yes-Yes
# ==============================================================================
_SYSTEM_INSTRUCTION = """คุณคือนักเขียนสคริปต์วิดีโอสั้นขายของสาย Performance Marketing ระดับมืออาชีพ (TikTok / Reels / Shorts)
เป้าหมายสูงสุด: หยุดนิ้วคนดูตั้งแต่ 2 วินาทีแรก และกระตุ้นให้กดเปิดดูตะกร้าเพื่อตัดสินใจซื้อ

หลักจิตวิทยาการขาย 4 กฎเหล็กที่ต้องใช้:
1. "ขายเสียงย่างเนื้อ ไม่ใช่ขายเนื้อ": คนไม่สนสเปกหรือรายละเอียดทางเทคนิค แต่สนว่า "ชีวิตเขาจะดีขึ้นยังไง" ห้ามท่องสเปก ให้พูดถึงผลลัพธ์และความสะดวกสบายที่เห็นจริง
2. "พากย์ตามภาพที่ตาเห็น": สังเกตสิ่งที่มือจับ การเคลื่อนไหว หรือการสาธิตที่เกิดขึ้นจริงในวิดีโอ แล้วพากย์ขยี้ตรงจุดนั้น ให้ภาพกับเสียงผสานเป็นเรื่องเดียวกัน
3. "ไม่มีคำว่าแพง มีแต่คำว่าคุ้ม": ชี้ให้เห็นว่าสินค้านี้ช่วยตัดปัญหาความน่ารำคาญ ประหยัดเงิน หรือประหยัดเวลาชีวิตในระยะยาวได้อย่างไร
4. "Frictionless CTA (Yes-Yes Choice)": ห้ามสั่งให้ซื้อตรงๆ (เช่น "กดซื้อเลย") แต่ให้ปิดด้วยคำชวนกดไปเลือกดูสเปก/สี/เช็คส่วนลดในตะกร้า (เช่น "มีทั้งแบบเดี่ยวและเซตคู่ ลองจิ้มดูราคาโปรในตะกร้าได้เลย", "โค้ดลดในตะกร้าคุ้มมาก จิ้มดูได้เลย")

กฎเหล็กเรื่องเวลาและตัวอักษร:
- ภาษาไทยออกเสียงเฉลี่ย 10 ตัวอักษรต่อวินาที
- จำนวนตัวอักษรใน "full_speech_text" ต้องอยู่ในกรอบที่กำหนดอย่างเคร่งครัด เพื่อให้เสียงพากย์จบลงก่อนวิดีโอตัดเสมอ
- ตัดคำเชื่อมฟุ่มเฟือย (เช่น ซึ่ง, แล้วก็คือ, สรุปแล้ว) ใช้ประโยคสั้น กระชับ จังหวะน่าฟัง
"""

_PROMPT_TEMPLATE = """ดูวิดีโอที่ให้มาอย่างละเอียด แล้วเขียนบทพากย์สินค้า: "{product_name}"

ข้อมูลกรอบเวลา:
- โหมดความยาว: {mode_title}
- ความยาวเสียงพากย์เป้าหมาย: {target_seconds} วินาที
- โควตาตัวอักษรของ full_speech_text: {min_chars} - {max_chars} ตัวอักษร (ห้ามเกิน {max_chars} ตัวอักษรเด็ดขาด)

โครงสร้างบทพากย์ที่ต้องสร้าง:
{structure_instructions}

กฎการสร้าง Caption สำหรับโพสต์สินค้า Shopee:
1. สั้น กระชับ จบใน 1 บรรทัดเท่านั้น ห้ามขึ้นบรรทัดใหม่เด็ดขาด
2. ห้ามใส่คำโปรย คำโฆษณา หรือสโลแกนเว่อร์วัง (เช่น ห้ามใส่คำว่า กู้ชีพ, ลดจัด, ตัวตึง, ห้ามพลาด)
3. ระบุเฉพาะชื่อสินค้าและคุณสมบัติสั้นๆ ให้จบในฟิลด์ "caption"
ตัวอย่าง caption ที่ถูกต้อง: "{product_name}" หรือ "{product_name} แผ่นซิลิโคนระบายความร้อน"

ตอบกลับเป็น JSON สะอาด รูปแบบนี้เท่านั้น:
{{
  "product_name": "{product_name}",
  "total_estimated_seconds": {target_seconds},
  "script_sections": {{
{sections_json_format}
  }},
  "full_speech_text": "ข้อความพากย์ทั้งหมดเรียงต่อกันเป็นเนื้อเดียว",
  "caption": "ชื่อสินค้าและคุณสมบัติสั้นๆ ห้ามมีคำโปรยขายของ",
  "hashtags": ["#แท็ก1", "#แท็ก2", "#แท็ก3", "#แท็ก4"]
}}"""


def get_video_duration(video_path: str) -> float:
    """วัดความยาววิดีโอจริงเป็นวินาทีด้วย FFprobe (รองรับภาษาไทย UTF-8)"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        output = subprocess.check_output(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL
        ).strip()
        return float(output)
    except Exception as e:
        print(f"  [FFprobe Warning] ไม่สามารถอ่านความยาววิดีโอ ({e}) -> ใช้ค่าเริ่มต้น 24.0s")
        return 24.0


def _build_adaptive_prompt(product_name: str, duration: float) -> tuple[str, list[str]]:
    """คำนวณโควตาตัวอักษรและเลือกโครงสร้างจิตวิทยาตามความยาวคลิป"""
    usable_seconds = max(8.0, duration - 2.0)

    if usable_seconds < 16.0:
        target_sec = int(usable_seconds)
        max_chars = int(target_sec * 9.5)
        min_chars = int(max_chars * 0.70)
        mode_title = "Fast Hook & Sizzle (คลิปสั้นมาก กระชับ จบไว)"
        structure = (
            "1. hook: ประโยคเปิดสกัดนิ้ว 0-2 วินาที ด้วย Pain point หรือคำเตือน\n"
            "2. point_1: ขยี้ผลลัพธ์ความสะดวก/จุดเด่นที่เห็นชัดที่สุดในวิดีโอ 1 ข้อ\n"
            "3. cta: ปิดด้วย Yes-Yes CTA ชวนกดดูโปรโมชั่นในตะกร้าทันที"
        )
        sections_format = '    "hook": "...",\n    "point_1": "...",\n    "cta": "..."'
        required_keys = ["hook", "point_1", "cta"]

    elif usable_seconds <= 26.0:
        target_sec = int(usable_seconds)
        max_chars = int(target_sec * 10.0)
        min_chars = int(max_chars * 0.75)
        mode_title = "Benefit & Comparison (คลิปความยาวปานกลาง เจาะลึกความคุ้มค่า)"
        structure = (
            "1. hook: ประโยคเปิดท้าทายหรือชวนสงสัย\n"
            "2. point_1: จุดเด่นที่ 1 แก้ปัญหาอะไรจากภาพที่เห็นบนจอ\n"
            "3. point_2: จุดเด่นที่ 2 ชี้ให้เห็นความคุ้มค่าหรือความสะดวกที่ได้เพิ่ม\n"
            "4. cta: ชวนกดเข้าไปเทียบรุ่น/เช็คสีในตะกร้า"
        )
        sections_format = '    "hook": "...",\n    "point_1": "...",\n    "point_2": "...",\n    "cta": "..."'
        required_keys = ["hook", "point_1", "point_2", "cta"]

    else:
        target_sec = min(28, int(usable_seconds))
        max_chars = int(target_sec * 10.5)
        min_chars = int(max_chars * 0.80)
        mode_title = "Full Sales Story (คลิปยาว รีวิวครบเครื่อง 3 ข้อเด่น)"
        structure = (
            "1. hook: เปิดประโยคจับกลุ่มเป้าหมายให้อยู่หมัด\n"
            "2. point_1: ข้อที่ 1 ผลลัพธ์แรกที่ได้ทันทีหลังใช้งาน\n"
            "3. point_2: ข้อที่ 2 ฟังก์ชันเด่นที่ทำให้ชีวิตง่ายขึ้น (อิงจากภาพวิดีโอ)\n"
            "4. point_3: ข้อที่ 3 หมัดฮุกตอกย้ำว่าทำไมถึงคุ้มกว่าตัวอื่น\n"
            "5. cta: ปิดด้วย Yes-Yes CTA แนะนำให้รีบเช็คสต็อก/โค้ดลดในตะกร้า"
        )
        sections_format = '    "hook": "...",\n    "point_1": "...",\n    "point_2": "...",\n    "point_3": "...",\n    "cta": "..."'
        required_keys = ["hook", "point_1", "point_2", "point_3", "cta"]

    prompt = _PROMPT_TEMPLATE.format(
        product_name=product_name,
        mode_title=mode_title,
        target_seconds=target_sec,
        min_chars=min_chars,
        max_chars=max_chars,
        structure_instructions=structure,
        sections_json_format=sections_format,
    )
    return prompt, required_keys


def _wait_until_processed(client, video_file) -> None:
    poll_interval = 3
    max_wait = 180
    waited = 0
    while video_file.state.name == "PROCESSING":
        if waited >= max_wait:
            raise TimeoutError(f"Gemini ประมวลผลวิดีโอนานเกิน {max_wait} วินาที")
        time.sleep(poll_interval)
        waited += poll_interval
        video_file = client.files.get(name=video_file.name)
    if video_file.state.name != "ACTIVE":
        raise RuntimeError(f"วิดีโอไม่พร้อมใช้งานใน Gemini: state={video_file.state.name}")


def generate_sales_script(video_path: str, product_name: str) -> dict:
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    duration = get_video_duration(video_path)
    prompt, required_sections = _build_adaptive_prompt(product_name, duration)

    print(f"  [Gemini] ความยาววิดีโอ: {duration:.1f}s | อัปโหลดเข้าสู่โมเดล...")

    # ป้องกันภาษาไทยในชื่อไฟล์หลุดเข้าไปใน HTTP Header ของ Google GenAI
    upload_path = video_path
    temp_link = None
    try:
        Path(video_path).name.encode("ascii")
    except UnicodeEncodeError:
        temp_link = Path(config.BASE_DIR) / "temp_gemini_upload.mp4"
        if temp_link.exists() or temp_link.is_symlink():
            temp_link.unlink(missing_ok=True)
        try:
            os.symlink(Path(video_path).resolve(), temp_link)
        except OSError:
            shutil.copyfile(video_path, temp_link)
        upload_path = str(temp_link)

    try:
        video_file = client.files.upload(
            file=upload_path,
            config=types.UploadFileConfig(display_name="input_video.mp4")
        )
    finally:
        if temp_link and (temp_link.exists() or temp_link.is_symlink()):
            try:
                temp_link.unlink(missing_ok=True)
            except OSError:
                pass

    _wait_until_processed(client, video_file)
    print("  [Gemini] วิเคราะห์ภาพวิดีโอและวางโครงสร้างจิตวิทยาการขาย...")

    models_to_try = [config.GEMINI_MODEL_ID]
    for fallback in ("gemini-2.5-flash", "gemini-1.5-flash"):
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    data = None
    last_error = None
    for attempt, model_id in enumerate(models_to_try):
        if attempt > 0:
            print(f"  [Gemini] สลับไปใช้โมเดลสำรอง: {model_id} ...")
        for retry in range(4):
            try:
                # ปิด thinking_budget เพื่อเพิ่มความเร็วสูงสุด ตอบกลับทันที
                gen_config = types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    temperature=0.35,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )

                response = client.models.generate_content(
                    model=model_id,
                    contents=[prompt, video_file],
                    config=gen_config,
                )
                data = _parse_json(response.text)
                break
            except genai_errors.APIError as e:
                last_error = e
                status = getattr(e, "code", None)
                if status == 404:
                    break
                if status in (429, 500, 503, 504):
                    wait = 5 * (2 ** retry)
                    print(f"  [Gemini] HTTP {status} รอ {wait}s ({retry + 1}/4)...")
                    time.sleep(wait)
                    continue
                raise
        if data is not None:
            break

    if data is None:
        raise RuntimeError(f"Gemini ไม่สามารถสร้างสคริปต์ได้: {last_error}")

    # Fallback ป้องกันคีย์ตกหล่น
    if "full_speech_text" not in data or not data["full_speech_text"]:
        sections = data.get("script_sections", {})
        data["full_speech_text"] = " ".join(str(v).strip() for v in sections.values() if v)

    if "caption" not in data or not data["caption"]:
        data["caption"] = product_name

    if "hashtags" not in data or not data["hashtags"]:
        clean_name = re.sub(r"\s+", "", product_name)
        data["hashtags"] = [f"#{clean_name}", "#ของดีบอกต่อ", "#พิกัดในตะกร้า"]

    script_sections = data.setdefault("script_sections", {})
    for sec in required_sections:
        script_sections.setdefault(sec, "")

    return normalise_caption_data(data)


def normalise_caption_data(data: dict) -> dict:
    caption = str(data.get("caption", "")).strip()
    
    # 1. ตัดคำโปรยขายของหรือสโลแกนที่มีเครื่องหมาย ! หรือคำโปรยทิ้ง
    clean_caption = re.split(r"[!|]", caption)[0].strip()
    clean_caption = " ".join(clean_caption.split())

    raw_hashtags = data.get("hashtags", [])
    if isinstance(raw_hashtags, str):
        raw_hashtags = raw_hashtags.split()

    hashtags = []
    seen = set()
    for raw_tag in raw_hashtags:
        tag = str(raw_tag).strip().strip(",;")
        if not tag:
            continue
        tag = "#" + tag.lstrip("#")
        if len(tag) >= 2 and not any(c.isspace() for c in tag) and tag.casefold() not in seen:
            hashtags.append(tag)
            seen.add(tag.casefold())

    if not hashtags:
        hashtags = ["#รีวิวของใช้", "#ของดีบอกต่อ", "#พิกัดในตะกร้า"]

    data["hashtags"] = hashtags[:5]
    data["caption"] = clean_caption or data.get("product_name", "รีวิวสินค้า")
    
    # 2. รวมเป็น 1 บรรทัดติดกัน คั่นด้วยเคาะเว้นวรรค 1 ช่อง (ไม่มี \n หรือขึ้นบรรทัดใหม่)
    data["social_caption"] = f"{data['caption']} " + " ".join(data["hashtags"])
    return data


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        match = decoder.raw_decode(text)
        return match[0]