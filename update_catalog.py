"""
Script to update the phone catalog from zestmobileshop.com API.
Run this periodically to keep prices and stock status current.

Usage: python update_catalog.py
"""

import json
import requests
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

API_BASE = "https://zestmobileshop.com/api/trpc/phones.search"


def fetch_phones(page=1, page_size=100):
    """Fetch phones from the ZEST Mobile Shop API."""
    params = {
        "batch": "1",
        "input": json.dumps({
            "0": {
                "json": {
                    "search": "",
                    "brand": "all",
                    "stock": "all",
                    "sort": "default",
                    "page": page,
                    "pageSize": page_size
                }
            }
        })
    }
    resp = requests.get(API_BASE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data[0]["result"]["data"]["json"]["phones"]


def update_catalog():
    """Fetch all phones and update the catalog file."""
    all_phones = []
    page = 1

    while True:
        print(f"Fetching page {page}...")
        phones = fetch_phones(page=page)
        if not phones:
            break
        all_phones.extend(phones)
        print(f"  Got {len(phones)} phones (total: {len(all_phones)})")
        if len(phones) < 100:
            break
        page += 1

    # Extract relevant fields
    catalog = []
    for p in all_phones:
        catalog.append({
            "id": p.get("id"),
            "brand": p.get("brand", ""),
            "name": p.get("name", ""),
            "storage": p.get("storage", ""),
            "colors": p.get("colors", ""),
            "price": p.get("price", ""),
            "stock": p.get("stock", ""),
            "tag": p.get("tag", ""),
        })

    output_path = os.path.join(DATA_DIR, "phone_catalog.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Updated catalog: {len(catalog)} phones saved to {output_path}")

    # Print stock summary
    from collections import Counter
    stock_counts = Counter(p["stock"] for p in catalog)
    print(f"Stock distribution: {dict(stock_counts)}")

    brand_counts = Counter(p["brand"] for p in catalog)
    print(f"Brands: {dict(brand_counts)}")


if __name__ == "__main__":
    update_catalog()
