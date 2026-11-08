import hashlib
import html
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from services import pipeline_service, product_service

st.set_page_config(
    page_title="AI Video Editor",
    page_icon=":material/movie:",
    layout="wide",
)

st.session_state.setdefault("ui_settings", pipeline_service.load_ui_settings())
st.session_state.setdefault("latest_results", [])
st.session_state.setdefault("gemini_api_key_input", "")
st.session_state.setdefault("elevenlabs_api_key_input", "")
st.session_state.setdefault("api_key_notice", "")
st.session_state.setdefault("pending_gemini_api_key", "")
st.session_state.setdefault("pending_elevenlabs_api_key", "")

_STAGES = ["script", "voice", "subtitle", "render", "capcut", "complete"]


# ==============================================================================
# Helper Functions สำหรับ Caption และ ปุ่มคัดลอกบน HTTP LAN
# ==============================================================================
def clean_single_line_caption(caption_text: str) -> str:
    """แปลง Caption ให้เป็นบรรทัดเดียว ตัดสโลแกนขายของ และไม่เว้นบรรทัด"""
    if not caption_text:
        return ""
    text = str(caption_text).strip()
    hashtags = re.findall(r"#[A-Za-z0-9_\u0E00-\u0E7F]+", text)
    title_part = re.sub(r"#[A-Za-z0-9_\u0E00-\u0E7F]+", "", text).strip()
    title_part = re.split(r"[!|]", title_part)[0].strip()
    title_part = re.split(r"\s+(?:กู้ชีพ|ลดจัด|ตัวตึง|ห้ามพลาด|ของดี|ไอเทม)", title_part)[0].strip()
    title_part = " ".join(title_part.split())
    tags_part = " ".join(hashtags)
    if tags_part:
        full_caption = f"{title_part} {tags_part}".strip()
    else:
        full_caption = title_part
    return " ".join(full_caption.split())


