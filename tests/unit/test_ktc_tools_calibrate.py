# Unit tests for ktc_tools_calibrate.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_tools_calibrate import (
    Axis,
    Directions,
    Position,
    KtcToolsCalibrate,
    PrinterProbeMultiAxis,
)
from klippy.pins import error as PinError


class TestKtcToolsCalibrate(KtcTestCase):
    """Test suite for nozzle alignment probe geometry, virtual endstops, and math."""

    def test_geometry_and_directions(self) -> None:
        """Verify Axis enums, directions, and Position vector arithmetic."""
        self.assertEqual(Axis.X, 0)
        self.assertEqual(Axis.Y, 1)
        self.assertEqual(Axis.Z, 2)

        self.assertEqual(Directions["x+"], [Axis.X, 1])
        self.assertEqual(Directions["x-"], [Axis.X, -1])
        self.assertEqual(Directions["y+"], [Axis.Y, 1])
        self.assertEqual(Directions["y-"], [Axis.Y, -1])
        self.assertEqual(Directions["z+"], [Axis.Z, 1])
        self.assertEqual(Directions["z-"], [Axis.Z, -1])

        pos = Position(10.0, 20.0, 5.0)
        self.assertEqual(pos.x, 10.0)
        self.assertEqual(pos.y, 20.0)
        self.assertEqual(pos.z, 5.0)

    def test_virtual_endstop_pin_validation(self) -> None:
        """Verify that probe virtual endstop rejects invalid pullups, inverts, and non-endstop types."""
        self.harness.file_config.sections["tools_calibrate"] = {
            "pin": "probe_pin",
            "travel_speed": "25.0",
            "spread": "4.0",
        }
        cfg = self.harness.get_config_wrapper("tools_calibrate")

        # Mock probe multi axis
        from unittest.mock import MagicMock
        probe_axis = PrinterProbeMultiAxis(MagicMock(), cfg, MagicMock(), MagicMock(), MagicMock())

        # Valid pin setup
        valid_params = {"pin": "xy_virtual_endstop", "invert": False, "pullup": False}
        res = probe_axis.setup_pin("endstop", valid_params)
        self.assertIsNotNone(res)

        # Invalid pin type
        with self.assertRaises(PinError) as ctx:
            probe_axis.setup_pin("pwm", valid_params)
        self.assertIn("Probe virtual endstop only useful as endstop pin", str(ctx.exception))

        # Invalid pin name
        bad_name_params = {"pin": "not_xy_virtual_endstop", "invert": False, "pullup": False}
        with self.assertRaises(PinError):
            probe_axis.setup_pin("endstop", bad_name_params)

        # Invalid invert
        invert_params = {"pin": "xy_virtual_endstop", "invert": True, "pullup": False}
        with self.assertRaises(PinError) as ctx:
            probe_axis.setup_pin("endstop", invert_params)
        self.assertIn("Can not pullup/invert probe virtual endstop", str(ctx.exception))

        # Invalid pullup
        pullup_params = {"pin": "xy_virtual_endstop", "invert": False, "pullup": True}
        with self.assertRaises(PinError) as ctx:
            probe_axis.setup_pin("endstop", pullup_params)
        self.assertIn("Can not pullup/invert probe virtual endstop", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

