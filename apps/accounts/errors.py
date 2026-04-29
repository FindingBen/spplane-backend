class DomainError(Exception):
    """Base class for domain-specific errors."""
    pass

class WalletDoesNotExistError(DomainError):
    """Raised when a user's wallet is not found."""
    def __init__(self, user_id):
        super().__init__(f"Wallet does not exist for user ID {user_id}")
        self.user_id = user_id

class InsufficientBalanceError(DomainError):
    """Raised when a user tries to reserve or debit more credits than available."""
    def __ini__(self, amount: int, available:int):
        super().__init__(f"Insufficient balance: tried to reserve/debit {amount} credits but only {available} available.")

        self.amount = amount
        self.available = available

class InvalidTransactionError(DomainError):
    """Raised when a transaction cannot be completed due to invalid state or parameters."""
    def __init__(self, message: str):
        super().__init__(f"Invalid transaction: {message}")