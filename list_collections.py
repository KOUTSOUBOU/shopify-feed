"""Βοηθητικό script μιας χρήσης.

Τυπώνει όλες τις collections του Shopify με το πλήθος προϊόντων τους,
και δείχνει ποια προϊόντα ανήκουν σε πολλές collections ταυτόχρονα.

Τρέξ' το μία φορά και στείλε μου το output, ώστε να φτιάξουμε τη λογική
προτεραιότητας για το <category> του feed.
"""

import os
import time
import requests
from collections import defaultdict

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").strip()
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "").strip() or "2024-10"
ACCESS_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}
BASE = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"


def get_paginated(url):
    """GET με cursor pagination μέσω του Link header."""
    items_key = None
    out = []
    while url:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        if items_key is None:
            items_key = next(iter(data))
        out.extend(data.get(items_key, []))

        url = None
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip("<> ")
                break
        time.sleep(0.55)   # REST limit: 2 calls/sec
    return out


def main():
    if not SHOPIFY_STORE or not ACCESS_TOKEN:
        raise SystemExit("ERROR: λείπει SHOPIFY_STORE ή SHOPIFY_ADMIN_TOKEN.")

    collections = []
    for kind in ("custom_collections", "smart_collections"):
        found = get_paginated(f"{BASE}/{kind}.json?limit=250")
        for c in found:
            c["_kind"] = kind
        collections.extend(found)
        print(f"Βρέθηκαν {len(found)} {kind}")

    print(f"\nΣΥΝΟΛΟ COLLECTIONS: {len(collections)}\n")
    print("=" * 78)

    product_to_collections = defaultdict(list)
    product_titles = {}
    rows = []

    for c in collections:
        prods = get_paginated(f"{BASE}/collections/{c['id']}/products.json?limit=250")
        # Μετράμε μόνο δημοσιευμένα προϊόντα με απόθεμα, όπως κάνει και το feed
        live = 0
        for p in prods:
            if not p.get("published_at"):
                continue
            if not any(v.get("inventory_quantity", 0) > 0 for v in p.get("variants", [])):
                continue
            live += 1
            product_to_collections[p["id"]].append(c["title"])
            product_titles[p["id"]] = p.get("title", "")
        rows.append((c["title"], c["_kind"], len(prods), live, c.get("handle", "")))

    # --- Πίνακας collections ---
    rows.sort(key=lambda r: -r[3])
    print(f"{'COLLECTION':<38} {'ΤΥΠΟΣ':<19} {'ΟΛΑ':>5} {'ΣΤΟ FEED':>9}")
    print("-" * 78)
    for title, kind, total, live, handle in rows:
        print(f"{title[:37]:<38} {kind:<19} {total:>5} {live:>9}")

    # --- Επικαλύψεις ---
    multi = {pid: cols for pid, cols in product_to_collections.items() if len(cols) > 1}
    print("\n" + "=" * 78)
    print(f"ΠΡΟΪΟΝΤΑ ΣΕ ΠΟΛΛΕΣ COLLECTIONS: {len(multi)} από "
          f"{len(product_to_collections)}\n")
    for pid, cols in sorted(multi.items(), key=lambda x: -len(x[1]))[:40]:
        print(f"  {product_titles[pid][:46]:<48} -> {', '.join(sorted(cols))}")

    # --- Ορφανά ---
    print("\n" + "=" * 78)
    print("Προϊόντα σε ΚΑΜΙΑ collection: τα βλέπεις συγκρίνοντας το πλήθος")
    print(f"({len(product_to_collections)} προϊόντα βρέθηκαν σε τουλάχιστον μία)")


if __name__ == "__main__":
    main()
