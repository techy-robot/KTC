# Integration tests for toolchanger safety interlocks and failure recovery
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_safety import KtcSwitchSensor


class TestSafetyInterlocks(KtcTestCase):
    """End-to-end integration test of safety switches, fault detection, and recovery."""

    def setUp(self) -> None:
        super().setUp()
        self.ktc = self.harness.load_ktc_stack(num_tools=2, has_heaters=False)
        self.harness.connect_and_ready()
        self.tc = self.ktc.default_toolchanger
        self.tool0 = self.ktc.all_tools_by_number[0]
        self.tool1 = self.ktc.all_tools_by_number[1]

        # Reset tools to unmounted state
        self.ktc.active_tool = self.ktc.TOOL_NONE
        self.tc.selected_tool = self.ktc.TOOL_NONE

        # Configure physical carriage sensor on toolchanger
        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        self.carriage_sensor = KtcSwitchSensor(
            self.harness.printer,
            cfg,
            "gpio_carriage",
            callback=self.tc.safety._handle_sensor_change,
        )
        self.tc.safety.carriage_sensor = self.carriage_sensor

    def test_pickup_sensor_interlock(self) -> None:
        """Verify toolchange fails if sensor does not confirm tool pickup."""
        # Sensor remains un-triggered (drop or missing tool)
        self.carriage_sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)

        # Attempt to select Tool 0 -> Should abort with safety error
        with self.assertRaises(Exception) as ctx:
            self.tool0.select(final_selected=True)
        self.assertIn("Pickup verification failed", str(ctx.exception))

        # Toolchanger enters ERROR state
        self.assertEqual(self.tc.state, self.tc.StateType.ERROR)

        # Recovery via safety unlock
        self.harness.run_gcode("KTC_SAFETY_UNLOCK")
        self.assertEqual(self.tc.state, self.tc.StateType.READY)

    def test_successful_toolchange_with_sensor(self) -> None:
        """Verify normal toolchange when physical sensors properly report state transitions."""
        # 1. Start unmounted -> sensor reports 0
        self.carriage_sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)

        # Tool pickup -> switch triggers
        self.carriage_sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 1)
        self.tool0.select(final_selected=True)
        self.assertEqual(self.tc.selected_tool, self.tool0)
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)

        # Tool dropoff -> switch releases
        self.carriage_sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)
        self.tool0.deselect()
        self.assertEqual(self.tc.selected_tool, self.ktc.TOOL_NONE)
        self.assertEqual(self.tc.state, self.tc.StateType.READY)


if __name__ == "__main__":
    unittest.main()
