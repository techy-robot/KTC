# Unit tests for ktc_base.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase, TestConfigWrapper
from klippy.extras.ktc_base import (
    KtcBaseClass,
    KtcBaseChangerClass,
    KtcBaseToolClass,
    KtcConstantsClass,
    KtcConfigurableEnum,
    PARAMS_TO_INHERIT,
    TOOL_NONE_N,
    TOOL_UNKNOWN_N,
    TOOL_NUMBERLESS_N,
)
from klippy.extras.ktc_toolchanger import KtcToolchanger


class TestKtcBase(KtcTestCase):
    """Test suite for base classes, inheritance, enums and helpers."""

    def test_constants(self) -> None:
        """Verify internal sentinel constants and invalid tools."""
        c = KtcConstantsClass()
        self.assertEqual(c.TOOL_NONE.number, TOOL_NONE_N)
        self.assertEqual(c.TOOL_UNKNOWN.number, TOOL_UNKNOWN_N)
        self.assertIn(c.TOOL_NONE, c.INVALID_TOOLS)
        self.assertIn(c.TOOL_UNKNOWN, c.INVALID_TOOLS)

    def test_configurable_enum(self) -> None:
        """Verify enum parsing from config values."""
        self.harness.file_config.sections["test_sec"] = {
            "mode_valid": "ON_START",
            "mode_case_insensitive": "manual",
            "mode_first": "on_first_use",
        }
        cfg = self.harness.get_config_wrapper("test_sec")

        val1 = KtcToolchanger.InitModeType.get_value_from_configuration(
            cfg, "mode_valid", KtcToolchanger.InitModeType.MANUAL
        )
        self.assertEqual(val1, KtcToolchanger.InitModeType.ON_START)

        val2 = KtcToolchanger.InitModeType.get_value_from_configuration(
            cfg, "mode_case_insensitive", KtcToolchanger.InitModeType.ON_START
        )
        self.assertEqual(val2, KtcToolchanger.InitModeType.MANUAL)

        val3 = KtcToolchanger.InitModeType.get_value_from_configuration(
            cfg, "mode_first", KtcToolchanger.InitModeType.MANUAL
        )
        self.assertEqual(val3, KtcToolchanger.InitModeType.ON_FIRST_USE)

    def test_base_class_init(self) -> None:
        """Verify base class property loading and initial states."""
        self.harness.file_config.sections["ktc_base_test"] = {
            "requires_axis_homed": "xyz",
            "engage_gcode": "M117 Engage",
            "params_speed": "150",
            "params_temp": "210.5",
        }
        cfg = self.harness.get_config_wrapper("ktc_base_test")
        base = KtcBaseClass(cfg)

        self.assertEqual(base.requires_axis_homed, "XYZ")
        self.assertEqual(base._engage_gcode, "M117 Engage")
        self.assertIn("params_speed", base.params)
        self.assertEqual(base.params["params_speed"], 150)
        self.assertEqual(base.params["params_temp"], 210.5)

    def test_fan_parsing(self) -> None:
        """Verify fan configuration string parsing and error conditions."""
        self.harness.file_config.sections["fans_valid"] = {
            "fans": "fan0, fan1:0.8"
        }
        cfg = self.harness.get_config_wrapper("fans_valid")
        obj = KtcBaseClass(cfg)

        self.assertEqual(len(obj.fans), 2)
        self.assertEqual(obj.fans[0], ["fan0", 1.0])
        self.assertEqual(obj.fans[1], ["fan1", 0.8])

        # Invalid multiplier
        self.harness.file_config.sections["fans_bad_mult"] = {
            "fans": "fan0:bad_mult"
        }
        cfg_bad = self.harness.get_config_wrapper("fans_bad_mult")
        with self.assertRaises(Exception):
            KtcBaseClass(cfg_bad)

        # Out of range multiplier
        self.harness.file_config.sections["fans_out_of_range"] = {
            "fans": "fan0:1.5"
        }
        cfg_oor = self.harness.get_config_wrapper("fans_out_of_range")
        with self.assertRaises(Exception):
            KtcBaseClass(cfg_oor)

    def test_init_offset_prompts_removal(self) -> None:
        """Verify that specifying init_offset stores to persistence and prompts config removal."""
        self.harness.load_ktc_stack(num_tools=0)
        self.harness.file_config.sections["ktc_tool 0"] = {
            "tool_number": "0",
            "toolchanger": "toolchanger",
            "init_offset": "10.0, 20.0, 30.0",
        }
        cfg = self.harness.get_config_wrapper("ktc_tool 0")
        from klippy.extras.ktc_tool import KtcTool
        tool = KtcTool(cfg)

        with self.assertRaises(Exception) as ctx:
            tool.configure_inherited_params()
        self.assertIn("successfully saved", str(ctx.exception))
        self.assertIn("Remove the setting from config", str(ctx.exception))

    def test_offset_coordinates(self) -> None:
        """Verify coordinate offset list assignment."""
        obj = KtcBaseClass(None)
        obj.offset = [10.5, -20.25, 5.0]
        self.assertEqual(obj.offset, [10.5, -20.25, 5.0])


if __name__ == "__main__":
    unittest.main()
