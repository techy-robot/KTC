# Nozzle alignment module for 3d kinematic probes.
#
# Convoluted Code History:
# - Added to KTC V2 by Asher Edwards <asher@fiatnovum.com>
# - Further adapted in https://github.com/viesturz/klipper-toolchanger/blob/main/klipper/extras/tools_calibrate.py
# - Originally sourced from https://github.com/ben5459/Klipper_ToolChanger/blob/master/probe_multi_axis.py, includes code by Kevin O'Connor <kevin@koconnor.net> and Martin Hierholzer <martin@hierholzer.info>
# - Ben5459 forked https://github.com/TypQxQ/Klipper_ToolChanger (KTCC V1)

from __future__ import annotations
import collections
import enum
import logging
import typing

from klippy import pins

from .ktc_base import (
    KtcBaseClass,
    KtcConstantsClass,
)

if typing.TYPE_CHECKING:
    from ...klipper.klippy import configfile, gcode
    from . import ktc, ktc_log, ktc_tool, ktc_persisting


class Axis(enum.IntEnum):
    X = 0
    Y = 1
    Z = 2


Position = collections.namedtuple("Position", ["x", "y", "z"])

Directions = {
    "x+": [Axis.X, +1],
    "x-": [Axis.X, -1],
    "y+": [Axis.Y, +1],
    "y-": [Axis.Y, -1],
    "z+": [Axis.Z, +1],
    "z-": [Axis.Z, -1],
}

HINT_TIMEOUT = """
If the probe did not move far enough to trigger, then
consider reducing/increasing the axis minimum/maximum
position so the probe can travel further (the minimum
position can be negative).
"""


