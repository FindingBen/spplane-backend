import logging
from apps.accounts.service import WalletTransactionService
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# dispatch_sms_send
#
# Thin async wrapper around SmsSendingService.validate_and_dispatch().
# Call this from the API view so the request returns immediately while
# recipient creation and batch enqueueing happen in a worker process.
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def dispatch_sms_send(self, sms_id: str) -> dict:
    """
    Entry-point task. Creates SmsRecipient rows, transitions Sms to
    'processing', and enqueues send_recipient_batch tasks.
    """
    from apps.sms.sending_service import SmsSendingService

    try:
        service = SmsSendingService()
        return service.validate_and_dispatch(sms_id)
    except ValueError as exc:
        # Business-logic errors (wrong status, no contacts, etc.) should not
        # be retried — they require a human to fix the data first.
        logger.error("dispatch_sms_send: validation error for sms %s: %s", sms_id, exc)
        _mark_sms_failed(sms_id)
        raise
    except Exception as exc:
        logger.exception("dispatch_sms_send: unexpected error for sms %s", sms_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _mark_sms_failed(sms_id)
            raise


# ---------------------------------------------------------------------------
# send_recipient_batch
#
# Core sending task. Processes one batch of SmsRecipient IDs.
# Each recipient is sent individually so failures are isolated.
#
# Retry strategy:
#   - Permanent provider errors (wrong number, barred, etc.): no retry,
#     recipient is marked 'failed' immediately.
#   - Transient errors (throttled, network, SDK exception): retried with
#     exponential back-off up to max_retries.
#   - acks_late=True: if the worker crashes mid-batch the task is redelivered.
#     Idempotency is guaranteed by filtering on status="queued".
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    acks_late=True,
)
def send_recipient_batch(self, sms_id: str, recipient_ids: list) -> dict:
    """
    Sends one batch of SmsRecipient rows via Vonage.
    Updates each recipient's status and creates SmsEvent rows.
    Returns a summary dict for the chord result.
    """
    from django.conf import settings
    from apps.sms.models import Sms, SmsRecipient, SmsEvent
    from apps.sms.sending_service import VonageProvider, SmsSendingService

    try:
        sms = Sms.objects.get(id=sms_id)
    except Sms.DoesNotExist:
        logger.error("send_recipient_batch: Sms %s not found, skipping.", sms_id)
        return {"skipped": True}

    # Resolve the hosted page slug once for the whole batch.
    page_slug = None
    try:
        page_slug = sms.page.public_slug
    except Exception:
        pass  # SMS without a hosted page is fine

    provider = VonageProvider(
        api_key=settings.VONAGE_ID,
        api_secret=settings.VONAGE_TOKEN,
    )
    service = SmsSendingService()

    # Only process recipients that are still queued (idempotency guard).
    recipients = (
        SmsRecipient.objects
        .select_related("contact")
        .filter(id__in=recipient_ids, status="queued")
    )

    now = timezone.now()
    events_to_create = []
    transient_failures = []
    sent_count = 0
    failed_count = 0

    for recipient in recipients:
        first_name = recipient.contact.first_name if recipient.contact else ""
        body = service.render_body(
            sms.body,
            first_name,
            page_slug,
            recipient.access_token,
        )

        result = provider.send(
            from_=sms.sender,
            to=recipient.phone,
            text=body,
            # client_ref encodes tracking_id + recipient so Vonage DLR
            # callbacks can be mapped back to the exact recipient row.
            client_ref=f"{sms.tracking_id}-{str(recipient.id)[:8]}",
        )

        if result.success:
            recipient.status = "sent"
            recipient.provider_message_id = result.provider_message_id
            recipient.provider_status = "sent"
            recipient.error_code = ""
            recipient.error_message = ""
            sent_count += 1
        elif result.is_permanent_failure:
            recipient.status = "failed"
            recipient.provider_status = "failed"
            recipient.error_code = result.error_code
            recipient.error_message = result.error_message
            failed_count += 1
        else:
            # Transient — keep status="queued" so a retry can pick it up.
            recipient.error_code = result.error_code
            recipient.error_message = result.error_message
            transient_failures.append(str(recipient.id))

        recipient.save(update_fields=[
            "status",
            "provider_message_id",
            "provider_status",
            "error_code",
            "error_message",
            "updated_at",
        ])

        event_type = "sent" if result.success else "failed"
        events_to_create.append(SmsEvent(
            sms=sms,
            recipient=recipient,
            event_type=event_type,
            metadata={
                "provider_message_id": result.provider_message_id,
                "error_code": result.error_code,
                "error_message": result.error_message,
            },
            occurred_at=now,
        ))

    if events_to_create:
        SmsEvent.objects.bulk_create(events_to_create)

    logger.info(
        "send_recipient_batch sms=%s sent=%d failed=%d transient=%d",
        sms_id, sent_count, failed_count, len(transient_failures),
    )

    # Retry only the transient failures with exponential back-off.
    if transient_failures:
        try:
            raise self.retry(
                args=[sms_id, transient_failures],
                countdown=2 ** self.request.retries * 60,
            )
        except self.MaxRetriesExceededError:
            logger.warning(
                "send_recipient_batch: retries exhausted for %d recipients in sms %s. "
                "Marking as failed.",
                len(transient_failures), sms_id,
            )
            SmsRecipient.objects.filter(id__in=transient_failures).update(
                status="failed",
                error_code="max_retries_exceeded",
                updated_at=timezone.now(),
            )

    return {"sent": sent_count, "failed": failed_count}


