# pylint: disable=no-member
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import RegisterSerializer, CustomTokenSerializer
from apps.accounts.models import EmailVerification
from apps.accounts.service import AccountService, EmailVerificationService
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            user = AccountService.register_user(**serializer.validated_data)

            refresh = RefreshToken.for_user(user)

            return Response({
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "user_type": user.user_type
                },
                # "access": str(refresh.access_token),
                # "refresh": str(refresh)
            }, status=201)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class VerifyEmailView(APIView):
    def get(self, request, token):
        try:
            verification = EmailVerificationService.verify_email(token)
            return Response({"message": "Email verified successfully"}, status=200)
        except EmailVerification.DoesNotExist:
            return Response({"error": "Invalid token"}, status=400)

        

class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenSerializer