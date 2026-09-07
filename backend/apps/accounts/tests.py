from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.finance.models import EmployeeProfile

from .models import AccountAuditEvent, Role, RoleChoices


User = get_user_model()


class SystemUserAdministrationTests(TestCase):
    def setUp(self):
        self.admin_role, _ = Role.objects.get_or_create(slug=RoleChoices.ADMIN, defaults={"name": "Admin"})
        self.worker_role, _ = Role.objects.get_or_create(slug=RoleChoices.GENERAL_WORKER, defaults={"name": "Worker"})
        self.stakeholder_role, _ = Role.objects.get_or_create(slug=RoleChoices.STAKE_HOLDER, defaults={"name": "Stakeholder"})
        self.admin = User.objects.create_user("administrator", "admin@example.com", "password123")
        self.admin.roles.add(self.admin_role)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_admin_can_create_system_user_and_link_loginless_employee(self):
        employee = EmployeeProfile.objects.create(
            employee_number="EMP-900", job_title="Stock clerk", employment_type="permanent",
            employment_start_date="2026-09-01", base_monthly_salary="100000.00",
        )
        response = self.client.post("/api/v1/auth/administration/users/", {
            "username": "stockclerk", "email": "stock@example.com", "password": "password123",
            "role_slugs": [RoleChoices.GENERAL_WORKER], "employee_profile_id": employee.pk,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        employee.refresh_from_db()
        self.assertEqual(employee.user.username, "stockclerk")
        self.assertTrue(AccountAuditEvent.objects.filter(target_user=employee.user, action="created").exists())

    def test_last_active_administrator_cannot_be_deactivated(self):
        response = self.client.patch(
            f"/api/v1/auth/administration/users/{self.admin.pk}/",
            {"is_active": False}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_grant_existing_user_read_only_finance_access(self):
        worker = User.objects.create_user("viewer", "viewer@example.com", "password123")
        worker.roles.add(self.worker_role)

        denied_client = APIClient()
        denied_client.force_authenticate(worker)
        self.assertEqual(
            denied_client.get("/api/v1/finance/dashboard").status_code,
            403,
        )

        response = self.client.patch(
            f"/api/v1/auth/administration/users/{worker.pk}/",
            {"role_slugs": [RoleChoices.STAKE_HOLDER]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        worker.refresh_from_db()
        self.assertEqual(worker.role_slugs, {RoleChoices.STAKE_HOLDER})
        self.assertEqual(
            denied_client.get("/api/v1/finance/dashboard").status_code,
            200,
        )
        self.assertTrue(
            AccountAuditEvent.objects.filter(
                target_user=worker,
                action="updated",
            ).exists()
        )

    def test_role_update_creates_a_missing_system_role_and_returns_current_roles(self):
        Role.objects.filter(slug=RoleChoices.FARM_MANAGER).delete()
        worker = User.objects.create_user("manager", "manager@example.com", "password123")
        worker.roles.add(self.worker_role)

        response = self.client.patch(
            f"/api/v1/auth/administration/users/{worker.pk}/",
            {"role_slugs": [RoleChoices.FARM_MANAGER]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {role["slug"] for role in response.data["roles"]},
            {RoleChoices.FARM_MANAGER},
        )
        worker.refresh_from_db()
        self.assertEqual(worker.role_slugs, {RoleChoices.FARM_MANAGER})

        manager_client = APIClient()
        manager_client.force_authenticate(worker)
        self.assertEqual(manager_client.get("/api/v1/finance/dashboard").status_code, 200)

    def test_role_update_preserves_all_explicitly_selected_roles(self):
        worker = User.objects.create_user("multi", "multi@example.com", "password123")
        worker.roles.add(self.worker_role)

        response = self.client.patch(
            f"/api/v1/auth/administration/users/{worker.pk}/",
            {
                "role_slugs": [
                    RoleChoices.FARM_SUPERVISOR,
                    RoleChoices.STAKE_HOLDER,
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {role["slug"] for role in response.data["roles"]},
            {RoleChoices.FARM_SUPERVISOR, RoleChoices.STAKE_HOLDER},
        )
