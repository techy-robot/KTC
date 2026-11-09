# Unit tests for ktc_heater.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_heater import (
    HeaterStateType,
    KtcHeater,
    KtcHeaterTimer,
    HeaterTimerType,
)


class TestKtcHeater(KtcTestCase):
    """Test suite for heater states, temperature management, and timers."""

    def setUp(self) -> None:
        super().setUp()
        self.printer = self.harness.printer
        self.heater = self.printer.heaters.add_heater("extruder")
        self.harness.file_config.sections["ktc_heater extruder"] = {
            "temperature_offset": "0.0",
        }
        self.cfg = self.harness.get_config_wrapper("ktc_heater extruder")
        self.ktc_heater = KtcHeater(self.cfg)
        # Register klippy:ready event for timer initialization
        self.printer.send_event("klippy:ready")

    def test_heater_state_type_parsing(self) -> None:
        """Verify HeaterStateType string and numeric parsing."""
        self.assertEqual(HeaterStateType.parse_heater_state("off"), HeaterStateType.OFF)
        self.assertEqual(HeaterStateType.parse_heater_state("0"), HeaterStateType.OFF)
        self.assertEqual(HeaterStateType.parse_heater_state("STANDBY"), HeaterStateType.STANDBY)
        self.assertEqual(HeaterStateType.parse_heater_state("1"), HeaterStateType.STANDBY)
        self.assertEqual(HeaterStateType.parse_heater_state("Active"), HeaterStateType.ACTIVE)
        self.assertEqual(HeaterStateType.parse_heater_state("2"), HeaterStateType.ACTIVE)

        with self.assertRaises(ValueError):
            HeaterStateType.parse_heater_state("invalid_state")

    def test_heater_temperature_settings(self) -> None:
        """Verify temperature settings on ACTIVE and OFF states."""
        self.ktc_heater.heater_active_temp = 210.0
        self.ktc_heater.standby_temp = 150.0

        # Set to ACTIVE
        self.ktc_heater.state = HeaterStateType.ACTIVE
        self.assertEqual(self.heater.target_temp, 210.0)

        # Set to OFF
        self.ktc_heater.state = HeaterStateType.OFF
        # After powerdown timer fires at NOW
        self.harness.advance_time(0.2)
        self.assertEqual(self.heater.target_temp, 0.0)

    def test_heater_off_state(self) -> None:
        """Verify setting state to OFF sets target temp to 0."""
        self.ktc_heater.heater_active_temp = 200.0
        self.ktc_heater.state = HeaterStateType.ACTIVE
        self.assertEqual(self.heater.target_temp, 200.0)

        # Set to OFF
        self.ktc_heater.state = HeaterStateType.OFF
        self.assertEqual(self.ktc_heater.state, HeaterStateType.OFF)
        self.harness.advance_time(0.2)
        self.assertEqual(self.heater.target_temp, 0.0)

    def test_heater_timer_transitions(self) -> None:
        """Verify standby and shutdown timer transitions."""
        self.ktc_heater.heater_active_temp = 220.0
        self.ktc_heater.standby_temp = 160.0
        self.ktc_heater.active_to_standby_delay = 5.0
        self.ktc_heater.standby_to_powerdown_delay = 10.0

        # Start ACTIVE
        self.ktc_heater.state = HeaterStateType.ACTIVE
        self.assertEqual(self.heater.target_temp, 220.0)

        # Set STANDBY (starts 5s timer)
        self.ktc_heater.state = HeaterStateType.STANDBY

        # Advance time by 5.2s -> standby timer triggers -> sets 160C and starts 10s powerdown timer
        self.harness.advance_time(5.2)
        self.assertEqual(self.heater.target_temp, 160.0)

        # Advance time by another 10.2s -> powerdown timer triggers -> turns heater off (0C)
        self.harness.advance_time(10.2)
        self.assertEqual(self.heater.target_temp, 0.0)


if __name__ == "__main__":
    unittest.main()
