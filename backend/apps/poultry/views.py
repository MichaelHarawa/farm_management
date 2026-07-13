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
    Sales,
    Mortality,
    FeedUsage,
)

from .serializers import(
    BatchSerializer,
    InputCostsSerializer,
    SalesSerializer,
    MortalitySerializer,
    FeedUsageSerializer
)

class BatchViewset(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    queryset = Batch.objects.all()

    def get_serializer_class(self):
        if self.action == "input_costs":
            return InputCostsSerializer
        elif self.action == "sales":
            return SalesSerializer
        elif self.action == "mortality":
            return MortalitySerializer
        elif self.action == "feed_usage":
            return FeedUsageSerializer
        return BatchSerializer

    @action(detail=True, methods=["get", "post"], url_path="input_costs")
    def input_costs(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            input_costs = poultry_batch.input_costs.all().order_by(
                "-purchase_date",
                "-created_at",
            )
            serializer = self.get_serializer(input_costs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        input_cost = serializer.save(batch=poultry_batch)

        return Response(
            self.get_serializer(input_cost).data,
            status=status.HTTP_201_CREATED,
        )


    @action(detail=True, methods=["get", "post"], url_path="sales")
    def sales(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            sales = poultry_batch.sales_row.all().order_by("-created_at")
            serializer = self.get_serializer(sales, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sale = serializer.save(batch=poultry_batch)

        return Response(
            self.get_serializer(sale).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="mortality")
    def mortality(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            mortalities = poultry_batch.mortality_row.all().order_by("-created_at")
            serializer = self.get_serializer(mortalities, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        mortality = serializer.save(batch=poultry_batch)

        return Response(
            self.get_serializer(mortality).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="feed_usage")
    def feed_usage(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            feed_usages = poultry_batch.feed_usage_row.all().order_by("-created_at")
            serializer = self.get_serializer(feed_usages, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feed_usage = serializer.save(batch=poultry_batch)

        return Response(
            self.get_serializer(feed_usage).data,
            status=status.HTTP_201_CREATED,
        )






