import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.contacts.models import Contact
from apps.shopify.models import (
    ShopifyCustomerLink,
    ShopifyProduct,
    ShopifyProductMedia,
    ShopifyProductVariant,
)
from apps.shopify.queries import GET_CUSTOMERS_QUERY, GET_PRODUCT_QUERY, GET_PRODUCTS_QUERY

logger = logging.getLogger(__name__)


class ShopifyGraphQLError(Exception):
    """Raised when Shopify GraphQL returns HTTP or top-level GraphQL errors."""


class ShopifyCustomerImportStateError(Exception):
    """Raised when the local shop import state disallows another import."""


class ShopifyProductImportStateError(Exception):
    """Raised when the local shop product import should not run again."""


class ShopifyGraphQLClient:
    """
    Thin Shopify Admin GraphQL client.

    This layer is intentionally transport-only: it knows how to talk to
    Shopify and normalize transport errors, but it does not know anything
    about requests, views, or local business rules.
    """

    def __init__(self, shop_domain: str, access_token: str):
        self._shop_domain = shop_domain
        self._access_token = access_token
        self._url = f"https://{shop_domain}/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json"

    def execute(self, query: str, variables: dict | None = None) -> dict:
        headers = {
            "X-Shopify-Access-Token": self._access_token,
            "Content-Type": "application/json",
        }

        response = requests.post(
            self._url,
            headers=headers,
            json={"query": query, "variables": variables or {}},
            timeout=15,
        )

        try:
            body = response.json()
        except ValueError as exc:
            logger.error(
                "ShopifyGraphQLClient: invalid JSON response for %s: %s",
                self._shop_domain,
                response.text,
            )
            raise ShopifyGraphQLError("Shopify returned an invalid JSON response.") from exc

        if response.status_code >= 400:
            logger.error(
                "ShopifyGraphQLClient: HTTP %s for %s: %s",
                response.status_code,
                self._shop_domain,
                body,
            )
            raise ShopifyGraphQLError(f"Shopify HTTP error: {response.status_code}")

        errors = body.get("errors")
        if errors:
            logger.error(
                "ShopifyGraphQLClient: GraphQL errors for %s: %s",
                self._shop_domain,
                errors,
            )
            raise ShopifyGraphQLError(f"Shopify GraphQL error: {errors}")

        return body.get("data", {})