class KtcToolsCalibrate(KtcBaseClass, KtcConstantsClass):
    def __init__(self, config: "configfile.ConfigWrapper"):
        super().__init__(config)
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.ktc: typing.Optional["ktc.Ktc"] = None
        self.log: typing.Optional["ktc_log.KtcLog"] = None

        self.gcode_move = self.printer.load_object(config, "gcode_move")
        self.probe_multi_axis = PrinterProbeMultiAxis(
            self,
            config,
            ProbeEndstopWrapper(config, "x"),
            ProbeEndstopWrapper(config, "y"),
            ProbeEndstopWrapper(config, "z"),
        )
        self.travel_speed = config.getfloat("travel_speed", 10.0, above=0.0)

        spread = config.getfloat("spread", 5.0)
        self.spread = [
            config.getfloat("spread_x", spread),
            config.getfloat("spread_y", spread),
        ]
        self.initial_spread = [
            config.getfloat("initial_spread_x", self.spread[Axis.X]),
            config.getfloat("initial_spread_y", self.spread[Axis.Y]),
        ]

        self.lower_z = config.getfloat("lower_z", 0.5)
        self.lift_z = config.getfloat("lift_z", 1.0)
        self.trigger_to_bottom_z = config.getfloat(
            "trigger_to_bottom_z", default=0.0
        )
        self.lift_speed = config.getfloat(
            "lift_speed", self.probe_multi_axis.lift_speed
        )
        self.config_sensor_x = config.getfloat("sensor_x", default=None)
        self.config_sensor_y = config.getfloat("sensor_y", default=None)
        self.config_sensor_z = config.getfloat("sensor_z", default=None)

        self._reset_last_results(None)

        # Register events
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "stepper_enable:motor_off", self._reset_last_results
        )

        # Register commands
        self.gcode = self.printer.lookup_object("gcode")

        # Standard KTC commands
        self.gcode.register_command(
            "KTC_TOOL_LOCATE_SENSOR",
            self.cmd_KTC_TOOL_LOCATE_SENSOR,
            desc=self.cmd_KTC_TOOL_LOCATE_SENSOR_help,
        )
        self.gcode.register_command(
            "KTC_TOOL_CALIBRATE_OFFSET",
            self.cmd_KTC_TOOL_CALIBRATE_OFFSET,
            desc=self.cmd_KTC_TOOL_CALIBRATE_OFFSET_help,
        )
        self.gcode.register_command(
            "KTC_TOOL_CALIBRATE_SAVE",
            self.cmd_KTC_TOOL_CALIBRATE_SAVE,
            desc=self.cmd_KTC_TOOL_CALIBRATE_SAVE_help,
        )
        self.gcode.register_command(
            "KTC_TOOL_CALIBRATE_QUERY",
            self.cmd_KTC_TOOL_CALIBRATE_QUERY,
            desc=self.cmd_KTC_TOOL_CALIBRATE_QUERY_help,
        )


    def _handle_connect(self):
        """Bind KTC core and KtcLog once all printer objects are initialized."""
        try:
            self.log = typing.cast(
                "ktc_log.KtcLog", self.printer.lookup_object("ktc_log", None)
            )
        except Exception:
            self.log = None

        try:
            self.ktc = typing.cast(
                "ktc.Ktc", self.printer.lookup_object("ktc", None)
            )
        except Exception:
            self.ktc = None

    def log_debug(self, msg: str):
        if self.log is not None:
            self.log.debug(msg)
        else:
            logging.debug(msg)

    def log_trace(self, msg: str):
        if self.log is not None:
            self.log.trace(msg)
        else:
            logging.debug(msg)

    def log_always(self, msg: str):
        if self.log is not None:
            self.log.always(msg)
        else:
            logging.info(msg)

    def _reset_last_results(self, eventtime=None):
        if (
            self.config_sensor_x is not None
            or self.config_sensor_y is not None
            or self.config_sensor_z is not None
        ):
            self.sensor_location = Position(
                self.config_sensor_x if self.config_sensor_x is not None else 0.0,
                self.config_sensor_y if self.config_sensor_y is not None else 0.0,
                self.config_sensor_z if self.config_sensor_z is not None else 0.0,
            )
        else:
            self.sensor_location = None
        self.last_result: typing.Optional[Position] = None
        self.last_calibrated_tool: typing.Optional[str] = None
        self.last_probe_offset = 0.0
        self.calibration_probe_inactive = True

    def get_status(self, eventtime=None):
        return {
            "sensor_location": (
                [self.sensor_location.x, self.sensor_location.y, self.sensor_location.z]
                if self.sensor_location
                else None
            ),
            "last_result": (
                [self.last_result.x, self.last_result.y, self.last_result.z]
                if self.last_result
                else None
            ),
            "last_calibrated_tool": self.last_calibrated_tool,
            "calibration_probe_inactive": self.calibration_probe_inactive,
        }

    def _parse_axes(self, gcmd: "gcode.GCodeCommand") -> tuple[bool, bool, bool]:
        probe_x = gcmd.get("X", None) is not None
        probe_y = gcmd.get("Y", None) is not None
        probe_z = gcmd.get("Z", None) is not None
        axis_param = gcmd.get("AXIS", None)
        if axis_param is not None:
            axis_param = axis_param.upper()
            if "ALL" in axis_param:
                probe_x = probe_y = probe_z = True
            else:
                if "X" in axis_param:
                    probe_x = True
                if "Y" in axis_param:
                    probe_y = True
                if "Z" in axis_param:
                    probe_z = True
        if not (probe_x or probe_y or probe_z):
            probe_x = probe_y = probe_z = True
        return probe_x, probe_y, probe_z

    def probe_xy(
        self, toolhead, top_pos, direction, gcmd, spread, samples=None
    ):
        [axis, offset] = Directions[direction]
        start_pos = list(top_pos)
        start_pos[axis] -= offset * spread[axis]
        self.log_trace(
            f"ktc_tools_calibrate: probe_xy({top_pos=}, {start_pos=}, {direction=})"
        )
        toolhead.manual_move(
            [None, None, top_pos[2] + self.lift_z], self.lift_speed
        )
        toolhead.manual_move(
            [start_pos[0], start_pos[1], None], self.travel_speed
        )
        toolhead.manual_move(
            [None, None, top_pos[2] - self.lower_z], self.lift_speed
        )
        return self.probe_multi_axis.run_probe(
            direction,
            gcmd,
            samples=samples,
            max_distance=spread[axis] * 1.8,
        )[axis]

    def calibrate_xy(
        self,
        toolhead,
        top_pos,
        gcmd,
        spread,
        samples=None,
        probe_x=True,
        probe_y=True,
    ):
        center_x = top_pos[0]
        center_y = top_pos[1]
        if probe_x:
            left_x = self.probe_xy(toolhead, top_pos, "x+", gcmd, spread, samples)
            right_x = self.probe_xy(toolhead, top_pos, "x-", gcmd, spread, samples)
            center_x = (left_x + right_x) / 2.0
            top_pos = [center_x, top_pos[1], top_pos[2]]
        if probe_y:
            near_y = self.probe_xy(toolhead, top_pos, "y+", gcmd, spread, samples)
            far_y = self.probe_xy(toolhead, top_pos, "y-", gcmd, spread, samples)
            center_y = (near_y + far_y) / 2.0
        return [center_x, center_y]

    def locate_sensor(
        self, gcmd, probe_x=True, probe_y=True, probe_z=True
    ):
        toolhead = self.printer.lookup_object("toolhead")
        position = toolhead.get_position()

        # If only probing Z:
        if probe_z and not (probe_x or probe_y):
            center_x = (
                self.sensor_location.x
                if self.sensor_location
                else (self.config_sensor_x if self.config_sensor_x is not None else position[0])
            )
            center_y = (
                self.sensor_location.y
                if self.sensor_location
                else (self.config_sensor_y if self.config_sensor_y is not None else position[1])
            )
            center_z = self.probe_multi_axis.run_probe("z-", gcmd)[2]
            position[2] = center_z + self.final_lift_z
            toolhead.manual_move([None, None, position[2]], self.lift_speed)
            toolhead.set_position(position)
            return Position(center_x, center_y, center_z)

        # If probing lateral axes without Z:
        if not probe_z and (probe_x or probe_y):
            if self.sensor_location and self.sensor_location.z != 0.0:
                top_z = self.sensor_location.z
            elif self.config_sensor_z is not None:
                top_z = self.config_sensor_z
            else:
                top_z = self.probe_multi_axis.run_probe("z-", gcmd, samples=1)[2]
            center_x, center_y = self.calibrate_xy(
                toolhead,
                [position[0], position[1], top_z],
                gcmd,
                self.spread,
                probe_x=probe_x,
                probe_y=probe_y,
            )
            center_z = top_z
            position[0] = center_x
            position[1] = center_y
            position[2] = center_z + self.final_lift_z
            toolhead.manual_move([None, None, position[2]], self.lift_speed)
            toolhead.manual_move(
                [position[0], position[1], None], self.travel_speed
            )
            toolhead.set_position(position)
            return Position(center_x, center_y, center_z)

        # Full or multi-axis probing with Z:
        downPos = self.probe_multi_axis.run_probe("z-", gcmd, samples=1)
        center_x, center_y = self.calibrate_xy(
            toolhead,
            downPos,
            gcmd,
            self.initial_spread,
            samples=1,
            probe_x=probe_x,
            probe_y=probe_y,
        )

        toolhead.manual_move(
            [None, None, downPos[2] + self.lift_z], self.lift_speed
        )
        toolhead.manual_move(
            [
                center_x if probe_x else None,
                center_y if probe_y else None,
                None,
            ],
            self.travel_speed,
        )
        center_z = self.probe_multi_axis.run_probe("z-", gcmd, speed_ratio=0.5)[
            2
        ]
        # Redo X and Y with accurate center Z
        center_x, center_y = self.calibrate_xy(
            toolhead,
            [center_x, center_y, center_z],
            gcmd,
            self.spread,
            probe_x=probe_x,
            probe_y=probe_y,
        )

        # Rest above center
        position[0] = center_x
        position[1] = center_y
        position[2] = center_z + self.final_lift_z
        toolhead.manual_move([None, None, position[2]], self.lift_speed)
        toolhead.manual_move(
            [position[0], position[1], None], self.travel_speed
        )
        toolhead.set_position(position)
        return Position(center_x, center_y, center_z)

    cmd_KTC_TOOL_LOCATE_SENSOR_help = (
        "Locate the tool calibration sensor, use with tool 0 or reference tool."
        + "\n [X] [Y] [Z] or [AXIS=ALL|X|Y|Z]"
    )

    def cmd_KTC_TOOL_LOCATE_SENSOR(self, gcmd: "gcode.GCodeCommand"):
        probe_x, probe_y, probe_z = self._parse_axes(gcmd)
        location = self.locate_sensor(
            gcmd, probe_x=probe_x, probe_y=probe_y, probe_z=probe_z
        )
        if self.sensor_location is not None:
            self.sensor_location = Position(
                location.x if probe_x else self.sensor_location.x,
                location.y if probe_y else self.sensor_location.y,
                location.z if probe_z else self.sensor_location.z,
            )
        else:
            self.sensor_location = Position(
                location.x if probe_x else (self.config_sensor_x if self.config_sensor_x is not None else 0.0),
                location.y if probe_y else (self.config_sensor_y if self.config_sensor_y is not None else 0.0),
                location.z if probe_z else (self.config_sensor_z if self.config_sensor_z is not None else 0.0),
            )
        self.last_result = self.sensor_location
        msg = "Sensor location at %.6f, %.6f, %.6f" % (
            self.sensor_location[0],
            self.sensor_location[1],
            self.sensor_location[2],
        )
        self.log_always(f"KTC Tools Calibrate: {msg}")
        self.gcode.respond_info(msg)

    cmd_KTC_TOOL_CALIBRATE_OFFSET_help = (
        "Calibrate current tool offset relative to reference sensor location."
        + "\n [X] [Y] [Z] or [AXIS=ALL|X|Y|Z] [SAVE=0|1]"
    )

    def cmd_KTC_TOOL_CALIBRATE_OFFSET(self, gcmd: "gcode.GCodeCommand"):
        if not self.sensor_location:
            raise gcmd.error(
                "No recorded sensor location, please run KTC_TOOL_LOCATE_SENSOR first or define sensor_x, sensor_y, sensor_z in config."
            )
        probe_x, probe_y, probe_z = self._parse_axes(gcmd)
        location = self.locate_sensor(
            gcmd, probe_x=probe_x, probe_y=probe_y, probe_z=probe_z
        )

        # Get existing offset for unprobed axes if available
        existing_offset = [0.0, 0.0, 0.0]
        if self.ktc is not None:
            tool_param = gcmd.get("TOOL", None)
            if tool_param is not None and tool_param.strip().lower() == "global":
                existing_offset = list(self.ktc.global_offset)
            else:
                target_tool = None
                if tool_param is not None or gcmd.get("T", None) is not None:
                    target_tool = self.ktc.get_tool_from_gcmd(gcmd)
                else:
                    target_tool = self.ktc.active_tool
                if (
                    target_tool
                    and target_tool != self.TOOL_UNKNOWN
                    and target_tool != self.TOOL_NONE
                ):
                    existing_offset = list(target_tool.offset)
        elif self.last_result is not None:
            existing_offset = [
                self.last_result.x,
                self.last_result.y,
                self.last_result.z,
            ]

        offset_x = (
            (location[0] - self.sensor_location[0])
            if probe_x
            else existing_offset[0]
        )
        offset_y = (
            (location[1] - self.sensor_location[1])
            if probe_y
            else existing_offset[1]
        )
        offset_z = (
            (location[2] - self.sensor_location[2])
            if probe_z
            else existing_offset[2]
        )
        self.last_result = Position(offset_x, offset_y, offset_z)

        msg = "Tool offset is %.6f, %.6f, %.6f" % (
            self.last_result[0],
            self.last_result[1],
            self.last_result[2],
        )
        self.log_always(f"KTC Tools Calibrate: {msg}")
        self.gcode.respond_info(msg)

        save_param = gcmd.get("SAVE", None)
        if save_param is not None and self.parse_bool(save_param):
            self.save_tool_offset(gcmd)

    cmd_KTC_TOOL_CALIBRATE_SAVE_help = (
        "Save tool offset calibration to KTC persistent storage or config."
        + "\n [TOOL: Tool name | global] or [T: Tool number]"
        + "\n [SECTION: Config section] [ATTRIBUTE: Config attribute]"
        + "\n [MACRO: Macro name] [VARIABLE: Macro variable]"
    )

    def cmd_KTC_TOOL_CALIBRATE_SAVE(self, gcmd: "gcode.GCodeCommand"):
        self.save_tool_offset(gcmd)

    def save_tool_offset(self, gcmd: "gcode.GCodeCommand"):
        if not self.last_result:
            raise gcmd.error(
                "No offset result, please run KTC_TOOL_CALIBRATE_OFFSET first"
            )

        # Legacy configfile.set support
        if gcmd.get("SECTION", None):
            section_name = gcmd.get("SECTION")
            param_name = gcmd.get("ATTRIBUTE")
            template = gcmd.get("VALUE", "{x:0.6f}, {y:0.6f}, {z:0.6f}")
            value = template.format(
                x=self.last_result.x, y=self.last_result.y, z=self.last_result.z
            )
            configfile = self.printer.lookup_object("configfile")
            configfile.set(section_name, param_name, value)
            self.gcode.respond_info(
                f"Saved offset to config [{section_name}] {param_name} = {value}"
            )
            return

        # Legacy gcode macro variable support
        if gcmd.get("MACRO", None):
            macro_name = gcmd.get("MACRO")
            variable_name = gcmd.get("VARIABLE")
            template = gcmd.get("VALUE", "({x:0.6f}, {y:0.6f}, {z:0.6f})")
            value = template.format(
                x=self.last_result.x, y=self.last_result.y, z=self.last_result.z
            )
            self.gcode.run_script_from_command(
                f'SET_GCODE_VARIABLE MACRO="{macro_name}" VARIABLE="{variable_name}" VALUE="{value}"'
            )
            self.gcode.respond_info(
                f"Saved offset to macro variable [{macro_name}] {variable_name} = {value}"
            )
            return

        # KTC native persistence & tool model integration
        if self.ktc is not None:
            tool_param = gcmd.get("TOOL", None)
            if tool_param is not None and tool_param.strip().lower() == "global":
                self.ktc.global_offset = [
                    self.last_result.x,
                    self.last_result.y,
                    self.last_result.z,
                ]
                self.ktc.persistent_state_set("global_offset", self.ktc.global_offset)
                msg = f"KTC Global offset set to: {self.ktc.global_offset}"
                self.log_always(msg)
                self.gcode.respond_info(msg)
                return

            # Resolve target tool
            target_tool: typing.Optional["ktc_tool.KtcTool"] = None
            if tool_param is not None or gcmd.get("T", None) is not None:
                target_tool = self.ktc.get_tool_from_gcmd(gcmd)
            else:
                target_tool = self.ktc.active_tool

            if (
                target_tool is None
                or target_tool == self.TOOL_UNKNOWN
                or target_tool == self.TOOL_NONE
            ):
                raise gcmd.error(
                    "No active tool mounted and no TOOL or T parameter provided. "
                    "Specify TOOL=<name> or T=<number>."
                )

            new_offset = [
                round(self.last_result.x, 6),
                round(self.last_result.y, 6),
                round(self.last_result.z, 6),
            ]
            target_tool.offset = new_offset
            target_tool.persistent_state_set("offset", target_tool.offset)
            self.last_calibrated_tool = target_tool.name
            msg = f"KTC Tool {target_tool.name} offset set to: {target_tool.offset}"
            self.log_always(msg)
            self.gcode.respond_info(msg)
            return

        raise gcmd.error(
            "KTC core is not loaded and no SECTION or MACRO parameter was specified."
        )

    cmd_KTC_TOOL_CALIBRATE_QUERY_help = (
        "Return the state of calibration probe"
    )

    def cmd_KTC_TOOL_CALIBRATE_QUERY(self, gcmd: "gcode.GCodeCommand"):
        toolhead = self.printer.lookup_object("toolhead")
        print_time = toolhead.get_last_move_time()
        endstop_states = [
            probe.query_endstop(print_time)
            for probe in self.probe_multi_axis.mcu_probe
        ]
        self.calibration_probe_inactive = any(endstop_states)
        gcmd.respond_info(
            "Calibration Probe: %s"
            % (["open", "TRIGGERED"][any(endstop_states)])
        )


