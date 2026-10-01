from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.serializers import TokenVerifySerializer
from rest_framework_simplejwt.tokens import UntypedToken
import uuid

from .models import MobileSession, SyncStreamState


def check_binding(token, user_id):
    keys = {"mobile_device_id", "mobile_session_id", "deployment_id"}
    if not any(key in token for key in keys):
        return None
    if not all(key in token for key in keys) or not settings.MOBILE_SYNC_CAPTURE:
        raise PermissionDenied({"code": "device_revoked", "message": "Mobile session unavailable."})
    try:
        uuid.UUID(str(token["mobile_session_id"]))
        uuid.UUID(str(token["mobile_device_id"]))
    except (ValueError, TypeError, AttributeError) as error:
        raise PermissionDenied({"code": "device_revoked", "message": "Invalid mobile binding."}) from error
    session = MobileSession.objects.select_related("device", "device__user").filter(
        pk=token["mobile_session_id"], device_id=token["mobile_device_id"], device__user_id=user_id,
        revoked_at__isnull=True, device__revoked_at__isnull=True, expires_at__gt=timezone.now(), device__user__is_active=True,
    ).first()
    stream = SyncStreamState.objects.filter(pk=1).first()
    if session is None or stream is None or str(stream.deployment_id) != token["deployment_id"]:
        raise PermissionDenied({"code": "device_revoked", "message": "Mobile session is revoked, expired or foreign."})
    return session


class FarmJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, token = result
            request.mobile_session = check_binding(token, user.pk)
            if request.mobile_session and not request.path.startswith("/api/v1/mobile-sync/"):
                if request.path.startswith("/api/v1/finance/") or (
                    request.method not in {"GET", "HEAD", "OPTIONS"} and request.path != "/api/v1/auth/logout"
                ):
                    raise PermissionDenied({"code": "command_unavailable", "message": "This mobile workflow is not enabled; use the advertised command API."})
        return result


class FarmTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        check_binding(refresh, refresh.get(settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")))
        return super().validate(attrs)


class FarmTokenVerifySerializer(TokenVerifySerializer):
    def validate(self, attrs):
        token = UntypedToken(attrs["token"])
        check_binding(token, token.get(settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")))
        return super().validate(attrs)
