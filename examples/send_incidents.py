#!/usr/bin/env python3
"""
Script to send all example incidents to the Crisis Management API.

This script scans the examples/incidents/ directory and sends all JSON files
to the POST /api/v1/incidents endpoint, streaming responses via SSE.

Usage:
    python examples/send_incidents.py
    python examples/send_incidents.py --api-url http://localhost:8080
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import httpx


async def send_incident(client: httpx.AsyncClient, api_url: str, incident_file: Path) -> dict:
    """Send a single incident JSON file to the API."""
    with open(incident_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    try:
        response = await client.post(
            f"{api_url}/api/v1/incidents",
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "file": incident_file.name,
            "status": "success",
            "incident_id": data.get("incident_id"),
            "stream_url": data.get("stream_url"),
        }
    except httpx.HTTPError as exc:
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
        print(f"ERROR: incidents directory not found at {examples_dir}")
        return 1

    # Collect all JSON files
    json_files = sorted(examples_dir.glob("*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found in {examples_dir}")
        return 1

    print(f"Found {len(json_files)} incident files")
    print(f"API base URL: {api_url}")
    print("-" * 80)

    # Send incidents
    results = []
    async with httpx.AsyncClient() as client:
        for json_file in json_files:
            result = await send_incident(client, api_url, json_file)
            results.append(result)

            # Print result
            status_symbol = "✓" if result["status"] == "success" else "✗"
            print(f"{status_symbol} {result['file']:<30} ", end="")
            if result["status"] == "success":
                print(f"incident_id={result['incident_id']}")
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")

            # Small delay to avoid overwhelming the API
            await asyncio.sleep(0.1)

    # Summary
    print("-" * 80)
    success_count = sum(1 for r in results if r["status"] == "success")
    error_count = len(results) - success_count
    print(f"Sent {len(results)} incidents: {success_count} success, {error_count} errors")

    if error_count > 0:
        print("\nFailed incidents:")
        for result in results:
            if result["status"] == "error":
                print(f"  - {result['file']}: {result.get('error', 'Unknown error')}")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

