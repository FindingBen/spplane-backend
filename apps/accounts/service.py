# pylint: disable=no-member
from datetime import timedelta
from .errors import InsufficientBalanceError, WalletDoesNotExistError,InvalidTransactionError
from django.utils.timezone import now
from .models import AuthProvider, User,EmailVerification, Wallet, CreditLedger
from .tasks import send_new_user_notification_email_task, send_verification_email_task
from django.db import transaction


class AccountService:
    @staticmethod
    @transaction.atomic
    def register_user(email, password, user_type):
        user = User.objects.create_user(
            email=email,
            password=password,
            is_active=False,
            user_type=user_type
        )

        AuthProvider.objects.create(
            user=user,
            provider="email",
            provider_user_id=user.email
        )

        Wallet.objects.create(
            user=user
        )

        verification = EmailVerification.objects.create(user=user)

        # trigger async email
        send_verification_email_task.delay(str(verification.token), user.email)
        send_new_user_notification_email_task.delay(user.email, user.user_type, "direct")

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
    

class WalletTransactionService:
    @staticmethod
    @transaction.atomic
    def top_up_wallet(user_id:str, amount:int, payment_refferance: dict = None):
        try:
            wallet = Wallet.objects.select_for_update().get(user_id=user_id)
        except Wallet.DoesNotExist:
            return WalletDoesNotExistError(f"Wallet for user {user_id} does not exist.")

        wallet.balance += amount
        wallet.save(update_fields=["balance", "updated_at"])
        payment_refferance = payment_refferance or {}
        CreditLedger.objects.create(
            wallet=wallet,
            entry_type="top_up",
            amount=amount,
            reference_id=str(
                payment_refferance.get("payment_order_id")
                or payment_refferance.get("provider_charge_id")
                or ""
            ),
            note=payment_refferance.get("note", "Wallet top-up")
        )
        return True
    
    @staticmethod
    @transaction.atomic
    def reserve_funds(user_id:str, amount:int, reference_id:str = ""):
        try:
            wallet = Wallet.objects.select_for_update().get(user_id=user_id)
        except Wallet.DoesNotExist:
            return WalletDoesNotExistError(f"Wallet for user {user_id} does not exist.")

        if wallet.balance - wallet.reserved < amount:
            return InsufficientBalanceError(amount, wallet.balance - wallet.reserved)

        wallet.reserved += amount
        wallet.save(update_fields=["reserved", "updated_at"])
        CreditLedger.objects.create(
            wallet=wallet,
            entry_type="reservation",
            amount=amount,
            reference_id=reference_id,
            note="Funds reserved for SMS sending"
        )

        return True
    
    @staticmethod
    @transaction.atomic
    def release_reservation(user_id: str, amount: int, reference_id: str = ""):
        wallet = Wallet.objects.select_for_update().get(user_id=user_id)
        wallet.reserved -= amount
        wallet.save(update_fields=["reserved", "updated_at"])
        CreditLedger.objects.create(
            wallet=wallet,
            entry_type="adjustment",
            amount=amount,
            reference_id=reference_id,
            note="Released over-reservation after send settlement",
        )
        return True

    @staticmethod
    @transaction.atomic
    def debit_funds(user_id:str, amount:int, reference_id:str = "", note:str = ""):
        try:
            wallet = Wallet.objects.select_for_update().get(user_id=user_id)
        except Wallet.DoesNotExist:
            return WalletDoesNotExistError(f"Wallet for user {user_id} does not exist.")

        if wallet.reserved < amount:
            return InsufficientBalanceError(amount, wallet.reserved)

        wallet.reserved -= amount
        wallet.balance -= amount
        wallet.save(update_fields=["balance", "reserved", "updated_at"])
        CreditLedger.objects.create(
            wallet=wallet,
            entry_type="debit",
            amount=amount,
            reference_id=reference_id,
            note=note
        )

        return True
    
    @staticmethod
    @transaction.atomic
    def refund_funds(user_id:str, amount:int, reference_id:str = "", note:str = ""):
        try:
            wallet = Wallet.objects.select_for_update().get(user_id=user_id)
        except Wallet.DoesNotExist:
            return WalletDoesNotExistError(f"Wallet for user {user_id} does not exist.")

        wallet.balance += amount
        wallet.save(update_fields=["balance", "updated_at"])
        CreditLedger.objects.create(
            wallet=wallet,
            entry_type="refund",
            amount=amount,
            reference_id=reference_id,
            note=note
        )

        return True