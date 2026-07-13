from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_system", "updated_at")
    list_filter = ("is_system",)
    search_fields = ("name", "slug")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Farm profile", {"fields": ("job_title", "department", "roles")}),
        ("Audit metadata", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")
    list_display = ("username", "email", "first_name", "last_name", "is_active", "role_list")
    list_filter = DjangoUserAdmin.list_filter + ("roles",)
    search_fields = ("username", "email", "first_name", "last_name", "department")
    filter_horizontal = DjangoUserAdmin.filter_horizontal + ("roles",)

    @admin.display(description="Roles")
    def role_list(self, obj: User) -> str:
        return ", ".join(obj.roles.values_list("name", flat=True)) or "-"
