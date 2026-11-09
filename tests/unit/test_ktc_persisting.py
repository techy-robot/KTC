# Unit tests for ktc_persisting.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import os
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_persisting import KtcPersisting


class TestKtcPersisting(KtcTestCase):
    """Test suite for persistent storage I/O and batch saving."""

    def setUp(self) -> None:
        super().setUp()
        self.var_path = os.path.join(self.harness.temp_dir, "test_variables.cfg")
        self.harness.file_config.sections["ktc_persisting"] = {
            "filename": self.var_path,
        }
        self.cfg = self.harness.get_config_wrapper("ktc_persisting")
        self.persisting = KtcPersisting(self.cfg)

    def test_file_creation(self) -> None:
        """Verify variables file is created if it does not exist."""
        self.assertTrue(os.path.exists(self.var_path))

    def test_save_and_load_variables(self) -> None:
        """Verify variable saving, file writing, and reloading."""
        self.persisting.save_variable("test_str", "'hello'")
        self.persisting.save_variable("test_int", "42")
        self.persisting.save_variable("test_list", "[1.0, 2.0, 3.0]")

        self.assertTrue(self.persisting.ready_to_save)

        # Trigger timer write event
        self.persisting._save_changes_timer_event(self.harness.printer.reactor.monotonic())
        self.assertFalse(self.persisting.ready_to_save)

        # Create new instance to reload from file
        reloaded = KtcPersisting(self.cfg)
        vars_sec = reloaded.content.get("Variables", {})
        self.assertEqual(vars_sec.get("test_str"), "hello")
        self.assertEqual(vars_sec.get("test_int"), 42)
        self.assertEqual(vars_sec.get("test_list"), [1.0, 2.0, 3.0])

    def test_delayed_timer_save(self) -> None:
        """Verify that changes are automatically written after timer delay."""
        self.persisting.save_variable("deferred_key", "'deferred_value'")
        self.assertTrue(self.persisting.ready_to_save)

        # Advance reactor time past save delay (10s)
        self.harness.advance_time(10.5)

        self.assertFalse(self.persisting.ready_to_save)

        # Verify on-disk file has been updated
        reloaded = KtcPersisting(self.cfg)
        vars_sec = reloaded.content.get("Variables", {})
        self.assertEqual(vars_sec.get("deferred_key"), "deferred_value")

    def test_disconnect(self) -> None:
        """Verify timer is stopped upon disconnect."""
        self.persisting.disconnect()
        timer_handle = self.persisting.timer_save
        self.assertEqual(timer_handle.waketime, self.harness.printer.reactor.NEVER)


if __name__ == "__main__":
    unittest.main()
