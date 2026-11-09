# Unit tests for ktc_toolchanger.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_toolchanger import KtcToolchanger


class TestKtcToolchanger(KtcTestCase):
    """Test suite for toolchanger initialization, engage/disengage, and tool management."""

    def setUp(self) -> None:
        super().setUp()
        self.ktc = self.harness.load_ktc_stack(num_tools=2, has_heaters=False)
        self.harness.connect_and_ready()
        self.tc: KtcToolchanger = self.ktc.default_toolchanger

    def test_toolchanger_initial_properties(self) -> None:
        """Verify toolchanger name, init modes, and tools registration."""
        self.assertEqual(self.tc.name, "toolchanger")
        self.assertEqual(self.tc.init_mode, KtcToolchanger.InitModeType.MANUAL)
        self.assertEqual(self.tc.init_order, KtcToolchanger.InitOrderType.INDEPENDENT)
        self.assertIn("0", self.tc.tools)
        self.assertIn("1", self.tc.tools)

    def test_engage_and_disengage(self) -> None:
        """Verify engage and disengage state transitions."""
        # Ready -> Engage -> Engaged
        self.tc.state = self.tc.StateType.READY
        self.tc.engage()
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)

        # Engaged -> Disengage -> Ready
        self.tc.disengage()
        self.assertEqual(self.tc.state, self.tc.StateType.READY)

    def test_initialize_from_configured(self) -> None:
        """Verify toolchanger initialization moves from CONFIGURED to READY."""
        self.tc.state = self.tc.StateType.CONFIGURED
        self.tc.initialize()
        self.assertEqual(self.tc.state, self.tc.StateType.READY)

    def test_invalid_parent_tool_check(self) -> None:
        """Verify non-existent parent_tool raises config error."""
        self.harness.file_config.sections["ktc_toolchanger bad_tc"] = {
            "parent_tool": "non_existent_tool",
        }
        cfg = self.harness.get_config_wrapper("ktc_toolchanger bad_tc")
        with self.assertRaises(Exception):
            KtcToolchanger(cfg)


if __name__ == "__main__":
    unittest.main()
