# 🎬 AI Video Automation Pipeline: Gemini + ElevenLabs + CapCut
> แผนงานระบบผลิตคลิปสั้นรีวิวสินค้าอัตโนมัติ (AI Short-Form Factory) พร้อม Prompt สั่งงาน OpenCode

---

## 📌 1. ภาพรวมและเป้าหมายของระบบ (Executive Summary)

ระบบนี้เป็นการอัปเกรดเว็บแอป Python เดิม เพื่อเปลี่ยนกระบวนการผลิตคลิปสั้นขายสินค้า (Affiliate / TikTok / Shorts / Reels) ให้เป็นอัตโนมัติเกือบ 100% โดยลดขั้นตอนที่ต้องทำด้วยมือ และแก้ปัญหาเรื่องคุณภาพเสียงพากย์กับซับไตเติลภาษาไทยที่ไม่ตรงจังหวะ

### หัวใจสำคัญของสถาปัตยกรรม (Core Architecture):
1. **Gemini API (สมองวิเคราะห์ & สคริปต์):**
   * รับไฟล์วิดีโอดิบและดึงชื่อสินค้าจากชื่อไฟล์ (เช่น `ESP32 S3 RLCD 4.2.mp4`)
   * ดูภาพในวิดีโอเพื่อจับจุดเด่นสินค้า แล้วเขียนบทพากย์ภาษาไทยตาม **Template สูตรเดิมซ้ำๆ** (Hook ดึงดูด -> 3 จุดเด่นสั้นกระชับ -> CTA ชวนกดตะกร้า)
2. **ElevenLabs API (เสียงพากย์ระดับพรีเมียม & ซับเป๊ะ 100%):**
   * เปลี่ยนบทพูดเป็นเสียงพากย์ภาษาไทยที่มีพลัง ชวนซื้อ ไม่เป็นหุ่นยนต์
   * ใช้ฟังก์ชัน `convert_with_timestamps` ดึงเวลาของแต่ละคำ (Word-level timestamps) ออกมาโดยตรง ทำให้ได้จังหวะซับที่แม่นยำระดับมิลลิวินาทีโดยไม่ต้องพึ่งโมเดล Speech-to-Text มาแกะซ้ำ
3. **Thai Subtitle Engine (ตัดคำไทยไม่ฉีก):**
   * ใช้ `PyThaiNLP` รวมกลุ่มคำสั้นๆ แสดงผลบนจอทีละ 2–4 คำ (Micro-chunking) ไม่ขึ้นยาวเป็นพรืด และไม่มีปัญหาคำฉีกกลางพยางค์
4. **Timeline & Trim Engine (เนื้อหาครบ จบงานทันที):**
   * ปิดเสียงวิดีโอต้นฉบับ วางแทร็กเสียงพากย์และซับไตเติล
   * **การจัดการความยาวคลิป:** เสียงพากย์พูดจบเมื่อไหร่ ถือว่าเนื้อหาครบ ไม่ต้องฝืนพากย์จนจบคลิปดิบ ระบบจะทำการตัดส่วนท้ายที่เกินออกให้อัตโนมัติ (Auto-Trim) หรือส่งเข้าโปรเจกต์ CapCut Desktop เพื่อให้ตรวจงานและ Export ได้ทันที

---

## 🗺️ 2. แผนงานการพัฒนาระบบ 5 ระยะ (Step-by-Step Roadmap)

