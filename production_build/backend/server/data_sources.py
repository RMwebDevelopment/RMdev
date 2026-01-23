from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from .sheets import fetch_csv_rows, read_sheet_dicts


def _to_int(value: Any) -> int:
    """Parse mixed numeric strings like "$600,000" into int safely."""
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return int(float(cleaned)) if cleaned else 0
    except (ValueError, TypeError):
        return 0


def _to_float(value: Any) -> float:
    """Parse decimal strings with commas into float safely."""
    try:
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _normalize_date(value: str) -> str:
    """Return ISO date (YYYY-MM-DD) from either ISO or MM/DD/YY."""
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def load_availability(sheet_id_override: Optional[str] = None) -> List[Dict[str, Any]]:
    sheet_id = sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID")
    sheet_range = os.getenv("SHEETS_AVAIL_RANGE", "Availability!A:B")
    if sheet_id:
        rows = read_sheet_dicts(sheet_id, sheet_range)
        normalized = []
        for row in rows:
            date_raw = (row.get("date") or "").strip()
            date = _normalize_date(date_raw) if date_raw else ""
            slots_raw = row.get("slots") or ""
            slots = [s.strip() for s in slots_raw.split(",") if s.strip()]
            if date and slots:
                normalized.append({"date": date, "slots": slots})
        if normalized:
            return normalized
    sheet_url = os.getenv("SHEETS_AVAIL_URL")
    if sheet_url:
        rows = fetch_csv_rows(sheet_url)
        normalized = []
        for row in rows:
            date_raw = (row.get("date") or "").strip()
            date = _normalize_date(date_raw) if date_raw else ""
            slots_raw = row.get("slots") or ""
            slots = [s.strip() for s in slots_raw.split(",") if s.strip()]
            if date and slots:
                normalized.append({"date": date, "slots": slots})
        if normalized:
            return normalized
    return []


def filter_availability(start: datetime, days: int) -> List[Dict[str, Any]]:
    availability = load_availability()
    end = start + timedelta(days=days)
    results: List[Dict[str, Any]] = []
    for entry in availability:
        try:
            entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        except ValueError:
            continue
        if start <= entry_date <= end:
            results.append(entry)
    return results


def find_slots_for_date(date_str: str, sheet_id_override: Optional[str] = None) -> List[str]:
    for entry in load_availability(sheet_id_override):
        if entry["date"] == date_str:
            return entry["slots"]
    return []


def load_inventory(sheet_id_override: Optional[str] = None) -> List[Dict[str, Any]]:
    sheet_id = sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID")
    sheet_range = os.getenv("SHEETS_INVENTORY_RANGE", "Inventory!A:G")
    if sheet_id:
        rows = read_sheet_dicts(sheet_id, sheet_range)
        normalized = []
        for row in rows:
            sku = (row.get("sku") or "").strip()
            name = (row.get("name") or "").strip()
            if not sku or not name:
                continue
            normalized.append(
                {
                    "sku": sku,
                    "name": name,
                    "status": (row.get("status") or "unknown").strip(),
                    "available": int(row.get("available") or 0),
                    "eta": (row.get("eta") or "").strip(),
                    "keywords": [k.strip() for k in (row.get("keywords") or "").split(",") if k.strip()],
                    "price_band": (row.get("price_band") or "").strip(),
                }
            )
        if normalized:
            return normalized
    sheet_url = os.getenv("SHEETS_INVENTORY_URL")
    if sheet_url:
        rows = fetch_csv_rows(sheet_url)
        normalized = []
        for row in rows:
            sku = (row.get("sku") or "").strip()
            name = (row.get("name") or "").strip()
            if not sku or not name:
                continue
            normalized.append(
                {
                    "sku": sku,
                    "name": name,
                    "status": (row.get("status") or "unknown").strip(),
                    "available": int(row.get("available") or 0),
                    "eta": (row.get("eta") or "").strip(),
                    "keywords": [k.strip() for k in (row.get("keywords") or "").split(",") if k.strip()],
                    "price_band": (row.get("price_band") or "").strip(),
                }
            )
        if normalized:
            return normalized
    # If we reach here, nothing was loaded
    print(f"[inventory] No inventory rows found (sheet_id={sheet_id or 'unset'}, url={sheet_url or 'unset'})")
    return []


