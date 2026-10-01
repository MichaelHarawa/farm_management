from rest_framework.exceptions import APIException


class SyncError(APIException):
    def __init__(self, code, message, status=400):
        self.status_code = status
        super().__init__({"code": code, "message": message}, code=code)
