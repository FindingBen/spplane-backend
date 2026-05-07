import logging

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.contacts.models import Contact
from apps.shopify.models import ShopifyCustomerLink
from apps.shopify.queries import GET_CUSTOMERS_QUERY

logger = logging.getLogger(__name__)


class ShopifyGraphQLError(Exception):
    """Raised when Shopify GraphQL returns HTTP or top-level GraphQL errors."""


class ShopifyCustomerImportStateError(Exception):
    """Raised when the local shop import state disallows another import."""


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
