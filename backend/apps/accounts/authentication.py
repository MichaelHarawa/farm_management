
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from .serializers import (
    FarmTokenObtainPairSerializer,
)
from apps.mobile_sync.authentication import FarmTokenRefreshSerializer, FarmTokenVerifySerializer


class PublicTokenViewMixin:
    authentication_classes = ()
    permission_classes = (AllowAny,)


class LoginView(
    PublicTokenViewMixin,
    TokenObtainPairView,
):
    serializer_class = (
        FarmTokenObtainPairSerializer
    )


class RefreshView(
    PublicTokenViewMixin,
    TokenRefreshView,
):
    serializer_class = FarmTokenRefreshSerializer


class VerifyView(
    PublicTokenViewMixin,
    TokenVerifyView,
):
    serializer_class = FarmTokenVerifySerializer
