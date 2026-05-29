import logging

from .serializers import SmsEventSerializer,SmsSerializer,SmsPageSerializer,SmsPublicPageSerializer,SmsRecipientSerializer,SmsPageActionSerializer,QRCodeSerializer
from apps.sms.service import SmsPageActionService,SmsService,SmsEventService,SmsRecipientService,SmsPageService, QrCodeService
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.utils import timezone

logger = logging.getLogger(__name__)

# Create your views here.


class SmsViewSet(viewsets.ModelViewSet):
    serializer_class = SmsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsService.get_smses_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms = SmsService.create_sms(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms = SmsService.update_sms(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsService.delete_sms(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        from apps.sms.tasks import dispatch_sms_send
        from apps.sms.sending_service import SmsSendingService

        instance = self.get_object()

        if str(instance.user_id) != str(request.user.id):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        if instance.status not in ("draft", "scheduled"):
            return Response(
                {"error": f"Cannot send an SMS in '{instance.status}' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            SmsSendingService().validate_send_request(str(instance.id))
            dispatch_sms_send.delay(str(instance.id))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"detail": "Send queued.", "sms_id": str(instance.id)}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="estimate-cost")
    def estimate_cost(self, request, pk=None):
        from apps.sms.sending_service import SmsSendingService

        instance = self.get_object()

        if str(instance.user_id) != str(request.user.id):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        try:
            estimate = SmsSendingService().estimate_cost(str(instance.id))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(estimate, status=status.HTTP_200_OK)


class SmsPageViewSet(viewsets.ModelViewSet):
    serializer_class = SmsPageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsPageService.get_all_sms_pages()

    def create(self, request, *args, **kwargs):
        return Response(
            {'detail': 'SMS pages are created automatically when an SMS is created.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_page = SmsPageService.update_sms_page(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_page)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsPageService.delete_sms_page(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsPageActionViewSet(viewsets.ModelViewSet):
    serializer_class = SmsPageActionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsPageActionService.get_all_sms_page_actions()

    def create(self, request, *args, **kwargs):
        return Response(
            {'detail': 'SMS page actions are created automatically when an SMS is created.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_page_action = SmsPageActionService.update_sms_page_action(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_page_action)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsPageActionService.delete_sms_page_action(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsRecipientViewSet(viewsets.ModelViewSet):
    serializer_class = SmsRecipientSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsRecipientService.get_all_sms_recipients()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_recipient = SmsRecipientService.create_sms_recipient(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_recipient)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_recipient = SmsRecipientService.update_sms_recipient(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_recipient)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsRecipientService.delete_sms_recipient(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsEventViewSet(viewsets.ModelViewSet):
    serializer_class = SmsEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsEventService.get_all_sms_events()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_event = SmsEventService.create_sms_event(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_event)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_event = SmsEventService.update_sms_event(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_event)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsEventService.delete_sms_event(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)

class QrCodeViewset(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        try:
            if request.user is None:
                return Response({'error': 'User not authenticated.'}, status=status.HTTP_401_UNAUTHORIZED)
            
            qr_code = QrCodeService.retrieve_or_generate_qr_code_for_user(request.user)
            return Response({'qr_code_url': qr_code.qr_image_url}, status=status.HTTP_200_OK)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, format=None):
        try:
            serializer = QRCodeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            qr = QrCodeService.create_qr_code(serializer.validated_data, request.user)
            if qr:
                return Response({'qr_code_url': qr.qr_image_url}, status=status.HTTP_201_CREATED)
            return Response({'error': 'Unable to create QR code.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PublicSmsPageView(APIView):
    """Public endpoint for serving an SMS hosted page snapshot.

    URL: GET /api/sms/public/page/<slug>/?t=<access_token>
    - If the page requires a token, `t` must be provided and valid for a
      recipient row on the associated Sms.
    - Records a `page_view` SmsEvent and updates the recipient `page_opened_at`.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug=None):
        from apps.sms.models import SmsPage, SmsRecipient

        token = request.query_params.get('t')

        page = SmsPage.objects.select_related('sms').filter(public_slug=slug).first()
        if page is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # If token is required, validate it against recipients for the SMS
        recipient = None
        if page.requires_token:
            if not token:
                return Response({'detail': 'Access token required.'}, status=status.HTTP_401_UNAUTHORIZED)
            recipient = SmsRecipient.objects.filter(sms=page.sms, access_token=token).first()
            if recipient is None:
                return Response({'detail': 'Invalid access token.'}, status=status.HTTP_403_FORBIDDEN)

        # Record open event and recipient open time (if a recipient was located)
        if recipient is not None:
            if recipient.page_opened_at is None:
                recipient.page_opened_at = timezone.now()
                recipient.save(update_fields=['page_opened_at', 'updated_at'])
            try:
                SmsEventService.create_sms_event({
                    'sms': page.sms,
                    'recipient': recipient,
                    'event_type': 'page_view',
                    'occurred_at': timezone.now(),
                })
            except Exception:
                # Don't block the page render if event recording fails; log elsewhere.
                pass

        serializer = SmsPublicPageSerializer(page)
        return Response(serializer.data)

# ---------------------------------------------------------------------------
# Vonage Messages API delivery webhook
# POST /sms/delivery
# ---------------------------------------------------------------------------

# Maps Vonage Messages API DLR statuses to our internal SmsRecipient statuses
# and the corresponding SmsEvent event_type.
_VONAGE_STATUS_MAP = {
    #  vonage_status    recipient_status   event_type
    "delivered":      ("delivered",       "delivered"),
    "rejected":       ("undelivered",     "failed"),
    "undeliverable":  ("undelivered",     "failed"),
    "submitted":      ("sent",            "sent"),
}


class VonageDeliveryWebhookView(APIView):
    """Receives delivery receipt (DLR) callbacks from Vonage Messages API.

    Vonage posts to this endpoint for every status update. We always
    return HTTP 200 so Vonage does not retry — any internal error is
    logged instead of surfaced.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.sms.models import SmsRecipient, SmsEvent

        payload = request.data
        message_uuid = payload.get("message_uuid")
        vonage_status = payload.get("status")

        if not message_uuid or not vonage_status:
            logger.warning("VonageDeliveryWebhook: missing message_uuid or status — %s", payload)
            return Response(status=status.HTTP_200_OK)

        internal_status = _VONAGE_STATUS_MAP.get(vonage_status)
        if internal_status is None:
            # Unknown / intermediate status — acknowledge and ignore.
            logger.debug("VonageDeliveryWebhook: unhandled status '%s' for %s", vonage_status, message_uuid)
            return Response(status=status.HTTP_200_OK)

        recipient_status, event_type = internal_status

        try:
            recipient = SmsRecipient.objects.select_related("sms").get(
                provider_message_id=message_uuid
            )
        except SmsRecipient.DoesNotExist:
            logger.warning("VonageDeliveryWebhook: no recipient for message_uuid %s", message_uuid)
            return Response(status=status.HTTP_200_OK)
        except Exception:
            logger.exception("VonageDeliveryWebhook: DB error looking up %s", message_uuid)
            return Response(status=status.HTTP_200_OK)

        try:
            update_fields = ["status", "provider_status", "updated_at"]
            recipient.status = recipient_status
            recipient.provider_status = vonage_status

            if recipient_status == "delivered" and recipient.delivered_at is None:
                recipient.delivered_at = timezone.now()
                update_fields.append("delivered_at")

            error_info = payload.get("error", {})
            if error_info:
                recipient.error_code = str(error_info.get("code", ""))
                recipient.error_message = error_info.get("reason", "")
                update_fields += ["error_code", "error_message"]

            recipient.save(update_fields=update_fields)

            SmsEvent.objects.create(
                sms=recipient.sms,
                recipient=recipient,
                event_type=event_type,
                metadata={
                    "message_uuid": message_uuid,
                    "vonage_status": vonage_status,
                    "error": error_info,
                },
                occurred_at=timezone.now(),
            )

            logger.info(
                "VonageDeliveryWebhook: %s → %s (internal: %s)",
                message_uuid, vonage_status, internal_status,
            )
        except Exception:
            logger.exception("VonageDeliveryWebhook: failed to process DLR for %s", message_uuid)

        return Response(status=status.HTTP_200_OK)

