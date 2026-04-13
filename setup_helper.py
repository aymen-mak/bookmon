#!/usr/bin/env python3
"""
Setup helper — fetches available VAC centers and visa categories
from the VFS master data API so you can fill in your .env file.

Usage:
    python setup_helper.py

No authentication required for master data endpoints.
"""

import json
import requests

LIFT_API_BASE = "https://lift-api.vfsglobal.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
    "Accept": "application/json",
}


def fetch_json(url: str) -> list | dict | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  [{resp.status_code}] {url}")
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"        Response: {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"  [ERR] {url} — {exc}")
    return None


def main():
    country = input("Country code (e.g. dza for Algeria): ").strip().lower() or "dza"
    mission = input("Mission code (e.g. ita for Italy): ").strip().lower() or "ita"

    print(f"\n{'='*60}")
    print(f"  Fetching data for {country.upper()} → {mission.upper()}")
    print(f"{'='*60}")

    # Step 1: Get centers
    print(f"\n--- VAC Centers ---")
    url = f"{LIFT_API_BASE}/master/center/{mission}/{country}"
    centers = fetch_json(url)

    if not centers:
        print("\n  Could not fetch centers.")
        print("  The master data API may require authentication for your route.")
        print("  Try logging into the VFS website and checking the network tab.")
        return

    if isinstance(centers, list):
        for c in centers:
            if isinstance(c, dict):
                code = c.get("vacCode") or c.get("code") or c.get("centerCode", "")
                name = c.get("vacName") or c.get("name") or c.get("centerName", "")
                print(f"    {code:>10} — {name}")
            else:
                print(f"    {c}")
    else:
        print(f"    {json.dumps(centers, indent=2)}")

    # Step 2: Get visa categories for each center
    vac_code = input("\nEnter your VAC code from above: ").strip()
    if not vac_code:
        print("No VAC code entered, skipping visa categories.")
        return

    print(f"\n--- Visa Categories for {vac_code} ---")
    url = f"{LIFT_API_BASE}/master/visacategory/{mission}/{country}/{vac_code}"
    categories = fetch_json(url)

    if categories and isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict):
                code = cat.get("visaCategoryCode") or cat.get("code", "")
                name = cat.get("visaCategoryName") or cat.get("name", "")
                print(f"    {code:>10} — {name}")
            else:
                print(f"    {cat}")
    elif categories:
        print(f"    {json.dumps(categories, indent=2)}")
    else:
        print("  Could not fetch visa categories.")

    # Step 3: Sub-categories
    cat_code = input("\nEnter your visa category code from above: ").strip()
    if not cat_code:
        return

    print(f"\n--- Sub-categories for {cat_code} ---")
    url = f"{LIFT_API_BASE}/master/subvisacategory/{mission}/{country}/{vac_code}/{cat_code}"
    subcats = fetch_json(url)
    if subcats and isinstance(subcats, list):
        for sub in subcats:
            if isinstance(sub, dict):
                code = sub.get("code") or sub.get("visaSubCategoryCode", "")
                name = sub.get("name") or sub.get("visaSubCategoryName", "")
                print(f"    {code:>10} — {name}")
            else:
                print(f"    {sub}")
    elif subcats:
        print(f"    {json.dumps(subcats, indent=2)}")
    else:
        print("  No sub-categories found (this is normal for many visa types).")

    # Summary
    print(f"\n{'='*60}")
    print("  Add these to your .env:")
    print(f"{'='*60}")
    print(f"  VFS_COUNTRY_CODE={country}")
    print(f"  VFS_MISSION_CODE={mission}")
    print(f"  VFS_VAC_CODE={vac_code}")
    print(f"  VFS_VISA_CATEGORY={cat_code}")


if __name__ == "__main__":
    main()