def find_inventory_match(
    message: str,
    inventory: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    inventory = inventory or load_inventory()
    lowered = message.lower()
    for item in inventory:
        sku = item.get("sku", "")
        if sku and sku.lower() in lowered:
            return item
        for kw in item.get("keywords", []):
            if kw.lower() in lowered:
                return item
    return None


def format_inventory_note(item: Dict[str, Any]) -> str:
    status = item.get("status", "unknown")
    available = item.get("available", 0)
    eta = item.get("eta", "").strip()
    name = item.get("name", "")
    sku = item.get("sku", "")
    if status == "in_stock" and available > 0:
        return f"{sku} — {name}: In stock ({available} available). {eta}".strip()
    if status == "service":
        return f"{sku} — {name}: Service offering. {eta}".strip()
    return f"{sku} — {name}: Currently backorder. {eta}".strip()


def summarize_inventory(inventory: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    notes: List[str] = []
    for item in inventory[:limit]:
        notes.append(format_inventory_note(item))
    return notes


# -----------------------------
# Real-estate listings support
# -----------------------------

def load_listings(sheet_id_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load listings with up to 5 images and optional location fields."""
    sheet_id = sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID")
    sheet_range = os.getenv("SHEETS_LISTINGS_RANGE", "Listings!A:R")
    rows: List[Dict[str, Any]] = []
    if sheet_id:
        rows = read_sheet_dicts(sheet_id, sheet_range)
    elif os.getenv("SHEETS_LISTINGS_URL"):
        rows = fetch_csv_rows(os.getenv("SHEETS_LISTINGS_URL"))

    listings: List[Dict[str, Any]] = []
    if not rows:
        return listings

    for row in rows:
        address = (row.get("address") or "").strip()
        if not address:
            continue
        price = _to_int(row.get("price"))
        status = (row.get("status") or "unknown").strip().lower()
        beds = _to_int(row.get("beds"))
        baths = _to_float(row.get("baths") or 0)
        sqft = _to_int(row.get("sqft") or row.get("square_feet") or row.get("sq_ft"))
        acres = _to_float(row.get("acres") or row.get("acreage") or row.get("lot_size"))
        images = [
            (row.get(f"image_{i}") or "").strip()
            for i in range(1, 6)
            if (row.get(f"image_{i}") or "").strip()
        ]
        listing_url = (row.get("listing_url") or row.get("url") or "").strip()
        listings.append(
            {
                "address": address,
                "price": price,
                "status": status or "unknown",
                "beds": beds,
                "baths": baths,
                "sqft": sqft,
                "acres": acres,
                "description": (row.get("description") or "").strip(),
                "images": images[:5],
                "listing_url": listing_url,
                "city": (row.get("city") or "").strip(),
                "state": (row.get("state") or "").strip(),
                "county": (row.get("county") or "").strip(),
                "zip": (row.get("zip") or "").strip(),
            }
        )
    return listings


def _status_rank(status: str) -> int:
    status_clean = (status or "").lower()
    if status_clean == "active":
        return 0
    if status_clean == "pending":
        return 1
    if status_clean == "sold":
        return 2
    return 3


def search_listings(
    params: Dict[str, Any],
    listings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    listings = listings or load_listings()
    if not listings:
        return []

    beds_req = _to_int(params.get("beds"))
    baths_req = _to_float(params.get("baths"))
    sqft_target = _to_int(params.get("sqft_target") or params.get("square_feet"))
    price_min = _to_int(params.get("price_min"))
    price_max = _to_int(params.get("price_max"))
    acreage_min = _to_float(params.get("acreage_min") or params.get("acres_min"))
    acreage_max = _to_float(params.get("acreage_max") or params.get("acres_max"))
    location = (
        params.get("location")
        or params.get("zip")
        or params.get("city")
        or params.get("state")
        or ""
    ).strip().lower()

    def location_match(item: Dict[str, Any]) -> bool:
        if not location:
            return True
        fields = [
            item.get("address", ""),
            item.get("city", ""),
            item.get("state", ""),
            item.get("county", ""),
            item.get("zip", ""),
        ]
        return any(location in (field or "").lower() for field in fields)

    scored: List[Dict[str, Any]] = []
    for item in listings:
        if not location_match(item):
            continue
        price = item.get("price") or 0
        acres = item.get("acres") or 0

        score = 0.0
        if beds_req:
            score += abs((item.get("beds") or 0) - beds_req) * 1.2
        if baths_req:
            score += abs((item.get("baths") or 0) - baths_req) * 1.1
        if sqft_target:
            denom = max(sqft_target, 500)
            score += abs((item.get("sqft") or 0) - sqft_target) / denom * 5
        if price_min and price:
            if price < price_min:
                score += (price_min - price) / max(price_min, 1) * 4
        if price_max and price:
            if price > price_max:
                score += (price - price_max) / max(price_max, 1) * 4
        if acreage_min and acres:
            if acres < acreage_min:
                score += (acreage_min - acres) / max(acreage_min, 0.1) * 3
        if acreage_max and acres:
            if acres > acreage_max:
                score += (acres - acreage_max) / max(acreage_max, 0.1) * 3

        scored.append((score, _status_rank(item.get("status", "")), item))

    scored.sort(key=lambda tup: (tup[0], tup[1], -(tup[2].get("price") or 0)))
    return [item for _, _, item in scored]
