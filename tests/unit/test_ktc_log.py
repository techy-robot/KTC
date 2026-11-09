# Unit tests for ktc_log.py
#
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import unittest

from tests.harness import KtcTestCase
from klippy.extras.ktc_log import (
    KtcLog,
    ToolStatisticsClass,
    ChangerStatisticsClass,
)


class TestKtcLog(KtcTestCase):
    """Test suite for logging filters, levels, statistics, and reporting."""

    def setUp(self) -> None:
        super().setUp()
        self.printer = self.harness.printer
        self.harness.file_config.sections["ktc_log"] = {
            "log_level": "2",  # DEBUG level
            "logfile_level": "-1",  # No background queue thread needed for test
        }
        self.cfg = self.harness.get_config_wrapper("ktc_log")
        self.log = KtcLog(self.cfg)
        self.printer.add_object("ktc_log", self.log)

    def test_log_level_filtering(self) -> None:
        """Verify that log methods output according to log_level threshold."""
        self.printer.gcode.responses.clear()

        self.log.trace("Test Trace Message")
        self.assertFalse(any("Test Trace Message" in r for r in self.printer.gcode.responses))

        self.log.debug("Test Debug Message")
        self.assertTrue(any("Test Debug Message" in r for r in self.printer.gcode.responses))

        self.log.info("Test Info Message")
        self.assertTrue(any("Test Info Message" in r for r in self.printer.gcode.responses))

        self.log.always("Test Always Message")
        self.assertTrue(any("Test Always Message" in r for r in self.printer.gcode.responses))

    def test_cmd_set_log_level(self) -> None:
        """Verify KTC_SET_LOG_LEVEL command updates log thresholds."""
        from klippy.gcode import GCodeCommand

        # Change level to 0 (off)
        gcmd = GCodeCommand("KTC_SET_LOG_LEVEL", {"LEVEL": "0"}, self.printer.gcode)
        self.log.cmd_KTC_SET_LOG_LEVEL(gcmd)
        self.assertEqual(self.log.log_level, 0)

        self.printer.gcode.responses.clear()
        self.log.info("Hidden message")
        self.assertFalse(any("Hidden message" in r for r in self.printer.gcode.responses))

        # Change level to 3 (TRACE)
        gcmd3 = GCodeCommand("KTC_SET_LOG_LEVEL", {"LEVEL": "3"}, self.printer.gcode)
        self.log.cmd_KTC_SET_LOG_LEVEL(gcmd3)
        self.assertEqual(self.log.log_level, 3)

        self.log.trace("Visible trace")
        self.assertTrue(any("Visible trace" in r for r in self.printer.gcode.responses))

    def test_tool_and_changer_statistics(self) -> None:
        """Verify tracking of tool and changer usage counts."""
        tool_stat = ToolStatisticsClass()
        self.assertEqual(tool_stat.selects_completed, 0)
        tool_stat.selects_completed += 1
        self.assertEqual(tool_stat.selects_completed, 1)

        tc_stat = ChangerStatisticsClass()
        self.assertEqual(tc_stat.engages, 0)
        tc_stat.engages += 5
        self.assertEqual(tc_stat.engages, 5)

    def test_reset_statistics(self) -> None:
        """Verify resetting session and print statistics snapshots."""
        self.log.changer_stats["default"] = ChangerStatisticsClass()
        self.log.changer_stats["default"].engages = 10
        self.log.print_changer_stats["default"] = ChangerStatisticsClass()
        self.log.print_changer_stats["default"].engages = 0

        # Reset print stats snapshots current changer_stats
        from klippy.gcode import GCodeCommand
        gcmd = GCodeCommand("KTC_RESET_PRINT_STATS", {}, self.printer.gcode)
        self.log.cmd_KTC_RESET_PRINT_STATS(gcmd)
        self.assertEqual(self.log.print_changer_stats["default"].engages, 10)


if __name__ == "__main__":
    unittest.main()
