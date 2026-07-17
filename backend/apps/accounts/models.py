from __future__ import annotations

import uuid
from collections.abc import Iterable

from django.contrib.auth.models import AbstractUser
from django.db import models


class RoleChoices(models.TextChoices):
    FARM_MANAGER = "farm_manager", "Farm Manager"
    FARM_SUPERVISOR = "farm_supervisor", "Farm Supervisor"
    DIRECTOR = "director", "Director"
    STAKE_HOLDER = "stake_holder", "Stake Holder"
    ADMIN = "admin", "Admin"
    GENERAL_WORKER = "general_worker", "General Worker"


class Role(models.Model):
    slug = models.CharField(
        max_length=64,
        choices=RoleChoices.choices,
        unique=True,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField(unique=True)
    roles = models.ManyToManyField(
        Role,
        blank=True,
        related_name="users",
    )
    job_title = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def role_slugs(self) -> set[str]:
        if not self.pk:
            return set()

        return set(
            self.roles.values_list("slug", flat=True)
        )

    @property
    def has_admin_access(self) -> bool:
        return (
            self.is_superuser
            or RoleChoices.ADMIN in self.role_slugs
        )

    def has_role(
        self,
        role: str | RoleChoices,
    ) -> bool:
        if self.has_admin_access:
            return True

        role_value = (
            role.value
            if isinstance(role, RoleChoices)
            else role
        )

        return role_value in self.role_slugs

    def has_any_role(
        self,
        roles: Iterable[str | RoleChoices],
    ) -> bool:
        if self.has_admin_access:
            return True

        required_roles = {
            role.value
            if isinstance(role, RoleChoices)
            else role
            for role in roles
        }

        return bool(
            self.role_slugs.intersection(required_roles)
        )
