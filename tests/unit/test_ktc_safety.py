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

    def test_sensor_event_delay_filters_transient_vibration(self) -> None:
        """Verify transient switch chatter/vibration within event_delay window (250ms default) does not trigger error."""
        safety: KtcSafety = self.tc.safety
        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio_deb", callback=safety._handle_sensor_change)
        safety.carriage_sensor = sensor

        # Engage tool 0 as mounted by machine with sensor triggered
        sensor.state = True
        self.tc.selected_tool = self.tool0
        self.tc.state = self.tc.StateType.ENGAGED
        self.tool0.state = self.tool0.StateType.ENGAGED
        safety.set_mounted_by_machine(True)

        # Vibration: sensor momentarily opens (0)
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)
        # Should NOT be in ERROR immediately
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)
        self.assertIsNotNone(safety._drop_timer)

        # Within 50ms (well under default 0.25s / 250ms event_delay), contact is restored (1)
        self.harness.printer.reactor.advance_time(0.05)
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 1)

        # Drop timer should be cancelled, still ENGAGED, and still machine mounted
        self.assertIsNone(safety._drop_timer)
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)
        self.assertTrue(safety._mounted_by_machine)

        # Advancing past 250ms should still not cause an error
        self.harness.printer.reactor.advance_time(0.5)
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)

    def test_sensor_event_delay_confirms_real_drop(self) -> None:
        """Verify sensor continuously open past event_delay (0.25s) confirms drop and triggers ERROR."""
        safety: KtcSafety = self.tc.safety
        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio_deb2", callback=safety._handle_sensor_change)
        safety.carriage_sensor = sensor

        # Engage tool 0
        sensor.state = True
        self.tc.selected_tool = self.tool0
        self.tc.state = self.tc.StateType.ENGAGED
        self.tool0.state = self.tool0.StateType.ENGAGED
        safety.set_mounted_by_machine(True)

        # Real tool drop: sensor opens (0)
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)
        self.assertEqual(self.tc.state, self.tc.StateType.ENGAGED)

        # Advance past 0.25s event_delay
        self.harness.printer.reactor.advance_time(0.3)

        # Toolchanger and tool should now be in ERROR state
        self.assertEqual(self.tc.state, self.tc.StateType.ERROR)
        self.assertEqual(self.tool0.state, self.tool0.StateType.ERROR)

    def test_sensor_event_delay_zero_immediate_drop(self) -> None:
        """Verify event_delay = 0 causes immediate drop detection without delay."""
        safety: KtcSafety = self.tc.safety
        cfg = self.harness.get_config_wrapper("ktc_toolchanger toolchanger")
        sensor = KtcSwitchSensor(self.harness.printer, cfg, "gpio_deb3", callback=safety._handle_sensor_change)
        safety.carriage_sensor = sensor

        # Set 0 event delay
        self.tc.event_delay = 0.0
        self.tool0.event_delay = 0.0

        sensor.state = True
        self.tc.selected_tool = self.tool0
        self.tc.state = self.tc.StateType.ENGAGED
        self.tool0.state = self.tool0.StateType.ENGAGED
        safety.set_mounted_by_machine(True)

        # Trigger open (0)
        sensor._handle_button_event(self.harness.printer.reactor.monotonic(), 0)

        # Should immediately be in ERROR
        self.assertEqual(self.tc.state, self.tc.StateType.ERROR)


if __name__ == "__main__":
    unittest.main()
