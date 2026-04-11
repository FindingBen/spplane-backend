from celery import shared_task
from django.conf import settings    
from django.core.mail import send_mail


@shared_task
def send_verification_email_task(token, email):
    verification_url = f"http://localhost:5173/verify-email/{token}"

    send_mail(
        subject="Verify your account",
        message=f"Click to verify: {verification_url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )