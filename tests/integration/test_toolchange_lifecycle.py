# Integration tests for complete toolchange lifecycle and temperature sequencing
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_heater import HeaterStateType


class TestToolchangeLifecycle(KtcTestCase):
    """End-to-end integration test of tool selection, switching, temperature delays, and stats."""

    def test_complete_toolchange_workflow(self) -> None:
        """Simulate a complete print job sequence with two active tools."""
        # 1. Setup multi-tool stack with heaters and fans
        ktc = self.harness.load_ktc_stack(num_tools=2, has_heaters=True, has_fans=True)
        self.harness.connect_and_ready()

        t0 = ktc.all_tools_by_number[0]
        t1 = ktc.all_tools_by_number[1]
        tc = ktc.default_toolchanger

        # Set fast delays for test predictability
        t0.extruder.active_to_standby_delay = 2.0
        t0.extruder.standby_to_powerdown_delay = 5.0
        t1.extruder.active_to_standby_delay = 2.0
        t1.extruder.standby_to_powerdown_delay = 5.0

        # Initial machine state: no tool mounted
        ktc.active_tool = ktc.TOOL_NONE
        tc.selected_tool = ktc.TOOL_NONE

        # 2. Configure printing temperatures for both tools
        self.harness.run_gcode("KTC_TOOL_SET_TEMPERATURE TOOL=0 ACTV_TMP=210 STDB_TMP=160")
        self.harness.run_gcode("KTC_TOOL_SET_TEMPERATURE TOOL=1 ACTV_TMP=240 STDB_TMP=170")

        h0 = self.harness.printer.heaters.lookup_heater("extruder")
        h1 = self.harness.printer.heaters.lookup_heater("extruder1")

        # 3. Select Tool 0
        t0.select(final_selected=True)
        self.assertEqual(tc.selected_tool, t0)
        self.assertEqual(ktc.active_tool, t0)
        self.assertEqual(t0.state, t0.StateType.ACTIVE)
        self.assertEqual(tc.state, tc.StateType.ENGAGED)
        self.assertEqual(h0.target_temp, 210.0)

        # Set fan speed for Tool 0
        self.harness.run_gcode("KTC_SET_AND_SAVE_PARTFAN_SPEED S=0.6 TOOL=0")
        fan0 = self.harness.printer.lookup_object("fan_generic fan0")
        self.assertEqual(fan0.speed, 0.6)

        # 4. Switch from Tool 0 to Tool 1
        t1.select(final_selected=True)
        self.assertEqual(tc.selected_tool, t1)
        self.assertEqual(ktc.active_tool, t1)
        self.assertEqual(t1.state, t1.StateType.ACTIVE)
        self.assertEqual(h1.target_temp, 240.0)

        # Tool 0 was deselected -> fan0 turned off
        self.assertEqual(fan0.speed, 0.0)

        # Tool 0 heater standby timer is counting down (2s delay)
        # Target is still 210 during delay
        self.assertEqual(h0.target_temp, 210.0)

        # Advance 2.1 seconds -> Tool 0 drops to standby temp (160C)
        self.harness.advance_time(2.1)
        self.assertEqual(h0.target_temp, 160.0)

        # Advance another 5.1 seconds -> Tool 0 heater shuts down (0C)
        self.harness.advance_time(5.1)
        self.assertEqual(h0.target_temp, 0.0)

        # Tool 1 heater is still active
        self.assertEqual(h1.target_temp, 240.0)

        # 5. Deselect all tools at end of print
        self.harness.run_gcode("KTC_DESELECT_ALL")
        self.assertEqual(tc.selected_tool, ktc.TOOL_NONE)
        self.assertEqual(ktc.active_tool, ktc.TOOL_NONE)

        # Advance time to allow Tool 1 heater to power down
        self.harness.advance_time(7.5)
        self.assertEqual(h1.target_temp, 0.0)

        # 6. Verify statistics recorded both tool selections
        log = self.harness.printer.lookup_object("ktc_log")
        self.assertGreaterEqual(log.tool_stats["0"].selects_completed, 1)
        self.assertGreaterEqual(log.tool_stats["1"].selects_completed, 1)

        # Ensure statistics reports generate without exceptions
        self.harness.run_gcode("KTC_STATS_REPORT")
        self.harness.run_gcode("KTC_PRINT_STATS_REPORT")


if __name__ == "__main__":
    unittest.main()