class ShopifyCustomerService:
    """
    Customer-specific Shopify operations.

    This layer accepts plain arguments or model objects and returns normalized
    Python data structures. It does not depend on DRF request objects.
    """

    @staticmethod
    def fetch_customers(
        shopify_profile,
        *,
        search_query: str = "",
        cursor: str | None = None,
        first: int = 50,
        reverse: bool = False,
    ) -> dict:
        """
        Fetches one page of Shopify customers for the given connected shop.

        Returns a normalized payload:
        {
            "customers": [...],
            "page_info": {
                "has_next_page": bool,
                "end_cursor": str | None,
            },
        }
        """
        page_size = max(1, min(first, 250))
        client = ShopifyGraphQLClient(
            shop_domain=shopify_profile.shop_domain,
            access_token=shopify_profile.access_token,
        )
        data = client.execute(
            GET_CUSTOMERS_QUERY,
            variables={
                "first": page_size,
                "after": cursor,
                "query": search_query or None,
                "reverse": reverse,
            },
        )

        customers_payload = data.get("customers", {})
        edges = customers_payload.get("edges", [])
        customers = [
            ShopifyCustomerService._serialize_customer(edge.get("node", {}))
            for edge in edges
            if edge.get("node")
        ]
        page_info = customers_payload.get("pageInfo", {})

        return {
            "customers": customers,
            "page_info": {
                "has_next_page": page_info.get("hasNextPage", False),
                "end_cursor": page_info.get("endCursor"),
            },
        }

    @staticmethod
    def _serialize_customer(customer: dict) -> dict:
        default_phone = customer.get("defaultPhoneNumber") or {}

        return {
            "id": customer.get("id"),
            "first_name": customer.get("firstName") or "",
            "last_name": customer.get("lastName") or "",
            "phone": customer.get("phone") or "",
            "marketing_state": default_phone.get("marketingState") or "NONE",
            "created_at": customer.get("createdAt"),
            "updated_at": customer.get("updatedAt"),
        }

    @staticmethod
    def _sanitize_customer(customer: dict) -> dict:
        sanitized_customer = dict(customer)
        sanitized_customer.pop("email", None)
        return sanitized_customer

    @staticmethod
    def import_customers(
        shopify_profile,
        *,
        user,
    ) -> dict:
        """
        Imports the merchant's full Shopify customer catalog into local
        contacts and ShopifyCustomerLink rows.
        """
        if shopify_profile.first_time_import_customers:
            raise ShopifyCustomerImportStateError(
                "Customers can be imported only once. Contact support for more info."
            )

        customers = ShopifyCustomerService._fetch_all_customers(shopify_profile)
        return ShopifyCustomerService._import_fetched_customers(
            shopify_profile=shopify_profile,
            user=user,
            customers=customers,
        )

    @staticmethod
    def _fetch_all_customers(
        shopify_profile,
        *,
        page_size: int = 250,
    ) -> list[dict]:
        customers: list[dict] = []
        cursor: str | None = None

        while True:
            payload = ShopifyCustomerService.fetch_customers(
                shopify_profile,
                cursor=cursor,
                first=page_size,
            )
            customers.extend(
                ShopifyCustomerService._sanitize_customer(customer)
                for customer in payload.get("customers", [])
            )

            page_info = payload.get("page_info", {})
            next_cursor = page_info.get("end_cursor")
            if not page_info.get("has_next_page") or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor

        return customers

    @staticmethod
    def _build_contact_attributes(
        customer: dict,
        shopify_profile,
        *,
        existing_custom_attributes: dict | None = None,
    ) -> dict:
        custom_attributes = dict(existing_custom_attributes or {})
        custom_attributes.pop("email", None)
        custom_attributes.update(
            {
                "shopify_customer_id": customer.get("id", ""),
                "shop_domain": shopify_profile.shop_domain,
            }
        )

        return {
            "first_name": customer.get("first_name", ""),
            "last_name": customer.get("last_name", ""),
            "status": "subscribed",
            "source": "shopify",
            "custom_attributes": custom_attributes,
        }

    @staticmethod
    def _upsert_contacts(
        *,
        shopify_profile,
        user,
        customers: list[dict],
        timestamp,
    ) -> tuple[dict[str, Contact], dict]:
        customer_by_phone: dict[str, dict] = {}
        for customer in customers:
            phone = customer.get("phone") or ""
            if phone:
                customer_by_phone[phone] = customer

        if not customer_by_phone:
            return {}, {"created": 0, "updated": 0}

        phones = list(customer_by_phone)
        existing_contacts = {
            contact.phone: contact
            for contact in Contact.objects.filter(users=user, phone__in=phones)
        }

        contacts_to_create = []
        contacts_to_update = []

        for phone, customer in customer_by_phone.items():
            existing_contact = existing_contacts.get(phone)
            contact_attributes = ShopifyCustomerService._build_contact_attributes(
                customer,
                shopify_profile,
                existing_custom_attributes=(
                    existing_contact.custom_attributes if existing_contact is not None else None
                ),
            )

            if existing_contact is None:
                contacts_to_create.append(
                    Contact(
                        users=user,
                        phone=phone,
                        first_name=contact_attributes["first_name"],
                        last_name=contact_attributes["last_name"],
                        status=contact_attributes["status"],
                        source=contact_attributes["source"],
                        custom_attributes=contact_attributes["custom_attributes"],
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                continue

            existing_contact.first_name = contact_attributes["first_name"]
            existing_contact.last_name = contact_attributes["last_name"]
            existing_contact.status = contact_attributes["status"]
            existing_contact.source = contact_attributes["source"]
            existing_contact.custom_attributes = contact_attributes["custom_attributes"]
            existing_contact.updated_at = timestamp
            contacts_to_update.append(existing_contact)

        if contacts_to_create:
            Contact.objects.bulk_create(contacts_to_create, batch_size=500)

        if contacts_to_update:
            Contact.objects.bulk_update(
                contacts_to_update,
                ["first_name", "last_name", "status", "source", "custom_attributes", "updated_at"],
                batch_size=500,
            )

        contacts_by_phone = {
            contact.phone: contact
            for contact in Contact.objects.filter(users=user, phone__in=phones)
        }
        return contacts_by_phone, {
            "created": len(contacts_to_create),
            "updated": len(contacts_to_update),
        }

    @staticmethod
    @transaction.atomic
    def _import_fetched_customers(
        *,
        shopify_profile,
        user,
        customers: list[dict],
    ) -> dict:
        timestamp = timezone.now()
        sanitized_customers = [
            ShopifyCustomerService._sanitize_customer(customer) for customer in customers
        ]
        valid_customers = [customer for customer in sanitized_customers if customer.get("id")]

        contacts_by_phone, contact_stats = ShopifyCustomerService._upsert_contacts(
            shopify_profile=shopify_profile,
            user=user,
            customers=valid_customers,
            timestamp=timestamp,
        )

        customer_ids = [customer["id"] for customer in valid_customers]
        existing_links = {
            link.shopify_customer_id: link
            for link in ShopifyCustomerLink.objects.filter(
                shopify_profile=shopify_profile,
                shopify_customer_id__in=customer_ids,
            ).select_related("contact")
        }

        links_to_create = []
        links_to_update = []
        results = []

        imported_count = 0
        skipped_count = 0
        failed_count = 0

        for customer in sanitized_customers:
            shopify_customer_id = customer.get("id")
            if not shopify_customer_id:
                failed_count += 1
                results.append(
                    {
                        "status": "failed",
                        "shopify_customer_id": "",
                        "reason": "Customer id is required.",
                    }
                )
                continue

            phone = customer.get("phone") or ""
            contact = contacts_by_phone.get(phone) if phone else None
            existing_link = existing_links.get(shopify_customer_id)
            link_contact = contact if contact is not None else (existing_link.contact if existing_link else None)

            if existing_link is None:
                links_to_create.append(
                    ShopifyCustomerLink(
                        shopify_profile=shopify_profile,
                        shopify_customer_id=shopify_customer_id,
                        contact=link_contact,
                        first_name=customer.get("first_name", ""),
                        last_name=customer.get("last_name", ""),
                        phone_snapshot=phone,
                        marketing_state=customer.get("marketing_state", "NONE"),
                        imported_at=timestamp if contact is not None else None,
                        last_synced_at=timestamp,
                        deleted_at=None,
                        raw_payload=customer,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                created_link = True
            else:
                existing_link.contact = link_contact
                existing_link.first_name = customer.get("first_name", "")
                existing_link.last_name = customer.get("last_name", "")
                existing_link.phone_snapshot = phone
                existing_link.marketing_state = customer.get("marketing_state", "NONE")
                existing_link.last_synced_at = timestamp
                existing_link.deleted_at = None
                existing_link.raw_payload = customer
                existing_link.updated_at = timestamp
                if contact is not None and existing_link.imported_at is None:
                    existing_link.imported_at = timestamp
                links_to_update.append(existing_link)
                created_link = False

            if contact is None:
                skipped_count += 1
                results.append(
                    {
                        "status": "skipped",
                        "shopify_customer_id": shopify_customer_id,
                        "reason": "Customer has no phone number.",
                        "created_link": created_link,
                    }
                )
                continue

            imported_count += 1
            results.append(
                {
                    "status": "imported",
                    "shopify_customer_id": shopify_customer_id,
                    "contact_id": contact.id,
                    "created_link": created_link,
                }
            )

        if links_to_create:
            ShopifyCustomerLink.objects.bulk_create(links_to_create, batch_size=500)

        if links_to_update:
            ShopifyCustomerLink.objects.bulk_update(
                links_to_update,
                [
                    "contact",
                    "first_name",
                    "last_name",
                    "phone_snapshot",
                    "marketing_state",
                    "imported_at",
                    "last_synced_at",
                    "deleted_at",
                    "raw_payload",
                    "updated_at",
                ],
                batch_size=500,
            )

        summary = {
            "requested": len(sanitized_customers),
            "fetched": len(sanitized_customers),
            "imported": imported_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "contacts_created": contact_stats["created"],
            "contacts_updated": contact_stats["updated"],
            "links_created": len(links_to_create),
            "links_updated": len(links_to_update),
        }

        if failed_count == 0 and not shopify_profile.first_time_import_customers:
            shopify_profile.first_time_import_customers = True
            shopify_profile.save(update_fields=["first_time_import_customers"])

        return {
            "first_time_import_customers": shopify_profile.first_time_import_customers,
            "summary": summary,
            "results": results,
        }


class ShopifyProductService:
    """Product-specific Shopify operations backed by the local catalog projection."""

    @staticmethod
    def fetch_products(
        shopify_profile,
        *,
        search_query: str = "",
        cursor: str | None = None,
        first: int = 50,
        reverse: bool = False,
    ) -> dict:
        page_size = max(1, min(first, 250))
        client = ShopifyGraphQLClient(
            shop_domain=shopify_profile.shop_domain,
            access_token=shopify_profile.access_token,
        )
        data = client.execute(
            GET_PRODUCTS_QUERY,
            variables={
                "first": page_size,
                "after": cursor,
                "query": ShopifyProductService._build_product_query(search_query),
                "reverse": reverse,
            },
        )

        products_payload = data.get("products", {})
        edges = products_payload.get("edges", [])
       
        products = [
            ShopifyProductService._serialize_remote_product(edge.get("node", {}))
            for edge in edges
            if edge.get("node")
        ]
        page_info = products_payload.get("pageInfo", {})

        return {
            "products": products,
            "page_info": {
                "has_next_page": page_info.get("hasNextPage", False),
                "end_cursor": page_info.get("endCursor"),
            },
        }

    @staticmethod
    def import_products(shopify_profile) -> dict:
        if shopify_profile.connect_products:
            raise ShopifyProductImportStateError(
                "Products can be imported only once. Future product changes sync via webhooks."
            )

        products = ShopifyProductService._fetch_all_products(shopify_profile)
        payload = ShopifyProductService._import_fetched_products(
            shopify_profile=shopify_profile,
            products=products,
            prune_missing=True,
        )

        if not shopify_profile.connect_products:
            shopify_profile.connect_products = True
            shopify_profile.save(update_fields=["connect_products"])

        payload["connect_products"] = shopify_profile.connect_products
        return payload

    @staticmethod
    def sync_product_from_webhook(shopify_profile, payload: dict) -> dict:
        product_id = ShopifyProductService._extract_webhook_product_id(payload)
        if not product_id:
            raise ValueError("Webhook payload is missing a product id.")

        sync_payload = ShopifyProductService.sync_product(shopify_profile, product_id)

        if not shopify_profile.connect_products:
            shopify_profile.connect_products = True
            shopify_profile.save(update_fields=["connect_products"])

        sync_payload["connect_products"] = shopify_profile.connect_products
        return sync_payload

    @staticmethod
    def delete_product_from_webhook(shopify_profile, payload: dict) -> dict:
        product_id = ShopifyProductService._extract_webhook_product_id(payload)
        if not product_id:
            raise ValueError("Webhook payload is missing a product id.")

        delete_payload = ShopifyProductService.delete_product(shopify_profile, product_id)

        if not shopify_profile.connect_products:
            shopify_profile.connect_products = True
            shopify_profile.save(update_fields=["connect_products"])

        delete_payload["connect_products"] = shopify_profile.connect_products
        return delete_payload

    @staticmethod
    def sync_product(shopify_profile, shopify_product_id: str) -> dict:
        client = ShopifyGraphQLClient(
            shop_domain=shopify_profile.shop_domain,
            access_token=shopify_profile.access_token,
        )
        data = client.execute(GET_PRODUCT_QUERY, variables={"id": shopify_product_id})
        product_node = data.get("product")

        if not product_node:
            return ShopifyProductService.delete_product(shopify_profile, shopify_product_id)

        product = ShopifyProductService._serialize_remote_product(product_node)
        return ShopifyProductService._import_fetched_products(
            shopify_profile=shopify_profile,
            products=[product],
            prune_missing=False,
        )

    @staticmethod
    def delete_product(shopify_profile, shopify_product_id: str) -> dict:
        timestamp = timezone.now()
        product = ShopifyProduct.objects.filter(
            shopify_profile=shopify_profile,
            shopify_product_id=shopify_product_id,
            deleted_at__isnull=True,
        ).first()

        if product is None:
            return {
                "summary": {
                    "requested": 1,
                    "fetched": 0,
                    "products_created": 0,
                    "products_updated": 0,
                    "products_deleted": 0,
                    "variants_created": 0,
                    "variants_updated": 0,
                    "variants_deleted": 0,
                    "media_created": 0,
                    "media_updated": 0,
                    "media_deleted": 0,
                },
                "results": [
                    {
                        "shopify_product_id": shopify_product_id,
                        "status": "missing",
                    }
                ],
            }

        product.deleted_at = timestamp
        product.last_synced_at = timestamp
        product.save(update_fields=["deleted_at", "last_synced_at", "updated_at"])
        variants_deleted = ShopifyProductVariant.objects.filter(
            product=product,
            deleted_at__isnull=True,
        ).update(deleted_at=timestamp, last_synced_at=timestamp, updated_at=timestamp)
        media_deleted = ShopifyProductMedia.objects.filter(
            product=product,
            deleted_at__isnull=True,
        ).update(deleted_at=timestamp, last_synced_at=timestamp, updated_at=timestamp)

        return {
            "summary": {
                "requested": 1,
                "fetched": 0,
                "products_created": 0,
                "products_updated": 0,
                "products_deleted": 1,
                "variants_created": 0,
                "variants_updated": 0,
                "variants_deleted": variants_deleted,
                "media_created": 0,
                "media_updated": 0,
                "media_deleted": media_deleted,
            },
            "results": [
                {
                    "shopify_product_id": shopify_product_id,
                    "status": "deleted",
                }
            ],
        }

    @staticmethod
    def list_products(
        shopify_profile,
        *,
        search_query: str = "",
        first: int = 50,
    ) -> dict:
        page_size = max(1, min(first, 250))
        products = ShopifyProduct.objects.filter(
            shopify_profile=shopify_profile,
            deleted_at__isnull=True,
        )
        if search_query:
            products = products.filter(
                Q(title__icontains=search_query)
                | Q(handle__icontains=search_query)
                | Q(variants__title__icontains=search_query)
                | Q(variants__sku__icontains=search_query)
            ).distinct()

        products = products.prefetch_related(
            Prefetch(
                "variants",
                queryset=ShopifyProductVariant.objects.filter(deleted_at__isnull=True).order_by(
                    "position", "id"
                ),
            ),
            Prefetch(
                "media",
                queryset=ShopifyProductMedia.objects.filter(deleted_at__isnull=True).order_by(
                    "position", "id"
                ),
            ),
        ).order_by("title", "id")

        total_count = products.count()
        products = list(products[:page_size])

        return {
            "products": [ShopifyProductService._serialize_local_product(product) for product in products],
            "page_info": {
                "has_next_page": total_count > page_size,
                "returned": len(products),
                "total_count": total_count,
            },
        }

    @staticmethod
    def _build_product_query(search_query: str) -> str:
        search_query = (search_query or "").strip()
        if search_query:
            return f"status:ACTIVE {search_query}"
        return "status:ACTIVE"

    @staticmethod
    def _fetch_all_products(
        shopify_profile,
        *,
        page_size: int = 50,
    ) -> list[dict]:
        products: list[dict] = []
        cursor: str | None = None

        while True:
            payload = ShopifyProductService.fetch_products(
                shopify_profile,
                cursor=cursor,
                first=page_size,
            )
            products.extend(payload.get("products", []))

            page_info = payload.get("page_info", {})
            next_cursor = page_info.get("end_cursor")
            if not page_info.get("has_next_page") or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor

        return products

    @staticmethod
    def _serialize_remote_product(product: dict) -> dict:
        variants = ShopifyProductService._serialize_remote_variants(
            product.get("variants", {}).get("edges", [])
        )
        media = ShopifyProductService._serialize_remote_media(
            product.get("media", {}).get("edges", [])
        )
        seo = product.get("seo") or {}
        featured_image_url = ""
        if media:
            featured_image_url = media[0].get("source_url", "")
        elif variants:
            featured_image_url = variants[0].get("featured_image_url", "")

        variants_count = product.get("variantsCount") or {}

        return {
            "id": product.get("id") or "",
            "title": product.get("title") or "",
            "handle": product.get("handle") or "",
            "description_html": product.get("descriptionHtml") or "",
            "status": product.get("status") or "",
            "tags": product.get("tags") or [],
            "seo_title": seo.get("title") or "",
            "seo_description": seo.get("description") or "",
            "featured_image_url": featured_image_url,
            "total_inventory": product.get("totalInventory"),
            "has_out_of_stock_variants": product.get("hasOutOfStockVariants") or False,
            "is_gift_card": product.get("isGiftCard") or False,
            "variant_count": ShopifyProductService._parse_int(variants_count.get("count")) or len(variants),
            "media_count": len(media),
            "published_at": ShopifyProductService._parse_datetime(product.get("publishedAt")),
            "shopify_created_at": ShopifyProductService._parse_datetime(product.get("createdAt")),
            "shopify_updated_at": ShopifyProductService._parse_datetime(product.get("updatedAt")),
            "variants": variants,
            "media": media,
            "raw_payload": product,
        }

    @staticmethod
    def _serialize_remote_variants(edges: list[dict]) -> list[dict]:
        variants = []
        for index, edge in enumerate(edges, start=1):
            node = edge.get("node") or {}
            variant_id = node.get("id")
            if not variant_id:
                continue

            image = node.get("image") or {}
            variants.append(
                {
                    "id": variant_id,
                    "title": node.get("title") or "",
                    "sku": node.get("sku") or "",
                    "price_amount": ShopifyProductService._parse_decimal(node.get("price")),
                    "inventory_quantity": ShopifyProductService._parse_int(node.get("inventoryQuantity")),
                    "position": index,
                    "shopify_image_id": image.get("id") or "",
                    "featured_image_url": image.get("url") or "",
                    "raw_payload": node,
                }
            )

        return variants

    @staticmethod
    def _serialize_remote_media(edges: list[dict]) -> list[dict]:
        media_items = []
        for index, edge in enumerate(edges, start=1):
            node = edge.get("node") or {}
            media_type = (node.get("mediaContentType") or "unknown").lower()
            if media_type != "image":
                continue

            image = node.get("image") or {}
            media_id = node.get("id")
            source_url = image.get("url") or ""
            if not media_id or not source_url:
                continue

            media_items.append(
                {
                    "id": media_id,
                    "media_type": media_type,
                    "alt_text": node.get("alt") or image.get("altText") or "",
                    "source_url": source_url,
                    "preview_image_url": source_url,
                    "mime_type": "",
                    "position": index,
                    "width": ShopifyProductService._parse_int(image.get("width")),
                    "height": ShopifyProductService._parse_int(image.get("height")),
                    "raw_payload": node,
                }
            )

        return media_items

    @staticmethod
    @transaction.atomic
    def _import_fetched_products(
        *,
        shopify_profile,
        products: list[dict],
        prune_missing: bool,
    ) -> dict:
        timestamp = timezone.now()
        valid_products = [product for product in products if product.get("id")]
        incoming_ids = [product["id"] for product in valid_products]
        existing_products = {
            product.shopify_product_id: product
            for product in ShopifyProduct.objects.filter(
                shopify_profile=shopify_profile,
                shopify_product_id__in=incoming_ids,
            )
        }

        stats = {
            "products_created": 0,
            "products_updated": 0,
            "products_deleted": 0,
            "variants_created": 0,
            "variants_updated": 0,
            "variants_deleted": 0,
            "media_created": 0,
            "media_updated": 0,
            "media_deleted": 0,
        }
        results = []

        for product_payload in valid_products:
            product_id = product_payload["id"]
            product = existing_products.get(product_id)
            created = product is None
            if created:
                product = ShopifyProduct(
                    shopify_profile=shopify_profile,
                    shopify_product_id=product_id,
                    imported_at=timestamp,
                )

            ShopifyProductService._apply_product_payload(
                product,
                product_payload,
                timestamp=timestamp,
            )
            product.save()

            if created:
                stats["products_created"] += 1
            else:
                stats["products_updated"] += 1

            child_stats = ShopifyProductService._sync_product_children(
                product,
                product_payload,
                timestamp=timestamp,
            )
            for key, value in child_stats.items():
                stats[key] += value

            results.append(
                {
                    "shopify_product_id": product.shopify_product_id,
                    "status": "created" if created else "updated",
                    "variants": len(product_payload.get("variants", [])),
                    "media": len(product_payload.get("media", [])),
                }
            )

        if prune_missing:
            stale_products = ShopifyProduct.objects.filter(
                shopify_profile=shopify_profile,
                deleted_at__isnull=True,
            )
            if incoming_ids:
                stale_products = stale_products.exclude(shopify_product_id__in=incoming_ids)

            stale_products = list(stale_products)
            for product in stale_products:
                product.deleted_at = timestamp
                product.last_synced_at = timestamp
                product.save(update_fields=["deleted_at", "last_synced_at", "updated_at"])

            if stale_products:
                stats["products_deleted"] += len(stale_products)
                stale_variants = ShopifyProductVariant.objects.filter(
                    product__in=stale_products,
                    deleted_at__isnull=True,
                )
                stale_media = ShopifyProductMedia.objects.filter(
                    product__in=stale_products,
                    deleted_at__isnull=True,
                )
                stats["variants_deleted"] += stale_variants.update(
                    deleted_at=timestamp,
                    last_synced_at=timestamp,
                    updated_at=timestamp,
                )
                stats["media_deleted"] += stale_media.update(
                    deleted_at=timestamp,
                    last_synced_at=timestamp,
                    updated_at=timestamp,
                )

        return {
            "summary": {
                "requested": len(products),
                "fetched": len(valid_products),
                **stats,
            },
            "results": results,
        }

    @staticmethod
    def _apply_product_payload(product, payload: dict, *, timestamp):
        product.title = payload.get("title", "")
        product.handle = payload.get("handle", "")
        product.description_html = payload.get("description_html", "")
        product.status = payload.get("status", "")
        product.tags = payload.get("tags", [])
        product.seo_title = payload.get("seo_title", "")
        product.seo_description = payload.get("seo_description", "")
        product.featured_image_url = payload.get("featured_image_url", "")
        product.total_inventory = payload.get("total_inventory")
        product.has_out_of_stock_variants = payload.get("has_out_of_stock_variants", False)
        product.is_gift_card = payload.get("is_gift_card", False)
        product.variant_count = payload.get("variant_count", 0)
        product.media_count = payload.get("media_count", 0)
        product.published_at = payload.get("published_at")
        product.shopify_created_at = payload.get("shopify_created_at")
        product.shopify_updated_at = payload.get("shopify_updated_at")
        product.raw_payload = payload.get("raw_payload", {})
        product.last_synced_at = timestamp
        product.deleted_at = None
        if product.imported_at is None:
            product.imported_at = timestamp

    @staticmethod
    def _sync_product_children(product, payload: dict, *, timestamp) -> dict:
        stats = {
            "variants_created": 0,
            "variants_updated": 0,
            "variants_deleted": 0,
            "media_created": 0,
            "media_updated": 0,
            "media_deleted": 0,
        }

        incoming_variants = payload.get("variants", [])
        existing_variants = {
            variant.shopify_variant_id: variant
            for variant in ShopifyProductVariant.objects.filter(product=product)
        }
        incoming_variant_ids = []

        for variant_payload in incoming_variants:
            variant_id = variant_payload.get("id")
            if not variant_id:
                continue

            incoming_variant_ids.append(variant_id)
            variant = existing_variants.get(variant_id)
            created = variant is None
            if created:
                variant = ShopifyProductVariant(
                    product=product,
                    shopify_variant_id=variant_id,
                    imported_at=timestamp,
                )

            variant.title = variant_payload.get("title", "")
            variant.sku = variant_payload.get("sku", "")
            variant.price_amount = variant_payload.get("price_amount")
            variant.inventory_quantity = variant_payload.get("inventory_quantity")
            variant.position = variant_payload.get("position", 0)
            variant.shopify_image_id = variant_payload.get("shopify_image_id", "")
            variant.featured_image_url = variant_payload.get("featured_image_url", "")
            variant.raw_payload = variant_payload.get("raw_payload", {})
            variant.last_synced_at = timestamp
            variant.deleted_at = None
            if variant.imported_at is None:
                variant.imported_at = timestamp
            variant.save()

            stats["variants_created" if created else "variants_updated"] += 1

        stale_variants = ShopifyProductVariant.objects.filter(
            product=product,
            deleted_at__isnull=True,
        ).exclude(shopify_variant_id__in=incoming_variant_ids)
        stats["variants_deleted"] += stale_variants.update(
            deleted_at=timestamp,
            last_synced_at=timestamp,
            updated_at=timestamp,
        )

        incoming_media = payload.get("media", [])
        existing_media = {
            media.shopify_media_id: media
            for media in ShopifyProductMedia.objects.filter(product=product)
        }
        incoming_media_ids = []

        for media_payload in incoming_media:
            media_id = media_payload.get("id")
            if not media_id:
                continue

            incoming_media_ids.append(media_id)
            media = existing_media.get(media_id)
            created = media is None
            if created:
                media = ShopifyProductMedia(
                    product=product,
                    shopify_media_id=media_id,
                    imported_at=timestamp,
                )

            media.media_type = media_payload.get("media_type", "unknown")
            media.alt_text = media_payload.get("alt_text", "")
            media.source_url = media_payload.get("source_url", "")
            media.preview_image_url = media_payload.get("preview_image_url", "")
            media.mime_type = media_payload.get("mime_type", "")
            media.position = media_payload.get("position", 0)
            media.width = media_payload.get("width")
            media.height = media_payload.get("height")
            media.raw_payload = media_payload.get("raw_payload", {})
            media.last_synced_at = timestamp
            media.deleted_at = None
            if media.imported_at is None:
                media.imported_at = timestamp
            media.save()

            stats["media_created" if created else "media_updated"] += 1

        stale_media = ShopifyProductMedia.objects.filter(
            product=product,
            deleted_at__isnull=True,
        ).exclude(shopify_media_id__in=incoming_media_ids)
        stats["media_deleted"] += stale_media.update(
            deleted_at=timestamp,
            last_synced_at=timestamp,
            updated_at=timestamp,
        )

        return stats

    @staticmethod
    def _serialize_local_product(product) -> dict:
        return {
            "id": product.id,
            "shopify_product_id": product.shopify_product_id,
            "title": product.title,
            "handle": product.handle,
            "description_html": product.description_html,
            "status": product.status,
            "tags": product.tags,
            "seo": {
                "title": product.seo_title,
                "description": product.seo_description,
            },
            "featured_image_url": product.featured_image_url,
            "total_inventory": product.total_inventory,
            "has_out_of_stock_variants": product.has_out_of_stock_variants,
            "is_gift_card": product.is_gift_card,
            "variant_count": product.variant_count,
            "media_count": product.media_count,
            "published_at": product.published_at.isoformat() if product.published_at else None,
            "shopify_created_at": (
                product.shopify_created_at.isoformat() if product.shopify_created_at else None
            ),
            "shopify_updated_at": (
                product.shopify_updated_at.isoformat() if product.shopify_updated_at else None
            ),
            "variants": [
                {
                    "shopify_variant_id": variant.shopify_variant_id,
                    "title": variant.title,
                    "sku": variant.sku,
                    "price_amount": str(variant.price_amount) if variant.price_amount is not None else None,
                    "inventory_quantity": variant.inventory_quantity,
                    "position": variant.position,
                    "featured_image_url": variant.featured_image_url,
                }
                for variant in product.variants.all()
            ],
            "media": [
                {
                    "shopify_media_id": media.shopify_media_id,
                    "media_type": media.media_type,
                    "alt_text": media.alt_text,
                    "source_url": media.source_url,
                    "preview_image_url": media.preview_image_url,
                    "mime_type": media.mime_type,
                    "position": media.position,
                    "width": media.width,
                    "height": media.height,
                }
                for media in product.media.all()
            ],
        }

    @staticmethod
    def _parse_decimal(value):
        if value in (None, ""):
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int(value):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None

        return parse_datetime(value)

    @staticmethod
    def _extract_webhook_product_id(payload: dict) -> str | None:
        if not isinstance(payload, dict):
            return None

        graphql_id = str(payload.get("admin_graphql_api_id") or "").strip()
        if graphql_id:
            return graphql_id

        raw_id = payload.get("id")
        if isinstance(raw_id, str) and raw_id.startswith("gid://"):
            return raw_id.strip()

        parsed_id = ShopifyProductService._parse_int(raw_id)
        if parsed_id is None:
            return None

        return f"gid://shopify/Product/{parsed_id}"
