# Integration tests for nested / multi-tier toolchangers
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_toolchanger import KtcToolchanger
from klippy.extras.ktc_tool import KtcTool


class TestNestedToolchangers(KtcTestCase):
    """Test suite for hierarchical / multi-tier toolchanger topologies."""

    def test_nested_toolchanger_hierarchy(self) -> None:
        """Verify two-tier toolchanger configuration, inheritance, and selection."""
        # Config structure:
        # - Top default_toolchanger "main_tc"
        #   - Tool "tool_main" (carries secondary toolchanger)
        # - Secondary toolchanger "sub_tc" with parent_tool = "tool_main"
        #   - Child Tool "tool_sub1" (on sub_tc)
        #   - Child Tool "tool_sub2" (on sub_tc)

        raw_config = {
            "ktc": {
                "default_toolchanger": "main_tc",
                "propagate_state": "True",
            },
            "ktc_toolchanger main_tc": {
                "init_mode": "MANUAL",
                "init_order": "INDEPENDENT",
                "engage_gcode": "M117 Main Engaged",
            },
            "ktc_tool tool_main": {
                "tool_number": "10",
                "toolchanger": "main_tc",
                "force_deselect_when_parent_deselects": "True",
                "tool_select_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=SELECTED",
                "tool_deselect_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=READY",
            },
            "ktc_toolchanger sub_tc": {
                "parent_tool": "tool_main",
                "init_mode": "MANUAL",
                "init_order": "AFTER_PARENT_INITIALIZATION",
            },
            "ktc_tool tool_sub1": {
                "tool_number": "1",
                "toolchanger": "sub_tc",
                "tool_select_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=SELECTED",
                "tool_deselect_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=READY",
            },
            "ktc_tool tool_sub2": {
                "tool_number": "2",
                "toolchanger": "sub_tc",
                "tool_select_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=SELECTED",
                "tool_deselect_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=READY",
            },
        }

        self.harness.file_config.sections.update(raw_config)

        # Initialize stack
        ktc = self.harness.load_ktc_stack(num_tools=0)

        # Load main toolchanger and parent tool
        main_tc_cfg = self.harness.get_config_wrapper("ktc_toolchanger main_tc")
        main_tc = KtcToolchanger(main_tc_cfg)
        self.harness.printer.add_object("ktc_toolchanger main_tc", main_tc)

        t_main_cfg = self.harness.get_config_wrapper("ktc_tool tool_main")
        t_main = KtcTool(t_main_cfg)
        self.harness.printer.add_object("ktc_tool tool_main", t_main)

        # Load sub toolchanger
        sub_tc_cfg = self.harness.get_config_wrapper("ktc_toolchanger sub_tc")
        sub_tc = KtcToolchanger(sub_tc_cfg)
        self.harness.printer.add_object("ktc_toolchanger sub_tc", sub_tc)

        # Load sub tools
        t_sub1_cfg = self.harness.get_config_wrapper("ktc_tool tool_sub1")
        t_sub1 = KtcTool(t_sub1_cfg)
        self.harness.printer.add_object("ktc_tool tool_sub1", t_sub1)

        t_sub2_cfg = self.harness.get_config_wrapper("ktc_tool tool_sub2")
        t_sub2 = KtcTool(t_sub2_cfg)
        self.harness.printer.add_object("ktc_tool tool_sub2", t_sub2)

        self.harness.connect_and_ready()

        # Verify hierarchy
        self.assertEqual(sub_tc.parent_tool, t_main)
        self.assertEqual(t_sub1.toolchanger, sub_tc)
        self.assertEqual(t_sub2.toolchanger, sub_tc)
        self.assertEqual(t_main.toolchanger, main_tc)

        # Inherited engage gcode from main_tc
        self.assertEqual(sub_tc._engage_gcode, "M117 Main Engaged")


if __name__ == "__main__":
    unittest.main()
