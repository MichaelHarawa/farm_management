from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.finance.services.batch_lifecycle import (
    create_mortality_with_lifecycle,
    create_sale_with_lifecycle,
    recalculate_batch_status,
)
from apps.finance.services.profitability import create_final_snapshot

from .models import(
    Batch,
    BatchStatus,
    InputCosts,
    Sales,
    Mortality,
    FeedUsage,
    DrugsVaccination,
)

from .serializers import(
    BatchSerializer,
    InputCostsSerializer,
    SalesSerializer,
    MortalitySerializer,
    FeedUsageSerializer,
    DrugsVaccinationSerializer,
)

class BatchViewset(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    queryset = Batch.objects.select_related("created_by")
    permission_classes = (IsAuthenticated,)

    def perform_create(self, serializer):
        batch = serializer.save(created_by=self.request.user)
        recalculate_batch_status(batch)

    def save_with_current_user(self, serializer, **kwargs):
        return serializer.save(
            created_by=self.request.user,
            **kwargs,
        )

    def get_serializer_class(self):
        if self.action in {"input_costs", "feed_input_costs"}:
            return InputCostsSerializer
        elif self.action == "sales":
            return SalesSerializer
        elif self.action == "mortality":
            return MortalitySerializer
        elif self.action == "feed_usage":
            return FeedUsageSerializer
        elif self.action == "drugs_vaccine":
            return DrugsVaccinationSerializer
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

        input_cost = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(input_cost).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="feed_input_costs")
    def feed_input_costs(self, request, pk=None):
        poultry_batch = self.get_object()
        input_costs = poultry_batch.input_costs.filter(
            category__icontains="feed",
        ).order_by(
            "-purchase_date",
            "-created_at",
        )
        serializer = self.get_serializer(input_costs, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


    @action(detail=True, methods=["get", "post"], url_path="sales")
    def sales(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            sales = poultry_batch.sales_row.all().order_by("-created_at")
            serializer = self.get_serializer(sales, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sale = create_sale_with_lifecycle(
                batch_id=poultry_batch.pk,
                created_by=request.user,
                **serializer.validated_data,
            )
        except ValueError as error:
            raise ValidationError({"quantity_sold": str(error)}) from error
        if sale.batch.status == BatchStatus.CLOSED:
            create_final_snapshot(sale.batch, generated_by=request.user)

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

        try:
            mortality = create_mortality_with_lifecycle(
                batch_id=poultry_batch.pk,
                created_by=request.user,
                **serializer.validated_data,
            )
        except ValueError as error:
            raise ValidationError({"quantity_dead": str(error)}) from error
        if mortality.batch.status == BatchStatus.CLOSED:
            create_final_snapshot(mortality.batch, generated_by=request.user)

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

        feed_usage = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(feed_usage).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="drugs_vaccine")
    def drugs_vaccine(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            vaccinations = poultry_batch.vaccination_row.all().order_by(
                "-vaccination_date",
                "-created_at",
            )
            serializer = self.get_serializer(vaccinations, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vaccination = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(vaccination).data,
            status=status.HTTP_201_CREATED,
        )






