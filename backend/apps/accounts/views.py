from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    CurrentUserSerializer,
    LogoutSerializer,
)


class CurrentUserView(RetrieveAPIView):
    serializer_class = CurrentUserSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )
        serializer.save()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )