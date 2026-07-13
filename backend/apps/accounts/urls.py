from django.urls import path

from .authentication import (
    LoginView,
    RefreshView,
    VerifyView,
)
from .views import (
    CurrentUserView,
    LogoutView,
)

app_name = "accounts"

urlpatterns = [path("login",LoginView.as_view(),name="login",),
                path("refresh",RefreshView.as_view(),name="refresh",),
                path("verify",VerifyView.as_view(),name="verify",),
                path("me",CurrentUserView.as_view(),name="current-user",),
                path("logout", LogoutView.as_view(), name="logout",),
]