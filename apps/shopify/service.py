import logging

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contacts.service import ContactService
from apps.shopify.models import ShopifyCustomerLink
from apps.shopify.queries import GET_CUSTOMERS_QUERY

logger = logging.getLogger(__name__)


class ShopifyGraphQLError(Exception):
    """Raised when Shopify GraphQL returns HTTP or top-level GraphQL errors."""


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
            "email": customer.get("email") or "",
            "phone": customer.get("phone") or "",
            "marketing_state": default_phone.get("marketingState") or "NONE",
            "created_at": customer.get("createdAt"),
            "updated_at": customer.get("updatedAt"),
        }

    @staticmethod
    def import_customers(
        shopify_profile,
        *,
        user,
        customers: list[dict],
        segment_ids: list[int] | None = None,
        contact_list: int | None = None,
    ) -> dict:
        """
        Imports selected Shopify customers into local contacts and links them
        back to ShopifyCustomerLink rows for future sync/webhook matching.
        """
        results = []

        for customer in customers:
            result = ShopifyCustomerService._import_single_customer(
                shopify_profile=shopify_profile,
                user=user,
                customer=customer,
                segment_ids=segment_ids,
                contact_list=contact_list,
            )
            results.append(result)

        summary = {
            "requested": len(customers),
            "imported": sum(1 for item in results if item["status"] == "imported"),
            "skipped": sum(1 for item in results if item["status"] == "skipped"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
        }

        return {
            "summary": summary,
            "results": results,
        }

    @staticmethod
    @transaction.atomic
    def _import_single_customer(
        *,
        shopify_profile,
        user,
        customer: dict,
        segment_ids: list[int] | None = None,
        contact_list: int | None = None,
    ) -> dict:
        shopify_customer_id = customer.get("id")
        phone = customer.get("phone") or ""

        if not shopify_customer_id:
            return {
                "status": "failed",
                "shopify_customer_id": "",
                "reason": "Customer id is required.",
            }

        if not phone:
            return {
                "status": "skipped",
                "shopify_customer_id": shopify_customer_id,
                "reason": "Customer has no phone number.",
            }

        try:
            contact = ContactService.create_contact(
                {
                    "phone": phone,
                    "first_name": customer.get("first_name", ""),
                    "last_name": customer.get("last_name", ""),
                    "source": "shopify",
                    "status": "subscribed",
                    "custom_attributes": {
                        "email": customer.get("email", ""),
                        "shopify_customer_id": shopify_customer_id,
                        "shop_domain": shopify_profile.shop_domain,
                    },
                    "segment_ids": segment_ids or [],
                    "contact_list": contact_list,
                },
                user=user,
            )
        except ValidationError as exc:
            logger.exception(
                "ShopifyCustomerService: failed to import customer %s for %s",
                shopify_customer_id,
                shopify_profile.shop_domain,
            )
            return {
                "status": "failed",
                "shopify_customer_id": shopify_customer_id,
                "reason": str(exc),
            }

        link, created = ShopifyCustomerLink.objects.get_or_create(
            shopify_profile=shopify_profile,
            shopify_customer_id=shopify_customer_id,
            defaults={
                "contact": contact,
                "first_name": customer.get("first_name", ""),
                "last_name": customer.get("last_name", ""),
                "email_snapshot": customer.get("email", ""),
                "phone_snapshot": phone,
                "marketing_state": customer.get("marketing_state", "NONE"),
                "imported_at": timezone.now(),
                "last_synced_at": timezone.now(),
                "raw_payload": customer,
            },
        )

        if not created:
            link.contact = contact
            link.first_name = customer.get("first_name", "")
            link.last_name = customer.get("last_name", "")
            link.email_snapshot = customer.get("email", "")
            link.phone_snapshot = phone
            link.marketing_state = customer.get("marketing_state", "NONE")
            link.last_synced_at = timezone.now()
            link.raw_payload = customer
            if link.imported_at is None:
                link.imported_at = timezone.now()
            link.save()

        return {
            "status": "imported",
            "shopify_customer_id": shopify_customer_id,
            "contact_id": contact.id,
            "created_link": created,
        }
