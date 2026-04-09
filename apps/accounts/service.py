# pylint: disable=no-member
from datetime import timedelta
from django.utils.timezone import now
from .models import AuthProvider, User,EmailVerification
from .tasks import send_verification_email_task
from django.db import transaction


class AccountService:
    @staticmethod
    @transaction.atomic
    def register_user(email, password, user_type):
        user = User.objects.create_user(
            email=email,
            password=password,
            user_type=user_type
        )

        AuthProvider.objects.create(
            user=user,
            provider="email",
            provider_user_id=user.email
        )

        verification = EmailVerification.objects.create(user=user)

        # trigger async email
        send_verification_email_task.delay(str(verification.token), user.email)

        return user
    
class EmailVerificationService:
    @staticmethod
    def verify_email(token):
        try:
            verification = EmailVerification.objects.get(token=token, is_used=False)
            if verification.created_at < now() - timedelta(hours=24):
                return 'error: token expired'
            
        except EmailVerification.DoesNotExist:
            return False

        user = verification.user
        user.is_active = True
        user.save()

        verification.is_used = True
        verification.save()

        return True