import requests
from datetime import datetime
from decimal import Decimal, InvalidOperation
import html
import re
import os
import sys

# ====== CONFIG ======
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").strip()
# .strip() or "..." ώστε ένα κενό env var να πέφτει στο default αντί για ""
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "").strip() or "2024-10"
ACCESS_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

# Store domain for product links
STORE_DOMAIN = "https://www.ethospassion.com"

# Default VAT rate (%) — Greece standard rate
DEFAULT_VAT_RATE = "24.00"

# Greek availability string (satisfies both Linkwise & Skroutz)
AVAILABILITY_TEXT = "Παράδοση σε 1-3 ημέρες"

# Description max length (Linkwise limit = 1000)
DESCRIPTION_MAX_LENGTH = 1000

# Product types to EXCLUDE from the feed
EXCLUDED_PRODUCT_TYPES = {"Gift cards"}

# Valid GTIN lengths (EAN-8, UPC-A, EAN-13, GTIN-14)
VALID_BARCODE_LENGTHS = {8, 12, 13, 14}


# ===== HELPERS =====
def xml_escape(text):
    """Escape special XML characters. ΜΗΝ το χρησιμοποιείς για περιεχόμενο CDATA."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def clean_text(text, escape=True):
    """Remove HTML tags, unescape HTML entities, collapse whitespace.

    escape=True  -> για περιεχόμενο που μπαίνει σκέτο σε tag (π.χ. <mpn>)
    escape=False -> για περιεχόμενο που μπαίνει σε CDATA. Το CDATA δεν
                    χρειάζεται escaping, και αν το κάνεις ο καταναλωτής
                    του feed βλέπει κυριολεκτικά "&amp;" μέσα στο κείμενο.
    """
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)      # replace tags with space
    clean = html.unescape(clean).strip()
    clean = re.sub(r"\s+", " ", clean)          # collapse whitespace
    # Το "]]>" θα έσπαγε το CDATA block
    clean = clean.replace("]]>", "]] >")
    return xml_escape(clean) if escape else clean


def clean_barcode(barcode):
    """Κρατά μόνο έγκυρα GTIN.

    Καθαρίζει αποστρόφους, κενά και suffix τύπου "(EAN-13)".
    Επιστρέφει "" αν αυτό που μένει δεν είναι έγκυρο barcode
    (π.χ. όταν στο πεδίο barcode έχει μπει κατά λάθος το SKU).
    """
    if not barcode:
        return ""
    text = str(barcode)
    # Πρώτα πετάμε σχόλια σε παρένθεση, π.χ. "4024144673971 (EAN-13)".
    # Αλλιώς το "13" του "EAN-13" θα κολλούσε στα ψηφία του barcode.
    text = re.sub(r"\([^)]*\)", " ", text)
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) in VALID_BARCODE_LENGTHS else ""


def format_price(val):
    """Format price with exactly 2 decimals (both platforms expect this)."""
    if val is None or val == "":
        return ""
    try:
        dec = Decimal(str(val))
        return f"{dec:.2f}"
    except (InvalidOperation, ValueError):
        return ""


def calc_discount(price_str, full_price_str):
    """Calculate percentage discount with up to 2 decimal places."""
    try:
        p = Decimal(price_str)
        f = Decimal(full_price_str)
        if f > 0 and p < f:
            pct = ((f - p) / f) * 100
            return f"{pct:.2f}"
    except (InvalidOperation, ValueError, ZeroDivisionError):
        pass
    return "0"


def cdata(text):
    """Wrap text in CDATA section."""
    return f"<![CDATA[{text}]]>"


def truncate(text, max_len):
    """Truncate text to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


