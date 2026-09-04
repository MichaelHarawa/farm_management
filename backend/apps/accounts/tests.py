from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.finance.models import EmployeeProfile

from .models import AccountAuditEvent, Role, RoleChoices


User = get_user_model()


class SystemUserAdministrationTests(TestCase):
    def setUp(self):
        self.admin_role = Role.objects.create(slug=RoleChoices.ADMIN, name="Admin")
        self.worker_role = Role.objects.create(slug=RoleChoices.GENERAL_WORKER, name="Worker")
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
