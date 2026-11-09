# Unit tests for ktc_safety.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_safety import (
    KtcSwitchSensor,
    KtcSafety,
)


class TestKtcSafety(KtcTestCase):
    """Test suite for safety sensor monitoring, pickup/dropoff verification, and unlock."""

    def setUp(self) -> None:
        super().setUp()
        self.ktc = self.harness.load_ktc_stack(num_tools=2, has_heaters=False)
        self.harness.connect_and_ready()
        self.tc = self.ktc.default_toolchanger
        self.tool0 = self.ktc.all_tools_by_number[0]
        self.tool1 = self.ktc.all_tools_by_number[1]

    def test_switch_sensor_state_change(self) -> None:
        """Verify KtcSwitchSensor debouncing and callback invocation."""
        events = []
        def on_change(eventtime: float, state: bool) -> None:
            events.append((eventtime, state))

        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio1", callback=on_change)

        # Trigger event
        sensor._handle_button_event(100.0, 1)
        self.assertTrue(sensor.state)
        self.assertTrue(sensor.is_triggered())
        self.assertEqual(len(events), 1)

        # Release event
        sensor._handle_button_event(101.0, 0)
        self.assertFalse(sensor.state)
        self.assertFalse(sensor.is_triggered())
        self.assertEqual(len(events), 2)

    def test_verify_pickup_success_and_failure(self) -> None:
        """Verify tool pickup verification passes when sensor triggers, fails otherwise."""
        safety: KtcSafety = self.tc.safety

        # Attach carriage sensor to toolchanger
        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio2", callback=safety._handle_sensor_change)
        safety.carriage_sensor = sensor

        # 1. Pickup verification succeeds when sensor is triggered
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 1)
        self.assertTrue(sensor.is_triggered())
        safety.verify_tool_pickup(self.tool0)

        # 2. Pickup verification fails when sensor is NOT triggered
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)
        self.assertFalse(sensor.is_triggered())

        with self.assertRaises(Exception) as ctx:
            safety.verify_tool_pickup(self.tool0)
        self.assertIn("Pickup verification failed", str(ctx.exception))

    def test_verify_dropoff_success_and_failure(self) -> None:
        """Verify tool dropoff verification passes when tool is released, fails if attached."""
        safety: KtcSafety = self.tc.safety

        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio3", callback=safety._handle_sensor_change)
        safety.carriage_sensor = sensor

        # 1. Dropoff succeeds when sensor is released (tool not on carriage)
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)
        safety.verify_tool_dropoff(self.tool0)

        # 2. Dropoff fails when sensor indicates tool is still attached
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 1)
        with self.assertRaises(Exception) as ctx:
            safety.verify_tool_dropoff(self.tool0)
        self.assertIn("Dropoff verification failed", str(ctx.exception))

    def test_safety_commands_and_unlock(self) -> None:
        """Verify KTC_SAFETY_ENABLE, KTC_SAFETY_DISABLE, and KTC_SAFETY_UNLOCK."""
        safety: KtcSafety = self.tc.safety

        # Disable safety
        self.harness.run_gcode("KTC_SAFETY_DISABLE")
        self.assertFalse(safety.enabled)

        # Enable safety
        self.harness.run_gcode("KTC_SAFETY_ENABLE")
        self.assertTrue(safety.enabled)

        # Put toolchanger in ERROR state
        self.tc.state = self.tc.StateType.ERROR
        self.assertEqual(self.tc.state, self.tc.StateType.ERROR)

        # Run unlock
        self.harness.run_gcode("KTC_SAFETY_UNLOCK")
        # Toolchanger should recover to READY state
        self.assertEqual(self.tc.state, self.tc.StateType.READY)


if __name__ == "__main__":
    unittest.main()
