from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .authentication import (
    LoginView,
    RefreshView,
    VerifyView,
)
from .views import (
    CurrentUserView,
    LogoutView,
    SystemUserViewSet,
)

app_name = "accounts"

router = DefaultRouter()
router.register("administration/users", SystemUserViewSet, basename="system-user")

urlpatterns = [path("login",LoginView.as_view(),name="login",),
                path("refresh",RefreshView.as_view(),name="refresh",),
                path("verify",VerifyView.as_view(),name="verify",),
                path("me",CurrentUserView.as_view(),name="current-user",),
                path("logout", LogoutView.as_view(), name="logout",),
                path("", include(router.urls)),
]
