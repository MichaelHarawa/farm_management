from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class RoleChoices(models.TextChoices):
    FARM_MANAGER = "farm_manager", "Farm Manager" 
    FARM_SUPERVISOR = "farm_supervisor", "Farm Supervisor"
    DIRECTOR = "director", "Director"
    STAKE_HOLDER = "stake_holder", "Stake Holder"
    ADMIN = "admin", "Admin"


class Role(models.Model):
    slug = models.CharField(max_length=64, choices=RoleChoices.choices, unique=True)
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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    roles = models.ManyToManyField(Role, blank=True, related_name="users")
    job_title = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    REQUIRED_FIELDS = ["roles","department"]

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def role_slugs(self) -> set[str]:
        if not self.pk:
            return set()
        return set(self.roles.values_list("slug", flat=True))

    @property
    def has_superuser_role(self) -> bool:
        """
        This checks two things:
        1. Is the user a Django superuser?
        2. Does the user have the system role "superuser"?
        """
        return self.is_superuser or RoleChoices.SUPERUSER in self.role_slugs

    def has_role(self, role: str | RoleChoices) -> bool:
        """
        This checks whether the user has a specific role
        """
        return self.has_superuser_role or str(role) in self.role_slugs

    def has_any_role(self, roles: list[str] | tuple[str, ...] | set[str]) -> bool:
        """
        to get a boolean value if user has any/specified role from a list
        """
        if self.has_superuser_role:
            return True
        return bool(self.role_slugs.intersection({str(role) for role in roles}))
