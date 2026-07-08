from __future__ import annotations

from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import(
    Batch,
    InputCosts,
)

from .serializers import(
    BatchSerializer,
    InputCostsSerializer,
)

class BatchViewset(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    queryset = Batch.objects.all()

    @action(detail = True, methods=["get","post"], url_path="input_costs")
    def input_costs(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            input_costs = poultry_batch.input_costs.all().order_by("-created_at")
            serializer = InputCostsSerializer(input_costs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = InputCostsSerializer(
            data = request.data,
        )
        serializer.is_valid(raise_exception =True)

        input_cost = serializer.save(
            batch=poultry_batch,
          #  created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(
            InputCostsSerializer(input_cost).data, 
            status = status.HTTP_201_CREATED,
            )







