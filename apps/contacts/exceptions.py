from rest_framework.exceptions import ValidationError
class ErrorExceptionCreation(Exception):
    """Raised when an error occurs during the creation of an exception."""
    pass

class PhoneAlreadyRegistered(ValidationError):
    """Phone is already registered!"""