import requests
from datetime import datetime
from decimal import Decimal
import html
import re
import os

# ===== CONFIG FROM ENV =====
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")  # e.g., ethospassion.myshopify.com
API_VERSION = "2025-01"
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# ===== HELPERS =====
def xml_escape(text):
    """Escape special XML characters."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def clean_text(text):
    """Remove HTML and escape XML special chars."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return xml_escape(html.unescape(clean).strip())

def format_price(val):
    """Format price with up to 2 decimals, remove trailing .00 if integer."""
    if val is None or val == "":
        return ""
    dec = Decimal(str(val))
    return f"{dec:.2f}".rstrip("0").rstrip(".")

def calc_discount(price, full_price):
    """Calculate percentage discount as integer string."""
    try:
        p = Decimal(price)
        f = Decimal(full_price)
        if f > 0 and p < f:
            pct = ((f - p) / f) * 100
            return str(int(pct))
    except:
        pass
    return None

def cdata_if_needed(text):
    """Wrap in CDATA if contains > sign."""
    if ">" in text:
        return f"<![CDATA[{text}]]>"
    return xml_escape(text)

# ===== FETCH PRODUCTS =====
def get_products():
    all_products = []
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json?limit=250"
    while url:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        all_products.extend(data.get("products", []))

        # Pagination
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
    lines.append("<mywebstore>")
    lines.append(f"<created_at>{datetime.now().strftime('%Y-%m-%d %H:%M')}</created_at>")
    lines.append("<products>")

    for p in products:
        for v in p.get("variants", []):
            qty = v.get("inventory_quantity", 0)
            if qty <= 0:
                continue  # skip out of stock

            lines.append("<product>")
            lines.append(f"<id>{v['id']}</id>")

            # Name
            if v.get("title") and v["title"] != "Default Title":
                name_text = f"{p['title']} {v['title']}"
            else:
                name_text = p["title"]
            lines.append(f"<name>{clean_text(name_text)}</name>")

            # Link
            product_link = f"https://www.ethospassion.com/products/{p['handle']}?variant={v['id']}"
            lines.append(f"<link>{xml_escape(product_link)}</link>")

            # Main image
            main_image = ""
            if v.get("image_id"):
                for img in p.get("images", []):
                    if img.get("id") == v["image_id"]:
                        main_image = img.get("src")
                        break
            if not main_image and p.get("images"):
                main_image = p["images"][0]["src"]
            lines.append(f"<image>{xml_escape(main_image)}</image>")

            # Prices
            price = format_price(v.get("price"))
            compare_at = v.get("compare_at_price")
            if compare_at and Decimal(str(compare_at)) > Decimal(str(v.get("price"))):
                full_price = format_price(compare_at)
            else:
                full_price = price
            lines.append(f"<price>{price}</price>")
            lines.append(f"<full_price>{full_price}</full_price>")

            # Manufacturer
            lines.append(f"<manufacturer>{clean_text(p.get('vendor') or '')}</manufacturer>")

            # MPN
            lines.append(f"<mpn>{clean_text(v.get('sku') or '')}</mpn>")

            # Instock
            lines.append("<instock>Y</instock>")

            # EAN
            lines.append(f"<ean>{clean_text(v.get('barcode') or '')}</ean>")

            # Description
            desc_text = clean_text(p.get("body_html") or "")
            if not desc_text:
                desc_text = clean_text(p.get("title") or "")
            lines.append(f"<description>{desc_text}</description>")

            # Additional images
            additional_images = [img.get("src") for img in p.get("images", []) if img.get("src") != main_image]
            if additional_images:
                lines.append("<additionalimage>")
                for idx, img in enumerate(additional_images[:10], start=1):
                    lines.append(f"<image{idx}>{xml_escape(img)}</image{idx}>")
                lines.append("</additionalimage>")
            else:
                lines.append("<additionalimage/>")

            # Discount
            discount_pct = calc_discount(price, full_price)
            if discount_pct:
                lines.append(f"<discount>{discount_pct}</discount>")

            # Quantity
            lines.append(f"<quantity>{qty}</quantity>")

            # Category
            category = p.get("product_type") or "Uncategorized"
            lines.append(f"<category>{cdata_if_needed(category)}</category>")

            # Shipping
            lines.append("<shiping>0.00</shiping>")

            # Availability
            lines.append("<availability>2 days</availability>")

            lines.append("</product>")

    lines.append("</products>")
    lines.append("</mywebstore>")
    return "\n".join(lines)

# ===== MAIN =====
if __name__ == "__main__":
    print("Fetching products from Shopify...")
    products = get_products()
    print(f"Fetched {len(products)} products.")
    xml_output = build_xml(products)
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml_output)
    print("Feed generated: feed.xml")
