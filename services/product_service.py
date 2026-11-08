import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import config

PRODUCTS_PATH = Path(config.OUTPUT_DIR) / "review_products.json"


def load_products() -> list:
    if not PRODUCTS_PATH.is_file():
        return []
    try:
        payload = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("ไฟล์คลังสินค้าเสียหาย กรุณานำเข้าไฟล์สำรอง") from exc
    return _normalise_products(payload)


def get_all_product_names() -> list[str]:
    """ดึงรายชื่อสินค้าทั้งหมดที่บันทึกไว้ เรียงตามตัวอักษร"""
    products = load_products()
    return sorted(list({p["name"] for p in products if p.get("name")}))


def get_product_link(product_name: str) -> str:
    """ดึงลิงก์ล่าสุดของสินค้านั้นๆ"""
    name = product_name.strip().casefold()
    for p in load_products():
        if p["name"].casefold() == name and p.get("links"):
            return p["links"][-1]
    return ""


def add_pre_staged_product(product_name: str, product_link: str = "") -> dict:
    """บันทึกชื่อสินค้าและลิงก์ล่วงหน้าเข้าคลัง (ถ้ามีอยู่แล้วจะอัปเดตลิงก์โดยไม่เพิ่มรอบรีวิว)"""
    name = _normalise_name(product_name)
    link = _normalise_link(product_link)
    products = load_products()
    
    for product in products:
        if product["name"].casefold() == name.casefold():
            product["name"] = name
            if link and link not in product["links"]:
                product["links"].append(link)
            _write_products(products)
            return dict(product)
            
    new_product = {"name": name, "links": [link] if link else [], "count": 0}
    products.append(new_product)
    _write_products(products)
    return dict(new_product)


def match_product_from_filename(filename: str) -> tuple[str, str]:
    """
    วิเคราะห์ชื่อไฟล์วิดีโอเพื่อค้นหาสินค้าที่ตรงกันมากที่สุดในคลัง (Auto-Match)
    คืนค่าเป็น: (product_name, product_link)
    """
    stem = Path(filename).stem.strip()
    clean_stem = re.sub(r"[_\-.\s]+", " ", stem).casefold()
    products = load_products()

    best_match_name = ""
    best_match_link = ""
    max_match_len = 0

    for prod in products:
        p_name = prod["name"].strip()
        clean_p = re.sub(r"[_\-.\s]+", " ", p_name).casefold()
        
        # 1. ตรวจสอบว่าชื่อสินค้าอยู่ในชื่อไฟล์ หรือชื่อไฟล์อยู่ในชื่อสินค้า
        if clean_p and (clean_p in clean_stem or clean_stem in clean_p):
            if len(clean_p) > max_match_len:
                max_match_len = len(clean_p)
                best_match_name = p_name
                best_match_link = prod["links"][-1] if prod.get("links") else ""

    # หากไม่เจอ ให้ใช้ชื่อไฟล์ตั้งต้นเป็นชื่อสินค้า
    if not best_match_name:
        return stem, ""
    return best_match_name, best_match_link


def validate_product_link(product_link: str = "") -> str:
    return _normalise_link(product_link)


def record_review(product_name: str, product_link: str = "") -> dict:
    name = _normalise_name(product_name)
    link = _normalise_link(product_link)
    products = load_products()
    for product in products:
        if product["name"].casefold() == name.casefold():
            product["name"] = name
            product["count"] = max(1, product.get("count", 0) + 1)
            if link and link not in product["links"]:
                product["links"].append(link)
            _write_products(products)
            return dict(product)
    product = {"name": name, "links": [link] if link else [], "count": 1}
    products.append(product)
    _write_products(products)
    return dict(product)


def delete_product(product_name: str) -> None:
    name = product_name.strip().casefold()
    products = load_products()
    remaining = [product for product in products if product["name"].casefold() != name]
    if len(remaining) == len(products):
        raise ValueError("ไม่พบสินค้าที่ต้องการลบ")
    _write_products(remaining)


def export_products() -> bytes:
    return json.dumps(load_products(), ensure_ascii=False, indent=2).encode("utf-8")


def import_products(payload, replace: bool = False) -> list:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8-sig")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("ไฟล์นำเข้าไม่ใช่ JSON ที่ถูกต้อง") from exc
    imported = _normalise_products(payload)
    if replace:
        merged = _merge_products([], imported)
    else:
        merged = _merge_products(load_products(), imported)
    _write_products(merged)
    return merged


def _normalise_products(payload) -> list:
    if not isinstance(payload, list):
        raise ValueError("ข้อมูลสินค้าต้องเป็น JSON array")
    products = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError("รายการสินค้าที่ {} ไม่ถูกต้อง".format(index + 1))
        name = _normalise_name(item.get("name", ""))
        raw_links = item.get("links")
        if raw_links is None:
            raw_links = []
        if not raw_links and isinstance(item.get("link"), str):
            raw_links = [item["link"]]
        if not isinstance(raw_links, list):
            raise ValueError("links ของ {} ต้องเป็น array".format(name))
        links = []
        for raw_link in raw_links:
            link = _normalise_link(raw_link)
            if link and link not in links:
                links.append(link)
        try:
            count = max(0, int(item.get("count", 0)))
        except (TypeError, ValueError) as exc:
            raise ValueError("count ของ {} ไม่ถูกต้อง".format(name)) from exc
        products.append({"name": name, "links": links, "count": count})
    return products


def _merge_products(current: list, imported: list) -> list:
    merged = [dict(product, links=list(product["links"])) for product in current]
    for incoming in imported:
        existing = next((product for product in merged
                         if product["name"].casefold() == incoming["name"].casefold()), None)
        if existing is None:
            merged.append(dict(incoming, links=list(incoming["links"])))
            continue
        existing["name"] = incoming["name"]
        existing["count"] = max(existing["count"], incoming["count"])
        for link in incoming["links"]:
            if link not in existing["links"]:
                existing["links"].append(link)
    return merged


def _normalise_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("กรุณาระบุชื่อสินค้า")
    return name


def _normalise_link(value) -> str:
    link = str(value or "").strip()
    if not link:
        return ""
    parsed = urlsplit(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https://")
    return link


def _write_products(products: list) -> None:
    PRODUCTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PRODUCTS_PATH.with_name(PRODUCTS_PATH.name + ".tmp")
    temporary.write_text(
        json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, PRODUCTS_PATH)