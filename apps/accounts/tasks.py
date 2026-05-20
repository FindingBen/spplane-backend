from celery import shared_task
from django.conf import settings    
from django.core.mail import send_mail


@shared_task
def send_verification_email_task(token, email):
    verification_url = f"https://spplane.app/verify-email/{token}"

    send_mail(
        subject="Verify your account",
        message=f"Click to verify: {verification_url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )


@shared_task
def send_new_user_notification_email_task(user_email, user_type, signup_source):
    notification_email = (
        getattr(settings, "NEW_USER_NOTIFICATION_EMAIL", "")
        or getattr(settings, "EMAIL_HOST_USER", "")
    )
    if not notification_email:
        return False

    send_mail(
        subject=f"New user registration: {user_email}",
        message=(
            "A new user registered on SendPerPlane.\n\n"
            f"Email: {user_email}\n"
            f"User type: {user_type}\n"
            f"Signup source: {signup_source}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification_email],
    )
    return True