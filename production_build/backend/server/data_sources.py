from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from .sheets import fetch_csv_rows, read_sheet_dicts


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