| ระยะ (Phase) | รายละเอียดงาน | ผลลัพธ์ที่ได้ (Deliverable) |
| :--- | :--- | :--- |
| **Phase 1: Gemini Script Engine** | ปรับ Prompt ให้ Gemini คืนค่าบทพากย์ตามโครงสร้างตายตัว (Hook -> 3 ข้อ -> CTA) ในรูปแบบ Clean JSON พร้อมตรวจสอบความยาวให้อยู่ในช่วง 20–35 วินาที | โมดูลสร้างสคริปต์ที่ได้ข้อความภาษาไทยพร้อมส่งต่อ |
| **Phase 2: ElevenLabs Voice & Timestamps** | เขียนฟังก์ชันเชื่อมต่อ `elevenlabs.client` เรียกใช้ `convert_with_timestamps` บันทึกไฟล์เสียง `.mp3` และสกัดโครงสร้างเวลาเริ่มต้น-สิ้นสุดของแต่ละคำ | ไฟล์เสียงพากย์ + ข้อมูลเวลาของคำพูด (Alignment Data) |
| **Phase 3: Subtitle Tokenizer & Styler** | ใช้ `PyThaiNLP` นำคำพูดและ Timestamp มาจับกลุ่มทำเป็นซับไตเติลสั้นแบบคาราโอเกะ (เด้งทีละคำ/ไฮไลต์สี) | ไฟล์ซับไตเติล `.srt` หรือโครงสร้าง Text Track สำหรับ CapCut |
| **Phase 4: Video Sync & Trim Handler** | เขียนลอจิกคำนวณ: วิดีโอต้นฉบับถูก Mute เสียงเดิม -> วางเสียง ElevenLabs -> ตรวจสอบจุดสิ้นสุดของเสียงพากย์ (`Audio Duration + Padding 1s`) -> สั่งตัดส่วนท้ายคลิปออก หรือประกอบร่างเป็น CapCut Draft | คลิปที่ตัดต่อเสร็จ หรือโฟลเดอร์ Draft ของ CapCut ที่เปิดตรวจงานได้ทันที |
| **Phase 5: Web UI & Batch Queue** | อัปเกรดหน้าเว็บเดิม เพิ่มช่องกรอก ElevenLabs API Key, เมนูเลือกเสียงพากย์ และปุ่มสร้างงานทีละหลายคลิป (Batch Mode) | หน้าเว็บที่ลากไฟล์วิดีโอหลายตัวมาวาง แล้วกดรันจบในลูปเดียว |

---

## 💻 3. ข้อมูลทางเทคนิคที่เกี่ยวข้อง (Technical Specifications)

### A. ตัวอย่าง JSON โครงสร้างสคริปต์จาก Gemini:
```json
{
  "product_name": "ESP32 S3 RLCD 4.2",
  "total_estimated_seconds": 25,
  "script_sections": {
    "hook": "เฮ้ย นี่คือ 3 ข้อที่ทำให้รู้ว่าบอร์ดนี้เหมาะกับใคร ถ้าไม่ตรงไม่ต้องซื้อ",
    "point_1": "ข้อ 1 ออกแดดแล้วจอมืด ตัวนี้เป็น RLCD ยิ่งแดดจัดยิ่งสว่างชัดเจน",
    "point_2": "ข้อ 2 เซ็งแบตหมดไว ตัวนี้กินไฟต่ำมาก แบตก้อนเดียวเปิดทิ้งไว้ข้ามเดือน",
    "point_3": "ข้อ 3 บอร์ดเดิมอืด ตัวนี้ใส่ชิป ESP32-S3 ตัวท็อป ประมวลผลไวสะใจ",
    "cta": "ถ้าชอบ กดดูที่ตะกร้าด้านล่างได้เลยครับ"
  },
  "full_speech_text": "เฮ้ย นี่คือ 3 ข้อที่ทำให้รู้ว่าบอร์ดนี้เหมาะกับใคร ถ้าไม่ตรงไม่ต้องซื้อ ข้อ 1 ออกแดดแล้วจอมืด ตัวนี้เป็น RLCD ยิ่งแดดจัดยิ่งสว่างชัดเจน ข้อ 2 เซ็งแบตหมดไว ตัวนี้กินไฟต่ำมาก แบตก้อนเดียวเปิดทิ้งไว้ข้ามเดือน ข้อ 3 บอร์ดเดิมอืด ตัวนี้ใส่ชิป ESP32-S3 ตัวท็อป ประมวลผลไวสะใจ ถ้าชอบ กดดูที่ตะกร้าด้านล่างได้เลยครับ"
}
```

### B. โค้ดหลักฝั่ง ElevenLabs สำหรับดึงเสียงและ Timestamp:
```python
from elevenlabs.client import ElevenLabs

def generate_voice_with_alignment(api_key: str, text: str, voice_id: str):
    client = ElevenLabs(api_key=api_key)
    response = client.text_to_speech.convert_with_timestamps(
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        text=text
    )
    # response.audio_base64: ข้อมูลไฟล์เสียง
    # response.alignment: มี characters, character_start_times_seconds, character_end_times_seconds
    return response
```

