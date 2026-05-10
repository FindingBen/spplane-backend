from decimal import Decimal, InvalidOperation


class ProductRuleEngine:
    LOW_INVENTORY_THRESHOLD = 10

    @staticmethod
    def analyze(product_data: dict) -> dict:
        variants = product_data.get("variants") or []
        images = product_data.get("images") or []
        total_inventory = ProductRuleEngine._coerce_int(product_data.get("total_inventory"))
        variant_items = [
            {
                "id": variant.get("id"),
                "title": variant.get("title") or "Default option",
                "price": variant.get("price"),
                "inventory_quantity": ProductRuleEngine._coerce_int(variant.get("inventory_quantity")),
                "image_url": variant.get("image_url"),
            }
            for variant in variants
        ]

        prices = [
            ProductRuleEngine._coerce_decimal(variant.get("price"))
            for variant in variants
            if ProductRuleEngine._coerce_decimal(variant.get("price")) is not None
        ]

        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        show_urgency = total_inventory is not None and total_inventory < ProductRuleEngine.LOW_INVENTORY_THRESHOLD
        show_variant_options = len(variant_items) > 1

        return {
            "signals": {
                "has_gallery": len(images) > 1,
                "has_multiple_variants": show_variant_options,
                "has_price": min_price is not None,
                "show_urgency": show_urgency,
                "total_inventory": total_inventory,
                "variant_count": len(variant_items),
            },
            "price_label": ProductRuleEngine._build_price_label(min_price=min_price, max_price=max_price),
            "urgency_message": (
                f"Only {total_inventory} units left in stock." if show_urgency and total_inventory is not None else None
            ),
            "variant_items": variant_items,
            "gallery_items": [
                {
                    "url": image_url,
                    "alt": item.get("image_alt_text") or item.get("alt") or product_data.get("title"),
                }
                for image_url, item in zip(images, product_data.get("media") or [], strict=False)
            ]
            or [{"url": image_url, "alt": product_data.get("title")} for image_url in images],
            "blocks": {
                "show_bundle": show_variant_options,
                "show_cta": True,
                "show_gallery": len(images) > 1,
                "show_price": min_price is not None,
                "show_urgency": show_urgency,
            },
        }

    @staticmethod
    def _coerce_int(value):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_decimal(value):
        if value in (None, ""):
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _build_price_label(*, min_price, max_price) -> str | None:
        if min_price is None:
            return None
        if max_price is None or min_price == max_price:
            return f"${min_price:.2f}"
        return f"From ${min_price:.2f} to ${max_price:.2f}"