# ===== FETCH PRODUCTS =====
def get_products():
    """Fetch only ACTIVE products from Shopify Admin API."""
    if not SHOPIFY_STORE or not ACCESS_TOKEN:
        raise SystemExit(
            "ERROR: λείπει SHOPIFY_STORE ή SHOPIFY_ADMIN_TOKEN. "
            "Έλεγξε τα secrets του repository."
        )

    all_products = []
    url = (
        f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"
        f"/products.json?limit=250&status=active"
    )
    while url:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        all_products.extend(data.get("products", []))

        # Pagination via Link header
        link_header = r.headers.get("Link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip("<> ")
                break
        url = next_url
    return all_products


# ===== BUILD XML =====
def build_xml(products):
    lines = []
    stats = {
        "written": 0,
        "skipped_type": 0,
        "skipped_unpublished": 0,
        "skipped_no_stock": 0,
        "skipped_no_identifier": 0,
        "dropped_barcode": 0,
    }

    # --- XML declaration (required by Skroutz) ---
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<mywebstore>")
    lines.append(
        f"<created_at>{datetime.now().strftime('%Y-%m-%d %H:%M')}</created_at>"
    )
    lines.append("<products>")

    for p in products:
        product_type = p.get("product_type") or ""

        # --- Skip excluded product types (e.g. Gift cards) ---
        if product_type in EXCLUDED_PRODUCT_TYPES:
            stats["skipped_type"] += len(p.get("variants", []))
            continue

        # --- Skip products not published to the Online Store ---
        # status=active ΔΕΝ σημαίνει δημοσιευμένο: ένα προϊόν μπορεί να είναι
        # active αλλά αποσυνδεδεμένο από το κανάλι Online Store.
        if not p.get("published_at"):
            stats["skipped_unpublished"] += len(p.get("variants", []))
            continue

        # --- Determine option structure for Color ---
        option_defs = p.get("options", [])
        color_option_index = None   # 0-based: option1, option2, option3
        for i, opt in enumerate(option_defs):
            if opt.get("name", "").strip().lower() in ("χρώμα", "color", "colour"):
                color_option_index = i
                break

        # --- Pre-compute description (shared by all variants of this product) ---
        raw_desc = clean_text(p.get("body_html") or "", escape=False)
        if not raw_desc:
            raw_desc = clean_text(p.get("title") or "", escape=False)
        desc_text = truncate(raw_desc, DESCRIPTION_MAX_LENGTH)

        # --- Pre-compute category ---
        category = product_type if product_type else "Uncategorized"

        # --- Pre-compute manufacturer ---
        manufacturer = clean_text(p.get("vendor") or "", escape=False) or "OEM"

        for v in p.get("variants", []):
            qty = v.get("inventory_quantity", 0)
            if qty <= 0:
                stats["skipped_no_stock"] += 1
                continue  # skip out-of-stock

            # ---- Identifiers ----
            mpn = clean_text(v.get("sku") or "")
            raw_barcode = v.get("barcode") or ""
            barcode = clean_barcode(raw_barcode)
            if raw_barcode and not barcode:
                stats["dropped_barcode"] += 1

            # Skroutz/Linkwise θέλουν τουλάχιστον ένα αναγνωριστικό
            if not mpn and not barcode:
                stats["skipped_no_identifier"] += 1
                print(
                    f"  WARNING: παραλείφθηκε '{p.get('title')}' "
                    f"(variant {v['id']}) — χωρίς SKU και χωρίς barcode"
                )
                continue

            lines.append("<product>")

            # ---- Unique ID ----
            lines.append(f"<id>{v['id']}</id>")

            # ---- Name ----
            # Append variant title if it's not "Default Title"
            if v.get("title") and v["title"] != "Default Title":
                name_text = f"{p['title']} {v['title']}"
            else:
                name_text = p["title"]
            lines.append(f"<name>{cdata(clean_text(name_text, escape=False))}</name>")

            # ---- Product Link ----
            product_link = f"{STORE_DOMAIN}/products/{p['handle']}?variant={v['id']}"
            lines.append(f"<link>{cdata(product_link)}</link>")

            # ---- Main Image ----
            main_image = ""
            if v.get("image_id"):
                for img in p.get("images", []):
                    if img.get("id") == v["image_id"]:
                        main_image = img.get("src", "")
                        break
            if not main_image and p.get("images"):
                main_image = p["images"][0].get("src", "")
            lines.append(f"<image>{cdata(main_image)}</image>")

            # ---- Additional Images ----
            # Linkwise format: nested <image1>, <image2>... inside <additionalimage>
            additional_images = [
                img.get("src") for img in p.get("images", [])
                if img.get("src") and img.get("src") != main_image
            ]
            if additional_images:
                lines.append("<additionalimage>")
                for idx, img_url in enumerate(additional_images[:10], start=1):
                    lines.append(f"<image{idx}>{cdata(img_url)}</image{idx}>")
                lines.append("</additionalimage>")
                # Skroutz format: separate <additional_imageurl> tags
                for img_url in additional_images[:15]:
                    lines.append(
                        f"<additional_imageurl>{cdata(img_url)}</additional_imageurl>"
                    )
            else:
                lines.append("<additionalimage/>")

            # ---- Category ----
            lines.append(f"<category>{cdata(category)}</category>")

            # ---- Price (current retail price incl. VAT) ----
            price = format_price(v.get("price"))
            lines.append(f"<price>{price}</price>")

            # ---- Full Price (original price before discount) [Linkwise] ----
            compare_at = v.get("compare_at_price")
            if compare_at:
                try:
                    if Decimal(str(compare_at)) > Decimal(str(v.get("price", 0))):
                        full_price = format_price(compare_at)
                    else:
                        full_price = price
                except (InvalidOperation, ValueError):
                    full_price = price
            else:
                full_price = price
            lines.append(f"<full_price>{full_price}</full_price>")

            # ---- Discount percentage [Linkwise] ----
            discount_pct = calc_discount(price, full_price)
            lines.append(f"<discount>{discount_pct}</discount>")

            # ---- VAT Rate [Skroutz required] ----
            lines.append(f"<vat>{DEFAULT_VAT_RATE}</vat>")

            # ---- Manufacturer ----
            lines.append(f"<manufacturer>{cdata(manufacturer)}</manufacturer>")

            # ---- MPN (SKU) ----
            lines.append(f"<mpn>{mpn}</mpn>")

            # ---- EAN / Barcode ----
            lines.append(f"<ean>{barcode}</ean>")

            # ---- In Stock ----
            lines.append("<instock>Y</instock>")

            # ---- Availability ----
            lines.append(f"<availability>{AVAILABILITY_TEXT}</availability>")

            # ---- Description ----
            lines.append(f"<description>{cdata(desc_text)}</description>")

            # ---- Quantity ----
            lines.append(f"<quantity>{qty}</quantity>")

            # ---- Color (if product has a color option) ----
            if color_option_index is not None:
                color_key = f"option{color_option_index + 1}"
                color_val = v.get(color_key, "")
                if color_val and color_val != "Default Title":
                    lines.append(f"<color>{xml_escape(color_val)}</color>")

            # ---- Weight (in grams, from Shopify) ----
            weight_grams = v.get("grams", 0)
            if weight_grams and weight_grams > 0:
                lines.append(f"<weight>{weight_grams}</weight>")

            # ---- Shipping Costs ----
            lines.append("<shipping>0</shipping>")

            lines.append("</product>")
            stats["written"] += 1

    lines.append("</products>")
    lines.append("</mywebstore>")
    return "\n".join(lines), stats


# ===== MAIN =====
if __name__ == "__main__":
    print(f"Fetching products from Shopify (API {API_VERSION})...")
    products = get_products()
    print(f"Fetched {len(products)} products.")

    xml_output, stats = build_xml(products)

    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml_output)

    print("\n--- Feed summary ---")
    print(f"  Γράφτηκαν στο feed:        {stats['written']}")
    print(f"  Χωρίς απόθεμα:             {stats['skipped_no_stock']}")
    print(f"  Μη δημοσιευμένα:           {stats['skipped_unpublished']}")
    print(f"  Εξαιρούμενος τύπος:        {stats['skipped_type']}")
    print(f"  Χωρίς SKU/barcode:         {stats['skipped_no_identifier']}")
    print(f"  Άκυρα barcode που κόπηκαν: {stats['dropped_barcode']}")
    print("Feed generated: feed.xml")

    # Δίχτυ ασφαλείας: άδειο ή σχεδόν άδειο feed είναι σφάλμα, όχι επιτυχία
    if stats["written"] == 0:
        print("ERROR: το feed δεν περιέχει κανένα προϊόν.", file=sys.stderr)
        sys.exit(1)