### C. โค้ด Thai Subtitle Chunks + CapCut Injector:
```python
import json
import os
import shutil
from pythainlp import word_tokenize

def create_thai_chunks_with_timing(alignment_data, max_words=3):
    """
    จับคู่เวลาของตัวอักษรจาก ElevenLabs เข้ากับกลุ่มคำภาษาไทยผ่าน PyThaiNLP
    เพื่อป้องกันปัญหาคำฉีกกลางพยางค์ และแสดงผลทีละ 2-4 คำ (Micro-chunking)
    """
    full_text = "".join(alignment_data.characters)
    words = word_tokenize(full_text, engine="newmm")

    char_starts = alignment_data.character_start_times_seconds
    char_ends = alignment_data.character_end_times_seconds

    chunks = []
    current_words = []
    char_idx = 0

    for word in words:
        if not word.strip():
            char_idx += len(word)
            continue

        start_char = char_idx
        end_char = char_idx + len(word) - 1

        # ดึงเวลาเริ่มต้นและสิ้นสุดของคำ
        w_start = char_starts[start_char]
        w_end = char_ends[end_char]

        current_words.append({"word": word, "start": w_start, "end": w_end})
        char_idx += len(word)

        # รวมกลุ่มคำเมื่อครบจำนวนที่กำหนด
        if len(current_words) >= max_words:
            chunk_text = "".join([item["word"] for item in current_words])
            chunk_start = current_words[0]["start"]
            chunk_end = current_words[-1]["end"]
            chunks.append({
                "text": chunk_text,
                "start_time": chunk_start,
                "end_time": chunk_end
            })
            current_words = []

    # เก็บคำตกค้างรอบสุดท้าย
    if current_words:
        chunk_text = "".join([item["word"] for item in current_words])
        chunks.append({
            "text": chunk_text,
            "start_time": current_words[0]["start"],
            "end_time": current_words[-1]["end"]
        })

    return chunks


def inject_to_capcut(project_name, raw_video_path, voice_audio_path, subtitles, capcut_draft_dir):
    """
    สร้างโปรเจกต์ใหม่ใน CapCut Desktop โดยโคลนจาก Master Template
    และอัปเดตพาธวิดีโอ (Mute), เสียงพากย์, และแทร็กซับไตเติล
    """
    target_project_dir = os.path.join(capcut_draft_dir, project_name)
    template_dir = os.path.join(os.path.dirname(__file__), "templates", "capcut_master")

    # 1. โคลนโครงสร้างโฟลเดอร์โปรเจกต์
    if not os.path.exists(target_project_dir):
        shutil.copytree(template_dir, target_project_dir)

    draft_json_path = os.path.join(target_project_dir, "draft_content.json")
    with open(draft_json_path, "r", encoding="utf-8") as f:
        draft = json.load(f)

    # 2. ปรับแต่ง Metadata และไทม์ไลน์
    # - Mute เสียงวิดีโอต้นฉบับ
    # - ยัดพาธ voice_audio_path ลงใน Audio Track
    # - นำรายการ subtitles ไปสร้างเป็น Text Segments ตามสไตล์ที่เซฟไว้ใน Template

    with open(draft_json_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    print(f"✅ Inject ข้อมูลเข้า CapCut สำเร็จ: {project_name}")
```

---

## 🤖 4. Prompt สั่งงาน OpenCode (สำเร็จรูป — คัดลอกไปใช้ได้เลย)

