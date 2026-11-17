from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import InterfaceError, OperationalError, ProgrammingError
from django.test import SimpleTestCase


COMMAND_MODULE = "apps.accounts.management.commands.wait_for_db"


class WaitForDatabaseTests(SimpleTestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.output = StringIO()
        self.connections = patch(
            f"{COMMAND_MODULE}.connections", {"default": self.connection}
        )
        self.connections.start()
        self.addCleanup(self.connections.stop)

    def test_ready_database_is_queried_and_connection_closed(self):
        with patch(f"{COMMAND_MODULE}.time.sleep") as sleep:
            call_command("wait_for_db", stdout=self.output)

        self.connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")
        self.connection.close.assert_called_once()
        sleep.assert_not_called()
        self.assertIn("Database is ready.", self.output.getvalue())

    def test_transient_dns_and_connection_failures_recover(self):
        self.connection.ensure_connection.side_effect = [
            OperationalError('could not translate host name "db" to address'),
            InterfaceError("connection lost"),
            None,
        ]
        with patch(f"{COMMAND_MODULE}.time.sleep") as sleep:
            call_command("wait_for_db", stdout=self.output)

        self.assertEqual(self.connection.ensure_connection.call_count, 3)
        self.assertEqual(self.connection.close.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("Database is ready.", self.output.getvalue())

    def test_query_failure_retries_with_a_fresh_connection(self):
        cursor = self.connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = [OperationalError("database starting"), None]
        with patch(f"{COMMAND_MODULE}.time.sleep"):
            call_command("wait_for_db", stdout=self.output)

        self.assertEqual(self.connection.ensure_connection.call_count, 2)
        self.assertEqual(self.connection.close.call_count, 2)

    def test_persistent_failure_exits_without_exposing_connection_details(self):
        self.connection.ensure_connection.side_effect = OperationalError("secret connection details")
        with (
            patch(f"{COMMAND_MODULE}.time.monotonic", side_effect=[0, 0, 3]),
            patch(f"{COMMAND_MODULE}.time.sleep") as sleep,
            self.assertRaisesMessage(CommandError, "Database unavailable after 3s") as error,
        ):
            call_command("wait_for_db", timeout=3, interval=5, stdout=self.output)

        sleep.assert_called_once_with(3)
        self.assertNotIn("secret connection details", str(error.exception))

    def test_non_connection_errors_fail_immediately(self):
        self.connection.ensure_connection.side_effect = ProgrammingError("invalid configuration")
        with (
            patch(f"{COMMAND_MODULE}.time.sleep") as sleep,
            self.assertRaises(ProgrammingError),
        ):
            call_command("wait_for_db", stdout=self.output)
        sleep.assert_not_called()

    def test_non_positive_options_are_rejected(self):
        for options in ({"timeout": 0}, {"timeout": -1}, {"interval": 0}, {"interval": -1}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command("wait_for_db", stdout=self.output, **options)
        self.connection.ensure_connection.assert_not_called()
