import logging
import uuid
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError
import requests
from vonage import Vonage, Auth
from vonage_messages.models import Sms as SmsMessagePayload
from vonage_http_client.errors import HttpRequestError

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.accounts.service import WalletTransactionService

logger = logging.getLogger(__name__)

# HTTP status codes from the Messages API that indicate a permanent failure.
# 429 (rate limit) and 5xx are transient and will be retried.
_PERMANENT_HTTP_CODES = {400, 401, 402, 403, 422}
_BLOCKED_DESTINATION_REGIONS = {"US", "CA"}


# ---------------------------------------------------------------------------
# Value object returned by VonageProvider.send()
# ---------------------------------------------------------------------------

@dataclass
class SendResult:
    success: bool
    provider_message_id: str
    error_code: str
    error_message: str
    is_permanent_failure: bool


# ---------------------------------------------------------------------------
# VonageProvider — thin adapter around the SDK.
# Business logic never imports vonage directly; it calls this class.
# ---------------------------------------------------------------------------

class VonageProvider:
    PRICING_URL = "https://rest.nexmo.com/account/get-full-pricing/outbound/sms"
    PRICING_CACHE_KEY = "vonage:country_prices"
    PRICING_CACHE_TTL = 6 * 3600  # 6 hours

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        auth = Auth(api_key=api_key, api_secret=api_secret)
        self._vonage = Vonage(auth=auth)

    @staticmethod
    def get_destination_region(value: str) -> str | None:
        import phonenumbers

        candidate = (value or "").strip()
        if not candidate:
            return None

        if candidate.isdigit():
            if candidate.startswith("0") or not 7 <= len(candidate) <= 15:
                return None
            candidate = f"+{candidate}"

        try:
            parsed = phonenumbers.parse(candidate, None)
        except phonenumbers.NumberParseException:
            return None

        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            return None

        return phonenumbers.region_code_for_number(parsed) or None

    @classmethod
    def _assert_supported_recipient(cls, value: str, *, field_name: str) -> None:
        region = cls.get_destination_region(value)
        if region in _BLOCKED_DESTINATION_REGIONS:
            raise ValueError(
                f"{field_name} to US and CA numbers is not supported yet."
            )

    @staticmethod
    def _normalize_msisdn(value: str, *, field_name: str, enforce_region_policy: bool = False) -> str:
        import phonenumbers

        candidate = (value or "").strip()
        if not candidate:
            raise ValueError(f"{field_name} is required.")

        if candidate.isdigit():
            if candidate.startswith("0") or not 7 <= len(candidate) <= 15:
                raise ValueError(f"{field_name} must be a valid E.164 phone number.")
            if enforce_region_policy:
                VonageProvider._assert_supported_recipient(candidate, field_name=field_name)
            return candidate

        try:
            parsed = phonenumbers.parse(candidate, None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError(f"{field_name} must be a valid E.164 phone number.") from exc

        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"{field_name} must be a valid E.164 phone number.")

        if enforce_region_policy:
            VonageProvider._assert_supported_recipient(candidate, field_name=field_name)

        return phonenumbers.format_number(
            parsed,
            phonenumbers.PhoneNumberFormat.E164,
        ).lstrip("+")

    @classmethod
    def _normalize_sender(cls, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            raise ValueError("Sender is required.")

        if any(character.isalpha() for character in candidate):
            return candidate

        return cls._normalize_msisdn(candidate, field_name="Sender")

    def send(self, from_: str, to: str, text: str, client_ref: str = "") -> SendResult:
        try:
            normalized_to = self._normalize_msisdn(
                to,
                field_name="Recipient phone",
                enforce_region_policy=True,
            )
            normalized_from = self._normalize_sender(from_)
            message = SmsMessagePayload(
                to=normalized_to,
                from_=normalized_from,
                text=text,
                client_ref=client_ref or None,
            )
            response = self._vonage.messages.send(message)
            return SendResult(
                success=True,
                provider_message_id=response.message_uuid,
                error_code="",
                error_message="",
                is_permanent_failure=False,
            )

        except (ValueError, PydanticValidationError) as exc:
            logger.warning("Vonage payload validation failed for %s: %s", to, exc)
            return SendResult(
                success=False,
                provider_message_id="",
                error_code="validation_error",
                error_message=str(exc),
                is_permanent_failure=True,
            )

        except HttpRequestError as exc:
            http_status = exc.response.status_code
            try:
                body = exc.response.json()
                error_code = str(body.get("error_code") or body.get("code") or http_status)
                error_message = body.get("detail") or body.get("title") or str(exc)
            except Exception:
                error_code = str(http_status)
                error_message = str(exc)
            return SendResult(
                success=False,
                provider_message_id="",
                error_code=error_code,
                error_message=error_message,
                is_permanent_failure=http_status in _PERMANENT_HTTP_CODES,
            )

        except Exception as exc:
            logger.exception("Vonage Messages API exception sending to %s", to)
            return SendResult(
                success=False,
                provider_message_id="",
                error_code="sdk_exception",
                error_message=str(exc),
                is_permanent_failure=False,  # treat as transient — will retry
            )

    def fetch_country_prices(self, force_refresh: bool = False) -> dict:
        """
        Returns a {country_code: price_per_sms} mapping.
        Cached in Django cache for PRICING_CACHE_TTL seconds.
        Falls back to the last successful cache entry if the API is down.
        """
        if not force_refresh:
            cached = cache.get(self.PRICING_CACHE_KEY)
            if cached:
                return cached

        try:
            resp = requests.get(
                self.PRICING_URL,
                params={"api_key": self._api_key, "api_secret": self._api_secret},
                timeout=10,
            )
            resp.raise_for_status()
            countries = resp.json().get("countries", [])
            prices = {
                c["countryCode"]: float(c.get("defaultPrice", 0))
                for c in countries
            }
            cache.set(self.PRICING_CACHE_KEY, prices, self.PRICING_CACHE_TTL)
            return prices

        except Exception as exc:
            logger.warning("Failed to refresh Vonage pricing: %s. Using cached fallback.", exc)
            fallback = cache.get(self.PRICING_CACHE_KEY)
            return fallback or {}


# ---------------------------------------------------------------------------
# PricingService — segment calculation and cost estimation.
# No Vonage SDK dependency — only uses the pricing data fetched above.
# ---------------------------------------------------------------------------

class MutualHelpers:
    @staticmethod
    def update_credits(sms_id:str, cost: int, user_id:str, wallet: WalletTransactionService):
        """
        Updates the user's wallet by debiting the cost of the send.
        Called from the finalize_sms_send task after all batches complete successfully.
        """
        
        reserve = wallet.reserve_funds(user_id, cost, reference_id=sms_id)
        if isinstance(reserve, Exception):
            logger.error(f"Failed to reserve funds for user {user_id}: {reserve}")
            raise reserve

        return True
    
    @staticmethod
    def assert_sendable(sms) -> None:
        if sms.status not in ("draft", "scheduled"):
            raise ValueError(
                f"Sms cannot be dispatched from status '{sms.status}'. "
                "Only draft or scheduled sends can be triggered."
            )
        if not sms.contact_list_id:
            raise ValueError("Sms has no contact list attached.")
        if not sms.sender:
            raise ValueError("Sms has no sender number set.")

class PricingService:

    @staticmethod
    def calculate_segments(text: str) -> int:
        """
        GSM-7 messages fit 160 chars per segment.
        Any non-ASCII character forces Unicode (UCS-2), limited to 70 chars/segment.
        """
        if any(ord(c) > 127 for c in text):
            return (len(text) + 69) // 70
        return (len(text) + 159) // 160

    @staticmethod
    def estimate_send_cost(contacts, body_template: str, provider: VonageProvider) -> dict:
        """
        Estimates total send cost for a given set of contacts and message body.
        Returns total_cost, estimated_credits (cost * 100 as integer), and per-recipient details.

        NOTE: This estimates against the template body without personalisation applied,
        which gives a conservative upper bound because personalised bodies may be shorter.
        """
        import phonenumbers
        from decimal import Decimal, ROUND_HALF_UP
        from phonenumbers import geocoder as ph_geocoder

        CREDIT_RATE = Decimal("100")
        prices = provider.fetch_country_prices()
        segments = PricingService.calculate_segments(body_template)
        total_cost = 0.0
        details = []

        for contact in contacts:
            try:
                parsed = phonenumbers.parse(contact.phone)
                country_code = ph_geocoder.region_code_for_number(parsed) or "US"
            except Exception:
                country_code = "US"

            price = prices.get(country_code, prices.get("US", 0.0))
            cost = price * segments
            total_cost += cost
            details.append({
                "phone": contact.phone,
                "country": country_code,
                "segments": segments,
                "segment_price": price,
                "total_price": round(cost, 6),
            })

        est_credits = (Decimal(str(total_cost)) * CREDIT_RATE).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        return {
            "total_cost": round(total_cost, 6),
            "recipients": len(details),
            "estimated_credits": est_credits,
            "details": details,
        }


# ---------------------------------------------------------------------------
# SmsSendingService — orchestrator.
#
# Responsibilities:
#   1. Validate the Sms is in a sendable state.
#   2. Filter eligible contacts from the attached contact list.
#   3. Bulk-create SmsRecipient rows (idempotent — skips existing phones).
#   4. Transition Sms status to "processing" inside an atomic block.
#   5. Enqueue per-batch Celery tasks.
#
# This class does NOT call Vonage directly — that happens inside the tasks.
# ---------------------------------------------------------------------------

class SmsSendingService:
    BATCH_SIZE = 200
    PROVIDER_NAME = "vonage"

    def __init__(self):
        self.provider = VonageProvider(
            api_key=settings.VONAGE_ID,
            api_secret=settings.VONAGE_TOKEN,
        )
        self.helper = MutualHelpers()

    # --- Public entry points ------------------------------------------------

    # def validate_reocurrent_dispatch(self,)

    def validate_and_dispatch(self, sms_id: str) -> dict:
        """
        Main entry point called by the API view or a scheduled-send task.
        Returns a summary dict with recipient_count and batch_count.
        Raises ValueError for invalid states or missing data.
        """
        from apps.sms.models import Sms

        sms = (
            Sms.objects
            .select_related("contact_list", "user")
            .get(id=sms_id)
        )
        
        self.helper.assert_sendable(sms)
        contacts = self._get_sendable_contacts(sms)

        #initiate wallet service once here to avoid circular imports with tasks.py which also needs it for refunds and adjustments after send completion
        wallet_service = WalletTransactionService()
        est_cost = self.estimate_cost(sms_id)
        
        with transaction.atomic():
            reserve_credits = self.helper.update_credits(sms_id=sms_id,
                                                    cost=est_cost["estimated_credits"],
                                                     user_id= str(sms.user_id),
                                                      wallet= wallet_service)
            if reserve_credits is not True:
                raise ValueError(f"Failed to reserve credits for this send: {reserve_credits}")
            recipient_ids = self._build_recipients(sms, contacts)
            sms.status = "processing"
            sms.provider = self.PROVIDER_NAME
            sms.save(update_fields=["status", "provider", "updated_at"])
            self._activate_campaign(sms.campaign_id)

        self._enqueue_batches(sms_id, recipient_ids)

        batch_count = -(-len(recipient_ids) // self.BATCH_SIZE)  # ceiling division
        return {
            "sms_id": str(sms_id),
            "recipient_count": len(recipient_ids),
            "batch_count": batch_count,
        }


    def estimate_cost(self, sms_id: str) -> dict:
        """
        Called before triggering a send so the frontend can show cost to the user.
        Does not modify any records.
        """
        from apps.sms.models import Sms

        sms = Sms.objects.select_related("contact_list").get(id=sms_id)
        contacts = self._get_sendable_contacts(sms)
        return PricingService.estimate_send_cost(contacts, sms.body, self.provider)

    def validate_send_request(self, sms_id: str) -> None:
        from apps.sms.models import Sms

        sms = (
            Sms.objects
            .select_related("contact_list", "user")
            .get(id=sms_id)
        )
        self._assert_sendable(sms)
        self._get_sendable_contacts(sms)

    def render_body(
        self,
        template: str,
        first_name: str,
        page_slug: str | None,
        access_token: str,
    ) -> str:
        """
        Renders the final per-recipient message body.
        Replaces {{first_name}} and {{page_link}} placeholders, then appends opt-out link.
        Called from the sending task so each recipient gets a personalised message.
        """
        frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")

        body = template.replace("{{first_name}}", first_name or "")

        if page_slug:
            page_url = f"{frontend_url}/sms/page/{page_slug}?t={access_token}"
            if "{{page_link}}" in body:
                body = body.replace("{{page_link}}", page_url)
            else:
                body = f"{body}\n{page_url}"

        opt_out_url = f"{frontend_url}/opt-out?t={access_token}"
        return f"{body}\n\nOpt-out: {opt_out_url}"

    # --- Private helpers ----------------------------------------------------

    def _assert_sendable(self, sms) -> None:
        if sms.status not in ("draft", "scheduled"):
            raise ValueError(
                f"Sms cannot be dispatched from status '{sms.status}'. "
                "Only draft or scheduled sends can be triggered."
            )
        if not sms.contact_list_id:
            raise ValueError("Sms has no contact list attached.")
        if not sms.sender:
            raise ValueError("Sms has no sender number set.")

    def _get_eligible_contacts(self, sms):
        from apps.contacts.models import Contact

        return (
            Contact.objects
            .filter(
                segment_memberships__contact_list=sms.contact_list,
                status="subscribed",
            )
            .only("id", "phone", "first_name")
            .distinct()
        )

    def _get_sendable_contacts(self, sms):
        contacts = list(self._get_eligible_contacts(sms))
        if not contacts:
            raise ValueError("No eligible (subscribed) contacts found in the contact list.")

        blocked_phones = [
            contact.phone
            for contact in contacts
            if self.provider.get_destination_region(contact.phone) in _BLOCKED_DESTINATION_REGIONS
        ]
        if blocked_phones:
            blocked_preview = ", ".join(blocked_phones[:3])
            blocked_suffix = ""
            if len(blocked_phones) > 3:
                blocked_suffix = f" and {len(blocked_phones) - 3} more"

            raise ValueError(
                "Sending to US and CA numbers is not supported yet. "
                f"Remove these contacts before sending: {blocked_preview}{blocked_suffix}."
            )

        return contacts

    def _build_recipients(self, sms, contacts) -> list[str]:
        """
        Bulk-creates SmsRecipient rows for all eligible contacts.
        Idempotent: contacts whose phone number already has a recipient row
        for this Sms are skipped so re-running is safe.
        Returns a list of recipient UUIDs (as strings) with status "queued".
        """
        from apps.sms.models import SmsRecipient

        existing_phones = set(
            SmsRecipient.objects.filter(sms=sms).values_list("phone", flat=True)
        )

        new_recipients = [
            SmsRecipient(
                sms=sms,
                contact=contact,
                phone=contact.phone,
                access_token=uuid.uuid4().hex,
                status="queued",
            )
            for contact in contacts
            if contact.phone not in existing_phones
        ]

        if new_recipients:
            SmsRecipient.objects.bulk_create(new_recipients)

        recipient_ids = list(
            SmsRecipient.objects
            .filter(sms=sms, status="queued")
            .values_list("id", flat=True)
        )
        return [str(rid) for rid in recipient_ids]

    def _activate_campaign(self, campaign_id) -> None:
        if not campaign_id:
            return
        from apps.campaign.models import Campaign

        Campaign.objects.filter(id=campaign_id).exclude(status="active").update(status="active")

    def _enqueue_batches(self, sms_id: str, recipient_ids: list[str]) -> None:
        """
        Dispatches recipient IDs as parallel Celery batch tasks.
        Uses a Celery chord so finalize_sms_send runs after all batches complete.
        """
        from celery import group
        from apps.sms.tasks import send_recipient_batch, finalize_sms_send

        batches = [
            send_recipient_batch.s(sms_id, recipient_ids[i: i + self.BATCH_SIZE])
            for i in range(0, len(recipient_ids), self.BATCH_SIZE)
        ]

        # chord: run all batches in parallel, then run finalize when all finish
        (group(batches) | finalize_sms_send.si(sms_id)).delay()


class SingleSendService:
    PROVIDER_NAME = "vonage"

    def __init__(self):
        self.provider = VonageProvider(
            api_key=settings.VONAGE_ID,
            api_secret=settings.VONAGE_TOKEN,
        )
        self.helper = MutualHelpers()
    """
    Service for triggering automated sends like welcome messages.
    Called from automation tasks when an automation execution starts.
    """
    def validate_and_send(self, customer_id: str, sms_id:str) -> None:
        from apps.sms.models import Sms
        from apps.contacts.models import Contact
        from apps.accounts.models import Wallet
    
        # check for user_id if exists in customer
        sms = Sms.objects.filter(id=sms_id).first()
        contact = Contact.objects.filter(id=customer_id).first()
        
        # Custom validation for single_send: check status and sender, but NOT contact_list
        if sms.status not in ("draft", "scheduled","processing"):
            raise ValueError(f"Sms cannot be dispatched from status '{sms.status}'. Only draft or scheduled sends can be triggered.")
        if not sms.sender:
            raise ValueError("Sms has no sender number set.")
        
        # self.build_recipient(sms, contact)
        wallet = Wallet.objects.filter(user_id=sms.user_id).first()
        wallet_service = WalletTransactionService()

        est_cost = self.estimate_price(sms_id, contact)
        print('cost')
        if wallet.balance - wallet.reserved < est_cost["estimated_credits"]:
            raise ValueError("Insufficient credits to send this message.")

        with transaction.atomic():
            reserve_credits = self.helper.update_credits(sms_id,est_cost["estimated_credits"], str(sms.user_id), wallet_service)
            if reserve_credits is not True:
                raise ValueError(f"Failed to reserve credits for this send: {reserve_credits}")
            sms.status = "processing"
            sms.provider = self.PROVIDER_NAME
            sms.save(update_fields=["status", "provider", "updated_at"])
            if sms.campaign_id:
                from apps.campaign.models import Campaign

                Campaign.objects.filter(id=sms.campaign_id).exclude(status="active").update(status="active")

        self.enqueue_send(sms_id=sms_id, customer_id=customer_id)

    def enqueue_send(self,sms_id:str, customer_id:str) -> None:
        from apps.sms.tasks import send_single_sms, finalize_sms_send

        _enque = send_single_sms.si(sms_id, customer_id)

        (_enque | finalize_sms_send.si(sms_id)).delay()
        
    def build_recipient(self, sms, contact):
        from apps.sms.models import Sms, SmsRecipient

        if contact.status != "subscribed":
            raise ValueError("Contact is not subscribed to receive messages.")
        recipient = SmsRecipient.objects.create(
                sms=sms,
                contact=contact,
                phone=contact.phone,
                access_token=uuid.uuid4().hex,
                status="queued",
            )
        return recipient
    
    def estimate_price(self, sms_id: str, contact) -> dict:
        """
        pricing service return {
            "total_cost": round(total_cost, 6),
            "recipients": len(details),
            "estimated_credits": est_credits,
            "details": details,
        }
        """
        from apps.sms.models import Sms

        sms = Sms.objects.get(id=sms_id)
        return PricingService.estimate_send_cost([contact], sms.body, VonageProvider(
            api_key=settings.VONAGE_ID,
            api_secret=settings.VONAGE_TOKEN,
        ))
    

    def render_body(
        self,
        template: str,
        first_name: str,
        page_slug: str | None,
        access_token: str,
    ) -> str:
        frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")

        body = template.replace("{{first_name}}", first_name or "")

        if page_slug:
            page_url = f"{frontend_url}/sms/page/{page_slug}?t={access_token}"
            if "{{page_link}}" in body:
                body = body.replace("{{page_link}}", page_url)
            else:
                body = f"{body}\n{page_url}"

        opt_out_url = f"{frontend_url}/opt-out?t={access_token}"
        return f"{body}\n\nOpt-out: {opt_out_url}"