```text
คุณคือ Senior Full-Stack Python & AI Media Automation Engineer
หน้าที่ของคุณคือช่วยฉันพัฒนาต่อยอดระบบ "เว็บแอปผลิตคลิปสั้นรีวิวสินค้าอัตโนมัติ" (Short-form Video Generator)

=== บริบทและระบบเดิมของฉัน ===
1. ปัจจุบันฉันมีเว็บแอปภาษา Python ที่ผู้ใช้สามารถโยนไฟล์วิดีโอดิบเข้าไปได้ โดยฉันจะตั้งชื่อไฟล์วิดีโอเป็นชื่อสินค้าล่วงหน้า (เช่น "ESP32 S3 RLCD 4.2.mp4")
2. ระบบเดิมใช้ Gemini API อ่านคลิปและดึงชื่อสินค้าจากชื่อไฟล์ เพื่อเขียนสคริปต์พากย์ขายสินค้าตามโครงสร้างเดิมซ้ำๆ (Hook -> 3 จุดเด่นสินค้า -> Call to Action สั้นๆ)
3. ปัญหาปัจจุบันคือ: การทำซับไตเติลยังทำได้ไม่ดี (คำฉีกกลางพยางค์ และจังหวะไม่ตรง) และต้องการยกระดับเสียงพากย์ให้มีคุณภาพสูงและน่าซื้อมากขึ้น

=== สถาปัตยกรรมและ Workflow ใหม่ที่ต้องการพัฒนา ===
1. [Gemini as the Brain]: 
   - รับไฟล์วิดีโอดิบ + ชื่อสินค้าจากชื่อไฟล์
   - สร้างสคริปต์ตาม Template โครงสร้างตายตัว ควบคุมความยาวให้อยู่ระหว่าง 20-35 วินาที ส่งออกเป็น JSON สะอาด
2. [ElevenLabs as Voice & Timestamps]: 
   - นำสคริปต์จาก Gemini ส่งไปเข้า ElevenLabs API โดยใช้ฟังก์ชัน convert_with_timestamps (โมเดล eleven_multilingual_v2)
   - บันทึกไฟล์เสียงพากย์ (.mp3)
   - ใช้ข้อมูล Alignment ที่ ElevenLabs ส่งกลับมา นำมาสร้างเป็น Timestamp ระดับคำ
3. [Thai Karaoke Subtitle Engine]:
   - ใช้ PyThaiNLP ในการตัดคำและจัดกลุ่มคำสั้นๆ บนหน้าจอ (Micro-chunking ละ 2-4 คำ) เพื่อไม่ให้คำไทยถูกหั่นกลางพยางค์
   - ผูกจังหวะเวลาของคำเข้ากับเวลาจริงที่ได้จาก ElevenLabs เพื่อทำซับสไตล์คาราโอเกะ (เด้งทีละคำ / เปลี่ยนสี)
4. [Video Sync & Trimming Logic]:
   - ปิดเสียง (Mute) ของวิดีโอต้นฉบับ
   - วางเสียงพากย์และซับไตเติลลงบนวิดีโอ
   - เงื่อนไขสำคัญ: "เนื้อหาครบก็จบเลย ไม่ต้องพากย์จนเต็มวิดีโอ"
     ถ้าวิดีโอต้นฉบับยาว 1 นาที แต่เสียงพากย์ยาวแค่ 25 วินาที ระบบต้องสามารถ:
     - ทางเลือก A: สั่งตัดส่วนท้ายวิดีโอที่เกินออกอัตโนมัติ (Cut at Audio End + 1.0s padding)
     - ทางเลือก B: จัดเตรียมเป็นโปรเจกต์ CapCut Desktop (draft_content.json) เพื่อให้เปิดโปรแกรมขึ้นมาตรวจงานและกดตัด/Export ได้ทันที

=== คำสั่งและข้อกำหนดก่อนเริ่มงาน (สำคัญมาก!) ===
ก่อนที่คุณจะเริ่มเขียนโค้ด ให้คุณทำสิ่งต่อไปนี้ก่อนเสมอ:
1. วิเคราะห์ Workflow ที่ฉันอธิบายด้านบน และสรุปความเข้าใจสั้นๆ ให้ตรงกัน
2. เสนอไอเดียที่ดีกว่า หรือข้อเสนอแนะเชิงเทคนิคที่น่าสนใจ 3-5 ข้อ (เช่น การจัดการเรื่องต้นทุน API, การเร่งความเร็วในการตัดต่อ, ฟีเจอร์ใส่ Sound Effect/เสียงหวือตามจังหวะข้อ 1-2-3 อัตโนมัติ, หรือการจัดวาง Layout ใน CapCut ให้สวยงามที่สุด)
3. ร่างโครงสร้างไฟล์และโมดูล (Project Structure) ที่คุณจะสร้างหรือแก้ไขในโปรเจกต์นี้
4. รอให้ฉันอนุมัติหรือเลือกไอเดียที่คุณเสนอก่อน แล้วจึงค่อยเริ่มลงมือเขียนโค้ดทีละขั้นตอน
```