# ---------------------------------------------------------------------------
# finalize_sms_send
#
# Runs as the chord callback after all send_recipient_batch tasks complete.
# Rolls up the final Sms.status from individual recipient statuses.
# Never overwrites a status that is already 'cancelled'.
# ---------------------------------------------------------------------------

@shared_task(bind=True)
def finalize_sms_send(self, sms_id: str) -> None:
    """
    Runs after all send_recipient_batch tasks complete (chord callback).

    Does two things:
      1. Rolls up the final Sms.status from recipient states.
      2. Settles credits:
           - Debits the actual cost (successful recipients only).
           - Releases any over-reservation (estimated - actual).
    """
    from decimal import Decimal
    from django.db.models import Count
    from django.conf import settings
    from apps.sms.models import Sms, SmsRecipient
    from apps.accounts.models import CreditLedger
    from apps.sms.sending_service import VonageProvider, PricingService

    try:
        sms = Sms.objects.select_related("user").get(id=sms_id)
    except Sms.DoesNotExist:
        logger.error("finalize_sms_send: Sms %s not found.", sms_id)
        return

    if sms.status == "cancelled":
        logger.info("finalize_sms_send: Sms %s is cancelled, skipping.", sms_id)
        return

    # ------------------------------------------------------------------
    # 1. Roll up final Sms status
    # ------------------------------------------------------------------
    status_counts = {
        row["status"]: row["count"]
        for row in (
            SmsRecipient.objects
            .filter(sms=sms)
            .values("status")
            .annotate(count=Count("id"))
        )
    }

    total = sum(status_counts.values())
    terminal_success = status_counts.get("sent", 0) + status_counts.get("delivered", 0)
    terminal_failure = status_counts.get("failed", 0) + status_counts.get("undelivered", 0)

    if terminal_success == total:
        final_status = "sent"
    elif terminal_failure == total:
        final_status = "failed"
    else:
        final_status = "partial"

    sms.status = final_status
    sms.sent_at = timezone.now()
    sms.save(update_fields=["status", "sent_at", "updated_at"])

    logger.info(
        "finalize_sms_send: sms %s → %s (total=%d success=%d failed=%d)",
        sms_id, final_status, total, terminal_success, terminal_failure,
    )

    # ------------------------------------------------------------------
    # 2. Settle credits
    #
    # Flow:
    #   a. Fetch the reserved amount from the ledger (set at dispatch time).
    #   b. Compute actual cost from successfully sent recipients.
    #   c. Debit the actual cost  → reduces both balance and reserved.
    #   d. Release leftover reservation (estimated - actual) → reduces reserved only.
    # ------------------------------------------------------------------
    try:
        credit_rate = Decimal(str(getattr(settings, "CREDIT_RATE", "100")))
        user_id = str(sms.user_id)

        # a. How much was reserved for this send?
        reservation_entry = (
            CreditLedger.objects
            .filter(
                wallet__user=sms.user,
                entry_type="reservation",
                reference_id=sms_id,
            )
            .order_by("-created_at")
            .first()
        )

        if reservation_entry is None:
            logger.warning(
                "finalize_sms_send: no reservation ledger entry found for sms %s, "
                "skipping credit settlement.",
                sms_id,
            )
            return

        estimated_credits = Decimal(str(reservation_entry.amount))

        # b. Compute actual cost — only for successfully sent recipients.
        successful_phones = list(
            SmsRecipient.objects
            .filter(sms=sms, status__in=("sent", "delivered"))
            .values_list("phone", flat=True)
        )

        if successful_phones:
            provider = VonageProvider(
                api_key=settings.VONAGE_ID,
                api_secret=settings.VONAGE_TOKEN,
            )
            prices = provider.fetch_country_prices()
            segments = PricingService.calculate_segments(sms.body)

            import phonenumbers
            from phonenumbers import geocoder as ph_geocoder

            actual_cost_dollars = Decimal("0")
            for phone in successful_phones:
                try:
                    parsed = phonenumbers.parse(phone)
                    country = ph_geocoder.region_code_for_number(parsed) or "US"
                except Exception:
                    country = "US"
                price = Decimal(str(prices.get(country, prices.get("US", 0))))
                actual_cost_dollars += price * segments

            actual_credits = (actual_cost_dollars * credit_rate).quantize(Decimal("0.0001"))
        else:
            # Every recipient failed — actual cost is zero.
            actual_credits = Decimal("0")

        # c. Debit actual cost.
        if actual_credits > 0:
            WalletTransactionService.debit_funds(
                user_id,
                actual_credits,
                reference_id=sms_id,
                note=f"SMS send debit — {terminal_success} messages sent",
            )

        # d. Release any over-reservation.
        over_reserved = estimated_credits - actual_credits
        if over_reserved > 0:
            WalletTransactionService.release_reservation(
                user_id,
                over_reserved,
                reference_id=sms_id,
            )

        logger.info(
            "finalize_sms_send: credit settlement sms=%s estimated=%s actual=%s released=%s",
            sms_id, estimated_credits, actual_credits,
            over_reserved if over_reserved > 0 else 0,
        )

    except Exception:
        # Settlement failure must not crash the task — the send already happened.
        # Log it loudly so it can be reconciled manually.
        logger.exception(
            "finalize_sms_send: credit settlement FAILED for sms %s — "
            "send status saved, manual reconciliation required.",
            sms_id,
        )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _mark_sms_failed(sms_id: str) -> None:
    """Silently marks an Sms record as failed. Used in error paths."""
    try:
        from apps.sms.models import Sms
        Sms.objects.filter(id=sms_id).update(
            status="failed",
            updated_at=timezone.now(),
        )
    except Exception:
        logger.exception("_mark_sms_failed: could not update sms %s", sms_id)
