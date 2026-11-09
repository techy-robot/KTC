# Unit tests for ktc.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc import Ktc
from klippy.extras.ktc_heater import HeaterStateType


class TestKtc(KtcTestCase):
    """Test suite for main KTC orchestrator, G-code commands, and offsets."""

    def setUp(self) -> None:
        super().setUp()
        self.ktc: Ktc = self.harness.load_ktc_stack(num_tools=3, has_heaters=True, has_fans=False)
        self.harness.connect_and_ready()
        self.tool0 = self.ktc.all_tools_by_number[0]
        self.tool1 = self.ktc.all_tools_by_number[1]
        self.tool2 = self.ktc.all_tools_by_number[2]

        # Reset tools to unmounted state
        self.ktc.active_tool = self.ktc.TOOL_NONE
        self.ktc.default_toolchanger.selected_tool = self.ktc.TOOL_NONE

    def test_initial_state_and_tool_registry(self) -> None:
        """Verify all tools, toolchangers, and heaters are registered properly."""
        self.assertEqual(len(self.ktc.all_tools_by_number), 3)
        self.assertIn("0", self.ktc.all_tools)
        self.assertIn("1", self.ktc.all_tools)
        self.assertIn("2", self.ktc.all_tools)
        self.assertEqual(self.ktc.state, self.ktc.StateType.CONFIGURED)

    def test_global_offset_save(self) -> None:
        """Verify setting and adjusting global offsets via KTC_GLOBAL_OFFSET_SAVE."""
        # Absolute set
        self.harness.run_gcode("KTC_GLOBAL_OFFSET_SAVE X=1.5 Y=-2.0 Z=0.25")
        self.assertEqual(self.ktc.global_offset, [1.5, -2.0, 0.25])

        # Relative adjust
        self.harness.run_gcode("KTC_GLOBAL_OFFSET_SAVE X_ADJUST=0.5 Z_ADJUST=-0.1")
        self.assertEqual(self.ktc.global_offset, [2.0, -2.0, 0.15])

    def test_tool_offset_save(self) -> None:
        """Verify setting and adjusting tool specific offsets via KTC_TOOL_OFFSET_SAVE."""
        self.harness.run_gcode("KTC_TOOL_OFFSET_SAVE TOOL=0 X=10.0 Y=20.0 Z=0.5")
        self.assertEqual(self.tool0.offset, [10.0, 20.0, 0.5])

        self.harness.run_gcode("KTC_TOOL_OFFSET_SAVE TOOL=0 X_ADJUST=-2.0")
        self.assertEqual(self.tool0.offset, [8.0, 20.0, 0.5])

    def test_tool_set_temperature_command(self) -> None:
        """Verify setting active and standby temperatures via KTC_TOOL_SET_TEMPERATURE."""
        self.harness.run_gcode("KTC_TOOL_SET_TEMPERATURE TOOL=0 STDB_TMP=150 ACTV_TMP=215")
        self.assertEqual(self.tool0.extruder.active_temp, 215.0)
        self.assertEqual(self.tool0.extruder.standby_temp, 150.0)

    def test_heaters_pause_and_resume(self) -> None:
        """Verify pausing and resuming heaters via KTC_HEATERS_PAUSE and KTC_HEATERS_RESUME."""
        heater_obj = self.ktc.all_heaters["extruder"]
        heater_obj.heater_active_temp = 200.0
        heater_obj.state = HeaterStateType.ACTIVE
        self.assertEqual(heater_obj.state, HeaterStateType.ACTIVE)

        # Pause heaters
        self.harness.run_gcode("KTC_HEATERS_PAUSE")
        self.assertEqual(heater_obj.state, HeaterStateType.OFF)
        self.harness.advance_time(0.2)
        heater = self.harness.printer.heaters.lookup_heater("extruder")
        self.assertEqual(heater.target_temp, 0.0)

        # Resume heaters
        self.harness.run_gcode("KTC_HEATERS_RESUME")
        self.assertEqual(heater_obj.state, HeaterStateType.ACTIVE)
        self.assertEqual(heater.target_temp, 200.0)

    def test_tool_map_number_command(self) -> None:
        """Verify remapping tool numbers via KTC_TOOL_MAP_NR."""
        # Remap T99 to tool 0
        self.harness.run_gcode("KTC_TOOL_MAP_NR TOOL=0 SET=99")
        self.assertEqual(self.ktc.all_tools_by_number[99], self.tool0)

    def test_deselect_all_command(self) -> None:
        """Verify deselecting all mounted tools via KTC_DESELECT_ALL."""
        self.tool0.select(final_selected=True)
        self.assertEqual(self.ktc.default_toolchanger.selected_tool, self.tool0)

        self.harness.run_gcode("KTC_DESELECT_ALL")
        self.assertEqual(self.ktc.default_toolchanger.selected_tool, self.ktc.TOOL_NONE)
        self.assertEqual(self.ktc.active_tool, self.ktc.TOOL_NONE)


if __name__ == "__main__":
    unittest.main()