class PrinterProbeMultiAxis:
    def __init__(
        self,
        tools_calibrate: KtcToolsCalibrate,
        config: "configfile.ConfigWrapper",
        mcu_probe_x: ProbeEndstopWrapper,
        mcu_probe_y: ProbeEndstopWrapper,
        mcu_probe_z: ProbeEndstopWrapper,
    ):
        self.tools_calibrate = tools_calibrate
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.mcu_probe = [mcu_probe_x, mcu_probe_y, mcu_probe_z]
        self.speed = config.getfloat("speed", 5.0, above=0.0)
        self.lift_speed = config.getfloat("lift_speed", self.speed, above=0.0)
        self.max_travel = config.getfloat("max_travel", 4, above=0)
        self.last_state = False
        self.last_result = [0.0, 0.0, 0.0]
        self.last_x_result = 0.0
        self.last_y_result = 0.0
        self.last_z_result = 0.0
        self.gcode = self.printer.lookup_object("gcode")
        self.gcode_move = self.printer.load_object(config, "gcode_move")

        # Multi-sample support (for improved accuracy)
        self.sample_count = config.getint("samples", 1, minval=1)
        self.sample_retract_dist = config.getfloat(
            "sample_retract_dist", 2.0, above=0.0
        )
        atypes = {"median": "median", "average": "average"}
        self.samples_result = config.getchoice(
            "samples_result", atypes, "average"
        )
        self.samples_tolerance = config.getfloat(
            "samples_tolerance", 0.100, minval=0.0
        )
        self.samples_retries = config.getint(
            "samples_tolerance_retries", 0, minval=0
        )
        # Register xyz_virtual_endstop pin
        self.printer.lookup_object("pins").register_chip(
            "probe_multi_axis", self
        )

    def setup_pin(self, pin_type, pin_params):
        if pin_type != "endstop" or pin_params["pin"] != "xy_virtual_endstop":
            raise pins.error("Probe virtual endstop only useful as endstop pin")
        if pin_params["invert"] or pin_params["pullup"]:
            raise pins.error("Can not pullup/invert probe virtual endstop")
        return self.mcu_probe

    def get_lift_speed(self, gcmd=None):
        if gcmd is not None:
            return gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.0)
        return self.lift_speed

    def _probe(self, speed, axis, sense, max_distance):
        phoming = self.printer.lookup_object("homing")
        pos = self._get_target_position(axis, sense, max_distance)
        try:
            epos = phoming.probing_move(self.mcu_probe[axis], pos, speed)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        self.gcode.respond_info(
            "Probe made contact at %.6f,%.6f,%.6f" % (epos[0], epos[1], epos[2])
        )
        return Position(*epos[:3])

    def _get_target_position(self, axis, sense, max_distance):
        toolhead = self.printer.lookup_object("toolhead")
        curtime = self.printer.get_reactor().monotonic()
        if (
            "x" not in toolhead.get_status(curtime)["homed_axes"]
            or "y" not in toolhead.get_status(curtime)["homed_axes"]
            or "z" not in toolhead.get_status(curtime)["homed_axes"]
        ):
            raise self.printer.command_error("Must home before probe")
        pos = toolhead.get_position()
        kin_status = toolhead.get_kinematics().get_status(curtime)
        if "axis_minimum" not in kin_status or "axis_maximum" not in kin_status:
            raise self.gcode.error(
                "Tools calibrate only works with kinematics that support axis minimum/maximum limits."
            )
        if sense > 0:
            pos[axis] = min(
                pos[axis] + max_distance, kin_status["axis_maximum"][axis]
            )
        else:
            pos[axis] = max(
                pos[axis] - max_distance, kin_status["axis_minimum"][axis]
            )
        return pos

    def _move(self, coord, speed):
        self.printer.lookup_object("toolhead").manual_move(coord, speed)

    def _calc_mean(self, positions):
        count = float(len(positions))
        return Position(
            *[sum([pos[i] for pos in positions]) / count for i in range(3)]
        )

    def _calc_median(self, positions, axis):
        axis_sorted = sorted(positions, key=(lambda p: p[axis]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return axis_sorted[middle]
        # even number of samples
        return self._calc_mean(axis_sorted[middle - 1 : middle + 1])

    def run_probe(
        self, direction, gcmd, speed_ratio=1.0, samples=None, max_distance=100.0
    ):
        speed = (
            gcmd.get_float("PROBE_SPEED", self.speed, above=0.0) * speed_ratio
        )
        if direction not in Directions:
            raise self.printer.command_error("Wrong value for DIRECTION.")

        self.tools_calibrate.log_trace(
            "ktc_tools_calibrate: run_probe direction = " + str(direction)
        )

        (axis, sense) = Directions[direction]

        self.tools_calibrate.log_trace(
            "ktc_tools_calibrate: run_probe axis = %d, sense = %d" % (axis, sense)
        )

        lift_speed = self.get_lift_speed(gcmd)
        sample_count = gcmd.get_int(
            "SAMPLES", samples if samples else self.sample_count, minval=1
        )
        sample_retract_dist = gcmd.get_float(
            "SAMPLE_RETRACT_DIST", self.sample_retract_dist, above=0.0
        )
        samples_tolerance = gcmd.get_float(
            "SAMPLES_TOLERANCE", self.samples_tolerance, minval=0.0
        )
        samples_retries = gcmd.get_int(
            "SAMPLES_TOLERANCE_RETRIES", self.samples_retries, minval=0
        )
        samples_result = gcmd.get("SAMPLES_RESULT", self.samples_result)

        probe_start = self.printer.lookup_object("toolhead").get_position()
        retries = 0
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(speed, axis, sense, max_distance)
            self.tools_calibrate.log_trace(
                f"ktc_tools_calibrate: run_probe result {probe_start=} {pos=}"
            )
            positions.append(pos)
            # Check samples tolerance
            axis_positions = [p[axis] for p in positions]
            if max(axis_positions) - min(axis_positions) > samples_tolerance:
                if retries >= samples_retries:
                    raise gcmd.error("Probe samples exceed samples_tolerance")
                gcmd.respond_info("Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
            # Retract
            if len(positions) < sample_count:
                liftpos = probe_start
                liftpos[axis] = pos[axis] - sense * sample_retract_dist
                self._move(liftpos, lift_speed)
        # Calculate and return result
        if samples_result == "median":
            return self._calc_median(positions, axis)
        return self._calc_mean(positions)


# Endstop wrapper that enables probe specific features
class ProbeEndstopWrapper:
    def __init__(self, config, axis):
        self.printer = config.get_printer()
        self.axis = axis
        self.idex = config.has_section("dual_carriage")
        # Create an "endstop" object to handle the probe pin
        ppins = self.printer.lookup_object("pins")
        pin = config.get("pin")
        ppins.allow_multi_use_pin(pin.replace("^", "").replace("!", ""))
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params["chip"]
        self.mcu_endstop = mcu.setup_pin("endstop", pin_params)
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self._get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop

    def _get_steppers(self):
        if self.idex and self.axis == "x":
            dual_carriage = self.printer.lookup_object("dual_carriage")
            prime_rail = dual_carriage.get_primary_rail()
            return prime_rail.get_rail().get_steppers()
        else:
            return self.mcu_endstop.get_steppers()

    def _handle_mcu_identify(self):
        kin = self.printer.lookup_object("toolhead").get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis(self.axis):
                self.add_stepper(stepper)

    def get_position_endstop(self):
        return 0.0


def load_config(config: "configfile.ConfigWrapper"):
    return KtcToolsCalibrate(config)