def render_copy_box(label: str, text_to_copy: str, element_id: str):
    """แสดงกล่องข้อความพร้อมปุ่มคัดลอกที่ทำงานได้ 100% บน HTTP วงแลน"""
    escaped_text = html.escape(str(text_to_copy))
    escaped_label = html.escape(str(label))

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
      body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #fafafa;
        overflow: hidden;
      }}
      .copy-card {{
        background-color: #1e212b;
        border: 1px solid #313543;
        border-radius: 6px;
        padding: 6px 10px;
        box-sizing: border-box;
      }}
      .card-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
      }}
      .card-label {{
        font-size: 12px;
        font-weight: 500;
        color: #9aa0a6;
      }}
      .btn-group {{
        display: flex;
        align-items: center;
        gap: 6px;
      }}
      .status-text {{
        color: #4ade80;
        font-size: 11px;
        display: none;
        font-weight: bold;
      }}
      .btn-copy {{
        background-color: #262730;
        color: #ffffff;
        border: 1px solid #4a4a5a;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 11px;
        cursor: pointer;
        transition: all 0.2s;
      }}
      .btn-copy:hover {{
        background-color: #3b3e4f;
        border-color: #70758f;
      }}
      .btn-copy:active {{
        transform: scale(0.96);
      }}
      .text-area {{
        width: 100%;
        height: 48px;
        background: transparent;
        color: #e8eaed;
        border: none;
        outline: none;
        font-size: 12px;
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        resize: none;
        line-height: 1.35;
        box-sizing: border-box;
        padding: 0;
        word-break: break-all;
      }}
    </style>
    </head>
    <body>
      <div class="copy-card">
        <div class="card-header">
          <span class="card-label">{escaped_label}</span>
          <div class="btn-group">
            <span id="msg_{element_id}" class="status-text">คัดลอกสำเร็จ!</span>
            <button id="btn_{element_id}" class="btn-copy" title="คัดลอก">⧉</button>
          </div>
        </div>
        <textarea id="ta_{element_id}" class="text-area" readonly>{escaped_text}</textarea>
      </div>

      <script>
        document.getElementById("btn_{element_id}").onclick = function() {{
          var ta = document.getElementById("ta_{element_id}");
          ta.select();
          ta.setSelectionRange(0, 99999);
          try {{
            var ok = document.execCommand('copy');
            if (ok) {{
              showSuccess();
              return;
            }}
          }} catch (err) {{}}

          if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(ta.value).then(showSuccess).catch(function() {{}});
          }}
        }};

        function showSuccess() {{
          var msg = document.getElementById("msg_{element_id}");
          msg.style.display = "inline";
          setTimeout(function() {{
            msg.style.display = "none";
          }}, 2000);
        }}
      </script>
    </body>
    </html>
    """
    components.html(html_code, height=92)


def capture_api_key_inputs() -> None:
    st.session_state.pending_gemini_api_key = st.session_state.gemini_api_key_input
    st.session_state.pending_elevenlabs_api_key = st.session_state.elevenlabs_api_key_input
    st.session_state.gemini_api_key_input = ""
    st.session_state.elevenlabs_api_key_input = ""


# ==============================================================================
# 1. หน้าสร้างวิดีโอ (รองรับ Pre-staging + Hybrid Batch Mapping Queue)
# ==============================================================================
def create_page() -> None:
    st.title("สร้างวิดีโอ", icon=":material/movie:")
    st.caption("ระบบ Hybrid: เตรียมชื่อและลิงก์ล่วงหน้า แล้วสั่งจับคู่ทำวิดีโอต่อเนื่องได้ไม่จำกัด")

    # ส่วนที่ 1: บันทึกสินค้าและลิงก์ล่วงหน้า (Pre-stage Products)
    with st.expander("📦 เพิ่มสินค้าและลิงก์ล่วงหน้า (บันทึกไว้รอคลิปวิดีโอ)", expanded=False):
        c_p1, c_p2, c_p3 = st.columns([3, 4, 1.5], vertical_alignment="bottom")
        with c_p1:
            pre_name = st.text_input("ชื่อสินค้า", placeholder="เช่น ถ่านชาร์จกระดุม LIR2032", key="pre_prod_name")
        with c_p2:
            pre_link = st.text_input("ลิงก์ตะกร้า Shopee/TikTok", placeholder="https://s.shopee.co.th/...", key="pre_prod_link")
        with c_p3:
            if st.button("บันทึกสินค้า", icon=":material/add_circle:", type="primary", use_container_width=True):
                if pre_name.strip():
                    try:
                        product_service.add_pre_staged_product(pre_name.strip(), pre_link.strip())
                        st.toast(f"บันทึก {pre_name.strip()} เรียบร้อยแล้ว")
                        st.rerun()
                    except Exception as err:
                        st.error(str(err))
                else:
                    st.warning("กรุณาระบุชื่อสินค้า")

    # แถบจัดการและลบไฟล์วิดีโอดิบใน input_videos
    with st.expander("📁 จัดการไฟล์วิดีโอดิบใน input_videos (ลบไฟล์เก่าเพื่อคืนพื้นที่)"):
        input_files = pipeline_service.list_input_videos()
        if not input_files:
            st.caption("ไม่มีไฟล์ใน input_videos")
        else:
            for v_file in input_files:
                col_name, col_btn = st.columns([4, 1])
                with col_name:
                    st.write(f"📄 `{v_file.name}` ({format_size(v_file.stat().st_size)})")
                with col_btn:
                    if st.button("ลบไฟล์ดิบ", key=f"del_raw_{v_file.name}", icon=":material/delete:"):
                        try:
                            v_file.unlink()
                            st.toast(f"ลบ {v_file.name} สำเร็จ")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ ไม่สามารถลบได้: {str(e)}")

    missing_keys = [key for key in config.REQUIRED_KEYS if not getattr(config, key, "")]
    if missing_keys:
        st.warning("ยังใช้ Gemini/ElevenLabs ไม่ได้: ขาด " + ", ".join(missing_keys), icon=":material/key_off:")

    # ส่วนที่ 2: เลือกและอัปโหลดวิดีโอ
    videos = pipeline_service.list_input_videos()
    video_options = [str(path) for path in videos]
    
    col_sel, col_upl = st.columns([1, 1])
    with col_sel:
        selected = st.multiselect(
            "เลือกวิดีโอจาก input_videos",
            video_options,
            format_func=lambda value: Path(value).name,
            placeholder="เลือกวิดีโอได้หลายไฟล์พร้อมกัน",
        )
    with col_upl:
        uploaded = st.file_uploader(
            "หรืออัปโหลดวิดีโอใหม่",
            type=sorted(extension.lstrip(".") for extension in pipeline_service.VIDEO_EXTENSIONS),
            accept_multiple_files=True,
        )

    # รวมไฟล์ทั้งหมดที่ถูกเลือก/อัปโหลด
    all_queue_paths = [Path(path) for path in selected]
    if uploaded:
        try:
            saved_new = pipeline_service.save_uploaded_videos(uploaded)
            for p in saved_new:
                if p not in all_queue_paths:
                    all_queue_paths.append(p)
        except Exception as e:
            st.error(f"อัปโหลดไฟล์ล้มเหลว: {e}")

    # ดึงคลังชื่อสินค้าเพื่อใช้ใน Dropdown
    db_product_names = product_service.get_all_product_names()
    dropdown_options = ["(กำหนดชื่อเอง / ตามชื่อไฟล์)"] + db_product_names

    batch_tasks = []

    # ส่วนที่ 3: ตารางจัดคิวและจับคู่สินค้า (Batch Mapping Section)
    if all_queue_paths:
        st.subheader("📋 จัดคิวและจับคู่สินค้าสำหรับวิดีโอ (Batch Matching)", icon=":material/checklist:")
        st.caption("ระบบตรวจจับคู่ชื่อสินค้าให้อัตโนมัติ คุณสามารถเลือกหรือแก้ไขชื่อและลิงก์ของแต่ละคลิปได้อิสระ")

        for idx, v_path in enumerate(all_queue_paths):
            f_name = v_path.name
            safe_k = hashlib.md5(f_name.encode("utf-8")).hexdigest()[:6]

            # ค้นหา Auto-Match
            auto_p_name, auto_p_link = product_service.match_product_from_filename(f_name)

            with st.container(border=True):
                c_lbl, c_drop, c_name, c_link = st.columns([2.5, 2.5, 2.5, 3.5], vertical_alignment="bottom")
                
                with c_lbl:
                    st.markdown(f"**คลิปที่ {idx + 1}:** `{f_name}`")
                    st.caption(f"ขนาด: {format_size(v_path.stat().st_size)}")

                with c_drop:
                    default_drop_idx = 0
                    if auto_p_name in db_product_names:
                        default_drop_idx = db_product_names.index(auto_p_name) + 1
                    
                    selected_prod_drop = st.selectbox(
                        "เลือกจากสินค้าในคลัง",
                        dropdown_options,
                        index=default_drop_idx,
                        key=f"drop_{safe_k}_{idx}",
                    )

                with c_name:
                    # ถ้าเลือกจาก Dropdown ให้ใช้ค่านั้น ถ้าไม่ ให้ใช้ auto_p_name
                    init_name = selected_prod_drop if selected_prod_drop != "(กำหนดชื่อเอง / ตามชื่อไฟล์)" else auto_p_name
                    task_name = st.text_input(
                        "ชื่อสินค้าสำหรับพากย์",
                        value=init_name,
                        key=f"pname_{safe_k}_{idx}",
                    )

                with c_link:
                    # ดึงลิงก์อัตโนมัติของตัวที่เลือก
                    init_link = product_service.get_product_link(task_name) if task_name in db_product_names else auto_p_link
                    task_link = st.text_input(
                        "ลิงก์ตะกร้าสินค้า",
                        value=init_link,
                        placeholder="https://s.shopee.co.th/...",
                        key=f"plink_{safe_k}_{idx}",
                    )

                batch_tasks.append({
                    "video_path": str(v_path),
                    "product_name": task_name.strip() or v_path.stem,
                    "product_link": task_link.strip(),
                })

    # ส่วนที่ 4: ตั้งค่าและสั่งเริ่มประมวลผล
    current = st.session_state.ui_settings
    with st.expander("ตั้งค่าเสียงและซับสำหรับรอบนี้", icon=":material/tune:"):
        voice_id = st.text_input("ElevenLabs Voice ID", value=current["voice_id"])
        color = st.color_picker("สีข้อความ", value=current["subtitle_color"])
        font_size = st.slider("ขนาดฟอนต์ (px)", 65, 80, int(current.get("font_size", 72)))
        subtitle_y = st.slider("ตำแหน่ง Y จากขอบบน (px)", 350, 500, int(current["subtitle_y"]))
        padding = st.slider("ระยะต่อท้าย (วินาที)", 0.0, 3.0, float(current["padding"]), step=0.1)

    can_start = bool(batch_tasks) and not missing_keys
    button_label = f"เริ่มสร้างวิดีโอต่อเนื่อง ({len(batch_tasks)} รายการ)" if batch_tasks else "เริ่มสร้างวิดีโอ"

    if st.button(button_label, icon=":material/play_arrow:", type="primary", disabled=not can_start):
        settings = {
            **current,
            "voice_id": voice_id.strip(),
            "subtitle_color": color,
            "font_size": font_size,
            "subtitle_y": subtitle_y,
            "padding": padding,
        }
        
        results, failures = [], []
        progress_bar = st.progress(0.0, text="เตรียมเริ่มคิวงาน...")
        
        with st.status(f"กำลังประมวลผลตามคิว {len(batch_tasks)} วิดีโอ", expanded=True) as status:
            for index, task in enumerate(batch_tasks):
                v_path = task["video_path"]
                p_name = task["product_name"]
                p_link = task["product_link"]
                
                st.write(f"🎬 **[{index + 1}/{len(batch_tasks)}] กำลังสร้าง: {p_name}**")

                def on_progress(stage, message, item_index=index):
                    stage_index = _STAGES.index(stage) if stage in _STAGES else 0
                    fraction = (item_index * len(_STAGES) + stage_index) / (len(batch_tasks) * len(_STAGES))
                    progress_bar.progress(min(fraction, 1.0), text=message)
                    st.write(f"└─ {message}")

                try:
                    result = pipeline_service.process_video(
                        v_path, p_name, settings,
                        product_link=p_link,
                        progress=on_progress
                    )
                    results.append(result)
                    st.success(f"✓ สำเร็จ: {p_name}", icon=":material/check_circle:")
                except Exception as exc:
                    failures.append((p_name, str(exc)))
                    st.error(f"✗ ล้มเหลว {p_name}: {exc}", icon=":material/error:")

            progress_bar.progress(1.0, text="ประมวลผลคิวเสร็จสิ้นทั้งหมดแล้ว")
            status.update(
                label=f"เสร็จสิ้น {len(results)} รายการ • ผิดพลาด {len(failures)} รายการ",
                state="complete" if not failures else "error",
                expanded=False,
            )
        st.session_state.latest_results = results

# ผลลัพธ์ล่าสุด
    if st.session_state.latest_results:
        st.subheader("ผลลัพธ์ล่าสุด", icon=":material/download:")
        for idx, result in enumerate(st.session_state.latest_results):
            with st.container(border=True):
                st.write(f"**{result['product_name']}**")
                download_button(result, f"latest_{idx}")
                cap_text = result.get("social_caption") or result.get("caption", "")
                if cap_text:
                    cleaned_cap = clean_single_line_caption(cap_text)
                    render_copy_box("Caption พร้อมคัดลอก:", cleaned_cap, f"latest_{idx}_{entry_key(result)}")


# ==============================================================================
# 2. หน้าคลังวิดีโอ (ดึงสินค้าทั้งหมด แม้มี 0 คลิป ก็แสดงกล่อง Expander ให้ทันที)
# ==============================================================================
def library_page() -> None:
    st.title("คลังวิดีโอแยกตามสินค้า", icon=":material/video_library:")

    entries = pipeline_service.scan_library()
    all_saved_products = product_service.load_products()

    # หากไม่มีทั้งคลิปวิดีโอและสินค้าในคลัง
    if not entries and not all_saved_products:
        st.info("ยังไม่มีสินค้าหรือวิดีโอในคลัง เริ่มสร้างจากหน้า “สร้างวิดีโอ”", icon=":material/video_file:")
        return

    # 1. จัดกลุ่มวิดีโอตามชื่อสินค้า
    grouped_products = defaultdict(list)
    for entry in entries:
        grouped_products[entry["product_name"]].append(entry)

    # 2. รวมสินค้าที่บันทึกไว้ล่วงหน้า แม้ยังไม่มีคลิปวิดีโอก็ให้สร้างกล่องรอไว้ (0 คลิป)
    for prod in all_saved_products:
        p_name = prod.get("name")
        if p_name and p_name not in grouped_products:
            grouped_products[p_name] = []

    # แถบควบคุมด้านบน: ค้นหา + ตัวกรอง + ปุ่มรีเฟรช
    col_search, col_filter, col_ref = st.columns([3, 2, 1], vertical_alignment="bottom")
    with col_search:
        search = st.text_input("ค้นหาสินค้า", placeholder="พิมพ์ชื่อสินค้าหรือรอบงาน...", label_visibility="collapsed")
    with col_filter:
        products_list = sorted(list(grouped_products.keys()))
        product_filter = st.selectbox("กรองตามสินค้า", ["ทั้งหมด"] + products_list, label_visibility="collapsed")
    with col_ref:
        if st.button("รีเฟรช", icon=":material/refresh:", use_container_width=True):
            st.rerun()

    # กรองรายการค้นหา
    filtered_groups = {}
    for p_name, p_entries in grouped_products.items():
        if product_filter != "ทั้งหมด" and p_name != product_filter:
            continue
        if search.strip():
            needle = search.strip().casefold()
            match_name = needle in p_name.casefold()
            matched_runs = [e for e in p_entries if needle in e["run_id"].casefold()]
            if not match_name and not matched_runs:
                continue
            if not match_name:
                p_entries = matched_runs
        filtered_groups[p_name] = p_entries

    total_clips = sum(len(items) for items in filtered_groups.values())
    st.caption(f"แสดง {len(filtered_groups)} รายการสินค้า • รวม {total_clips} วิดีโอ")

    # แสดงผลการ์ดสินค้าแบบ ย่อ/พับได้ (st.expander)
    for prod_name, prod_entries in filtered_groups.items():
        total_rev = len(prod_entries)
        
        # ดึงลิงก์จากคลิป หรือดึงจากประวัติสินค้าในคลัง
        latest_link = next((e["product_link"] for e in prod_entries if e.get("product_link")), "")
        if not latest_link:
            latest_link = product_service.get_product_link(prod_name)

        latest_cap = next((e["social_caption"] or e["caption"] for e in prod_entries if (e.get("social_caption") or e.get("caption"))), "")

        safe_id = hashlib.sha1(prod_name.encode("utf-8")).hexdigest()[:8]

        with st.expander(f"📦 **{prod_name}** ({total_rev} คลิป)", expanded=False):
            col_info, col_caption, col_del_prod = st.columns([2.5, 3.5, 1.2], vertical_alignment="top")

            with col_info:
                if latest_link:
                    clean_l = str(latest_link).strip()
                    render_copy_box("คัดลอกลิงก์ x2:", f"{clean_l}\n{clean_l}", f"link_{safe_id}")
                else:
                    st.caption("🛒 *ยังไม่มีการระบุลิงก์ตะกร้า*")

            with col_caption:
                if latest_cap:
                    single_caption = clean_single_line_caption(latest_cap)
                    render_copy_box("📌 Caption ล่าสุด:", single_caption, f"cap_{safe_id}")
                else:
                    st.caption("📝 *ยังไม่มี Caption (รอสร้างวิดีโอ)*")

            with col_del_prod:
                st.caption("จัดการสินค้า")
                if st.button("ลบสินค้านี้", key=f"del_all_{safe_id}", icon=":material/delete_forever:", type="primary", help="ลบโฟลเดอร์และข้อมูลของสินค้านี้"):
                    confirm_delete_entire_product(prod_name)

            st.divider()

            # หากยังไม่มีวิดีโอ ให้แสดงข้อความสถานะรอ
            if not prod_entries:
                st.info("⏳ สินค้านี้บันทึกเตรียมไว้แล้ว ยังไม่มีวิดีโอ (สามารถเลือกจับคู่และเริ่มสร้างได้ที่หน้า 'สร้างวิดีโอ')", icon=":material/pending:")
            else:
                # แสดงวิดีโอแบบ Grid 3 คอลัมน์
                grid_cols = st.columns(3)
                for idx, entry in enumerate(prod_entries):
                    key = entry_key(entry)
                    with grid_cols[idx % 3]:
                        with st.container(border=True):
                            st.video(entry["final_video"])
                            st.markdown(f"**รอบ:** `{entry['run_id']}`")
                            st.caption(f"{entry['created_at'][:16].replace('T', ' ')} • {float(entry['duration_seconds']):.1f}s")
                            
                            b_col1, b_col2, b_col3 = st.columns(3)
                            with b_col1:
                                download_button(entry, "lib_" + key)
                            with b_col2:
                                if entry.get("draft_dir") and Path(entry["draft_dir"]).is_dir():
                                    if st.button("CapCut", key=f"cc_{key}", icon=":material/draft:", use_container_width=True):
                                        open_folder(Path(entry["draft_dir"]))
                                else:
                                    if st.button("โฟลเดอร์", key=f"f_{key}", icon=":material/folder:", use_container_width=True):
                                        open_folder(Path(entry["run_dir"]))
                            with b_col3:
                                if st.button("ลบ", key=f"del_{key}", icon=":material/delete:", use_container_width=True):
                                    confirm_delete(entry)

                            with st.expander("ไฟล์เสริม (SRT/ASS)"):
                                extra_downloads(entry, key)


# ==============================================================================
# 3. หน้าตั้งค่าระบบ
# ==============================================================================
def settings_page() -> None:
    st.title("ตั้งค่า", icon=":material/settings:")
    st.caption("การตั้งค่าทั่วไปแยกจาก API Key และจะถูกบันทึกไว้ใช้ในรอบถัดไป")

    if st.session_state.api_key_notice:
        st.success(st.session_state.api_key_notice, icon=":material/check_circle:")
        st.session_state.api_key_notice = ""

    with st.container(border=True):
        st.subheader("เพิ่มหรือเปลี่ยน API Key", icon=":material/key:")
        service_status("Gemini API Key", bool(config.GEMINI_API_KEY))
        service_status("ElevenLabs API Key", bool(config.ELEVENLABS_API_KEY))
        with st.form("api_credentials_form"):
            st.text_input("Gemini API Key", type="password", key="gemini_api_key_input")
            st.text_input("ElevenLabs API Key", type="password", key="elevenlabs_api_key_input")
            if st.form_submit_button("บันทึก API Key", icon=":material/save:", type="primary", on_click=capture_api_key_inputs):
                try:
                    pipeline_service.save_api_credentials(
                        gemini_api_key=st.session_state.pending_gemini_api_key,
                        elevenlabs_api_key=st.session_state.pending_elevenlabs_api_key,
                    )
                    st.session_state.api_key_notice = "บันทึก Key เรียบร้อยแล้ว"
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    current = st.session_state.ui_settings
    with st.form("settings_form"):
        voice_id = st.text_input("ElevenLabs Voice ID", value=current["voice_id"])
        capcut_dir = st.text_input("CapCut Drafts", value=current["capcut_draft_dir"])
        color = st.color_picker("สีข้อความเริ่มต้น", value=current["subtitle_color"])
        font_size = st.slider("ขนาดฟอนต์เริ่มต้น (px)", 65, 80, int(current.get("font_size", 72)))
        subtitle_y = st.slider("ตำแหน่ง Y เริ่มต้น (px)", 350, 500, int(current["subtitle_y"]))
        padding = st.slider("ระยะต่อท้ายเริ่มต้น (วินาที)", 0.0, 3.0, float(current["padding"]), step=0.1)
        if st.form_submit_button("บันทึกการตั้งค่า", icon=":material/save:", type="primary"):
            settings = {
                "voice_id": voice_id.strip(),
                "capcut_draft_dir": capcut_dir.strip(),
                "subtitle_color": color,
                "font_size": font_size,
                "subtitle_y": subtitle_y,
                "padding": padding,
            }
            try:
                pipeline_service.save_ui_settings(settings)
                st.session_state.ui_settings = settings
                st.success("บันทึกการตั้งค่าแล้ว", icon=":material/check_circle:")
            except Exception as exc:
                st.error(str(exc))


# ==============================================================================
# Helper Dialogs & Actions
# ==============================================================================
@st.dialog("ยืนยันการลบสินค้าทั้งหมด", width="small")
def confirm_delete_entire_product(product_name: str) -> None:
    st.write(f"คุณต้องการลบสินค้า **{product_name}** และวิดีโอทั้งหมดที่เกี่ยวข้องหรือไม่?")
    st.caption("การกระทำนี้จะลบโฟลเดอร์งานทั้งหมดของสินค้านี้ใน `output/` อย่างถาวร")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("ยกเลิก", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("ยืนยันลบทั้งหมด", icon=":material/delete_forever:", type="primary", use_container_width=True):
            try:
                safe_p = pipeline_service._safe_name(product_name)
                target_dir = Path(config.OUTPUT_DIR) / safe_p
                if target_dir.is_dir():
                    shutil.rmtree(target_dir)

                try:
                    product_service.delete_product(product_name)
                except Exception:
                    pass

                st.toast(f"ลบ {product_name} สำเร็จ")
                st.rerun()
            except Exception as exc:
                st.error(f"ลบไม่สำเร็จ: {exc}")


@st.dialog("ยืนยันการลบรอบงาน", width="small")
def confirm_delete(entry: dict) -> None:
    st.write(f"ลบรอบ **{entry['run_id']}** หรือไม่?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("ยกเลิก", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("ยืนยันลบ", icon=":material/delete:", type="primary", use_container_width=True):
            try:
                pipeline_service.delete_run(entry["run_dir"])
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def download_button(entry: dict, prefix: str) -> None:
    path = Path(entry["final_video"])
    if not path.is_file():
        st.warning("ไม่พบไฟล์")
        return
    # เพิ่ม run_id หรือ hash เพื่อรับประกันว่า key จะไม่ซ้ำกันแน่นอน
    unique_suffix = entry.get("run_id") or entry_key(entry)
    st.download_button(
        "MP4",
        data=lambda: path.read_bytes(),
        file_name=f"{entry['product_name']}_{entry['run_id']}.mp4",
        mime="video/mp4",
        key=f"dl_{prefix}_{unique_suffix}",
        icon=":material/download:",
        use_container_width=True,
    )


def extra_downloads(entry: dict, key: str) -> None:
    run_dir = Path(entry["run_dir"])
    for filename, label, mime in [
        ("subtitles.srt", "SRT", "application/x-subrip"),
        ("subtitles_karaoke.ass", "ASS", "text/plain"),
        ("script.json", "Script", "application/json"),
    ]:
        path = run_dir / filename
        if path.is_file():
            st.download_button(
                label, data=lambda p=str(path): Path(p).read_bytes(),
                file_name=f"{entry['product_name']}_{entry['run_id']}_{filename}",
                mime=mime, key=f"extra_{key}_{filename}",
                use_container_width=True,
            )


def open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path.resolve()))
        else:
            st.write(f"พาธ: {path}")
        st.toast("เปิดโฟลเดอร์แล้ว", icon=":material/folder_open:")
    except Exception as exc:
        st.error(str(exc))


def service_status(label: str, ready: bool) -> None:
    if ready:
        st.badge(f"{label} พร้อม", icon=":material/check_circle:", color="green")
    else:
        st.badge(f"{label} ไม่พร้อม", icon=":material/error:", color="red")


def entry_key(entry: dict) -> str:
    return hashlib.sha1(entry["final_video"].encode("utf-8")).hexdigest()[:12]


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


# ==============================================================================
# Navigation
# ==============================================================================
with st.sidebar:
    st.title("AI Video Editor")
    st.caption("Gemini • ElevenLabs • CapCut")

page = st.navigation([
    st.Page(create_page, title="สร้างวิดีโอ", icon=":material/movie:"),
    st.Page(library_page, title="คลังวิดีโอ", icon=":material/video_library:"),
    st.Page(settings_page, title="ตั้งค่า", icon=":material/settings:"),
])
page.run()