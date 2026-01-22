"""Helpers for pulling CSV data or Google Sheets service-account data."""
from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any, Dict, List, Optional

import requests

try:  # pragma: no cover - optional dependency
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
except Exception as exc:  # pragma: no cover - runtime optional
    Credentials = None  # type: ignore
    build = None  # type: ignore
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

log = logging.getLogger(__name__)


def fetch_csv_rows(url: str, timeout: int = 8) -> List[Dict[str, Any]]:
    """Fetch a CSV URL (e.g., Sheets export) and return rows as dicts."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - network env dependent
        log.warning("Failed to fetch CSV from %s: %s", url, exc)
        return []
    buf = io.StringIO(resp.text)
    reader = csv.DictReader(buf)
    return [row for row in reader if row]


def _get_service(creds_file: str):
    if Credentials is None or build is None:
        raise RuntimeError(f"Google Sheets client not available: {IMPORT_ERROR}")
    creds = Credentials.from_service_account_file(
        creds_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet_dicts(
    spreadsheet_id: str,
    range_name: str,
    creds_file: Optional[str] = None,
) -> List[Dict[str, Any]]:
    creds_file = creds_file or os.getenv("SHEETS_SERVICE_ACCOUNT_FILE")
    if not creds_file:
        return []
    try:
        service = _get_service(creds_file)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        values = result.get("values", [])
        if not values or len(values) < 2:
            return []
        headers = [h.strip() for h in values[0]]
        rows: List[Dict[str, Any]] = []
        for row in values[1:]:
            item = {}
            for i, header in enumerate(headers):
                item[header] = row[i] if i < len(row) else ""
            rows.append(item)
        return rows
    except Exception as exc:  # pragma: no cover - external dependency
        log.warning("Failed to read Google Sheet %s %s: %s", spreadsheet_id, range_name, exc)
        return []


def append_sheet_row(
    spreadsheet_id: str,
    range_name: str,
    row: List[Any],
    creds_file: Optional[str] = None,
) -> bool:
    creds_file = creds_file or os.getenv("SHEETS_SERVICE_ACCOUNT_FILE")
    if not creds_file:
        return False
    try:
        service = _get_service(creds_file)
        body = {"values": [row]}
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        return True
    except Exception as exc:  # pragma: no cover - external dependency
        log.warning("Failed to append to Google Sheet %s %s: %s", spreadsheet_id, range_name, exc)
        return False
