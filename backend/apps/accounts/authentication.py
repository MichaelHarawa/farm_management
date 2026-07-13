
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from .serializers import (
    FarmTokenObtainPairSerializer,
)


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
    pass


class VerifyView(
    PublicTokenViewMixin,
    TokenVerifyView,
):
    pass