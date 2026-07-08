from django.http import JsonResponse


def api_index(request):
    return JsonResponse(
        {
            "name": "Farm Management API",
            "status": "ok",
            "endpoints": {
                "health": "/health/",
                "csrf": "/api/v1/auth/csrf/",
                "login": "/api/v1/auth/login/",
                "logout": "/api/v1/auth/logout/",
                "me": "/api/v1/auth/me/",
                "requests": "/api/v1/batch/",
                "roles": "/api/v1/auth/roles/",
                "users": "/api/v1/auth/users/",
                "audit_logs": "/api/v1/audit/logs/",
                "admin": "/admin/",
            },
        }
    )


def health(request):
    return JsonResponse({"status": "ok"})
