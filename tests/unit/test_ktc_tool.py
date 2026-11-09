# Unit tests for ktc_tool.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_tool import KtcTool
from klippy.extras.ktc_heater import HeaterStateType


class TestKtcTool(KtcTestCase):
    """Test suite for tool initialization, selection, deselection, and offset management."""

    def setUp(self) -> None:
        super().setUp()
        self.ktc = self.harness.load_ktc_stack(num_tools=2, has_heaters=True, has_fans=True)
        self.harness.connect_and_ready()
        self.tool0: KtcTool = self.ktc.all_tools_by_number[0]
        self.tool1: KtcTool = self.ktc.all_tools_by_number[1]
        self.ktc.active_tool = self.ktc.TOOL_NONE
        self.ktc.default_toolchanger.selected_tool = self.ktc.TOOL_NONE

    def test_tool_properties(self) -> None:
        """Verify tool naming, number, and toolchanger binding."""
        self.assertEqual(self.tool0.name, "0")
        self.assertEqual(self.tool0.number, 0)
        self.assertEqual(self.tool0.toolchanger, self.ktc.default_toolchanger)
        self.assertEqual(self.tool1.name, "1")
        self.assertEqual(self.tool1.number, 1)

    def test_reserved_tool_name_rejected(self) -> None:
        """Verify that creating a tool with a reserved name raises error."""
        self.harness.file_config.sections["ktc_tool tool_none"] = {
            "tool_number": "99",
        }
        cfg = self.harness.get_config_wrapper("ktc_tool tool_none")
        with self.assertRaises(Exception) as ctx:
            KtcTool(cfg)
        self.assertIn("reserved for internal use", str(ctx.exception))

    def test_tool_selection_and_deselection(self) -> None:
        """Verify tool selection/deselection state transitions and heater states."""
        # 1. Select Tool 0
        self.tool0.select()
        self.assertEqual(self.tool0.state, self.tool0.StateType.SELECTED)
        self.assertEqual(self.ktc.default_toolchanger.selected_tool, self.tool0)

        # 2. Deselect Tool 0
        self.tool0.deselect()
        self.assertEqual(self.tool0.state, self.tool0.StateType.READY)
        self.assertEqual(self.ktc.default_toolchanger.selected_tool, self.tool0.TOOL_NONE)

    def test_fan_speed_save_and_restore(self) -> None:
        """Verify that fan speed is saved via KTC_SET_AND_SAVE_PARTFAN_SPEED and restored on select."""
        self.tool0.select(final_selected=True)

        # Set fan speed via KTC command (uses S parameter)
        self.harness.run_gcode("KTC_SET_AND_SAVE_PARTFAN_SPEED S=0.75 TOOL=0")
        self.assertEqual(self.ktc.saved_fan_speed, 0.75)

        fan = self.harness.printer.lookup_object("fan_generic fan0")
        self.assertEqual(fan.speed, 0.75)

        # Deselect tool -> fan set to 0, saved speed retained
        self.tool0.deselect()
        self.assertEqual(fan.speed, 0.0)
        self.assertEqual(self.ktc.saved_fan_speed, 0.75)


if __name__ == "__main__":
    unittest.main()
