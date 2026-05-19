#!/usr/bin/env python3
"""
Script to send all example incidents to the Crisis Management API.

This script scans the examples/incidents/ directory and sends all JSON files
to the POST /api/v1/incidents endpoint, displaying progress and incident IDs.

Usage:
    python examples/send_incidents.py
    python examples/send_incidents.py --api-url http://localhost:8080
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx


def log_info(message: str):
    """Print info log with timestamp."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] ℹ️  {message}")


def log_success(message: str):
    """Print success log with timestamp."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] ✅ {message}")


def log_warning(message: str):
    """Print warning log with timestamp."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] ⚠️  {message}")


def log_error(message: str):
    """Print error log with timestamp."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] ❌ {message}")


async def send_incident(client: httpx.AsyncClient, api_url: str, incident_file: Path) -> dict:
    """Send a single incident JSON file to the API."""
    with open(incident_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    try:
        log_info(f"Wysyłanie: {incident_file.name} — {payload.get('description', '')[:60]}...")
        response = await client.post(
            f"{api_url}/api/v1/incidents",
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        incident_id = data.get("incident_id")
        stream_url = data.get("stream_url", "").replace(api_url, "")
        log_success(f"{incident_file.name:25} → {incident_id}")
        return {
            "file": incident_file.name,
            "status": "success",
            "incident_id": incident_id,
            "stream_url": stream_url,
        }
    except httpx.HTTPError as exc:
        log_error(f"{incident_file.name:25} → {str(exc)}")
        return {
            "file": incident_file.name,
            "status": "error",
            "error": str(exc),
        }


async def main() -> int:
    """Main entry point."""
    # Parse arguments
    api_url = "http://localhost:8000"
    if "--api-url" in sys.argv:
        idx = sys.argv.index("--api-url")
        if idx + 1 < len(sys.argv):
            api_url = sys.argv[idx + 1]

    # Find examples directory
    examples_dir = Path(__file__).parent / "incidents"
    if not examples_dir.exists():
        log_error(f"Folder incidents nie znaleziony: {examples_dir}")
        return 1

    # Collect all JSON files
    json_files = sorted(examples_dir.glob("*.json"))
    if not json_files:
        log_error(f"Brak plików JSON w {examples_dir}")
        return 1

    print("\n" + "=" * 80)
    log_info(f"Znaleziono {len(json_files)} incydentów do wysłania")
    log_info(f"Adres API: {api_url}")
    log_info(f"Katalog: {examples_dir}")
    print("=" * 80 + "\n")

    # Send incidents
    results = []
    async with httpx.AsyncClient() as client:
        for idx, json_file in enumerate(json_files, 1):
            log_info(f"[{idx}/{len(json_files)}] Przetwarzanie...")
            result = await send_incident(client, api_url, json_file)
            results.append(result)

            # Small delay to avoid overwhelming the API
            await asyncio.sleep(0.15)

    # Summary
    print("\n" + "=" * 80)
    success_count = sum(1 for r in results if r["status"] == "success")
    error_count = len(results) - success_count

    log_success(f"Wysłano {len(results)} incydentów")
    log_info(f"Powodzenie: {success_count} | Błędy: {error_count}")

    if error_count > 0:
        print("\nIncydenty z błędami:")
        for result in results:
            if result["status"] == "error":
                print(f"  • {result['file']}: {result.get('error', 'Nieznany błąd')}")

    if success_count > 0:
        print(f"\n💡 Podpowiedź: Przejdź do dashboardu (http://localhost:8000) i przełączaj się między incydentami używając selektora.")
        print(f"   Lub obserwuj SSE stream: curl http://localhost:8000/viz/stream/{{incident_id}}")

    print("=" * 80 + "\n")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

