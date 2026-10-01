from django.db import transaction
from django.db import DatabaseError
from django.http import JsonResponse
from .errors import SyncError

from .writers import capture_enabled, sync_boundary


class SyncWriterMiddleware:
    """Web/admin outer transaction; acquire stream before any view domain locks.

    Push intentionally manages independent transactions per operation. Streaming
    mutations are unsupported; no I/O may occur while holding the stream lock.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        should_wrap = (capture_enabled() and request.method not in {"GET", "HEAD", "OPTIONS"}
                       and request.path.startswith(("/api/v1/", "/admin/"))
                       and not request.path.startswith(("/api/v1/mobile-sync/", "/api/v1/auth/login", "/api/v1/auth/refresh")))
        if not should_wrap:
            return self.get_response(request)
        try:
            with sync_boundary():
                response = self.get_response(request)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                return response
        except SyncError as error:
            return JsonResponse(error.detail, status=error.status_code)
        except DatabaseError:
            return JsonResponse({"code": "retry_later", "message": "Database request failed; do not assume the mutation was accepted."}, status=503)
