# KTC - Klipper Tool Changer code (v.2)
# Extended Tool Safety module
#
# This file is part of the KTC extension for the Klipper firmware.
#
# Copyright (C) 2024 Andrei Ignat <andrei@ignat.se>
# Copyright (C) 2026 Asher Edwards <asher@fiatnovum.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
from __future__ import annotations
import logging
import typing

if typing.TYPE_CHECKING:
    from ...klipper.klippy import configfile
    from ...klipper.klippy.extras import gcode_macro as klippy_gcode_macro
    from . import ktc, ktc_log, ktc_tool, ktc_toolchanger, ktc_base


class KtcSwitchSensor:
    """Encapsulates a physical microswitch / optical sensor pin using Klipper's buttons."""

    def __init__(
        self,
        printer,
        config: "configfile.ConfigWrapper",
        pin_name: str,
        callback=None,
    ):
        self.printer = printer
        self.config = config
        self.pin_name = pin_name.strip() if pin_name else ""
        self.callback = callback
        self.state: bool = False
        self.event_count: int = 0
        self.last_eventtime: float = 0.0

        if self.pin_name:
            self._setup_sensor()

    def _setup_sensor(self):
        try:
            ppins = self.printer.lookup_object("pins")
            clean_pin = self.pin_name.replace("^", "").replace("!", "").replace("~", "").strip()
            ppins.allow_multi_use_pin(clean_pin)
        except Exception:
            pass

        buttons = self.printer.load_object(self.config, "buttons")
        buttons.register_buttons([self.pin_name], self._handle_button_event)

    def _handle_button_event(self, eventtime, state):
        self.state = bool(state)
        self.event_count += 1
        self.last_eventtime = eventtime
        logging.debug(
            "KtcSwitchSensor [%s] event #%d: state=%s",
            self.pin_name,
            self.event_count,
            self.state,
        )
        if self.callback:
            self.callback(eventtime, self.state)

    def query(self) -> bool:
        return self.state

    def is_triggered(self) -> bool:
        return self.state


class KtcSafety:
    """Safety controller attached to a KtcToolchanger."""

    def __init__(self, toolchanger: "ktc_toolchanger.KtcToolchanger", config: "configfile.ConfigWrapper"):
        self.toolchanger = toolchanger
        self.printer = toolchanger.printer
        self.config = config

        self.enabled: bool = True
        self.carriage_sensor: typing.Optional[KtcSwitchSensor] = None
        self._last_drop_eventtime: float = 0.0
        self._last_mount_eventtime: float = 0.0
        self._last_dismount_eventtime: float = 0.0
        self._mounted_by_machine: bool = False
        self._in_toolchange: bool = False
        self._reboot_timer = None
        self._pending_reboot_msg: typing.Optional[str] = None
        self._pending_reboot_gcode: typing.Optional[str] = None
        self._pending_reboot_tool: typing.Optional[typing.Any] = None

        # Register carriage sensor during __init__ before MCU connects and builds config
        pin = getattr(self.toolchanger, "tool_present_pin", None) or self.config.get("tool_present_pin", None)
        if pin:
            self.carriage_sensor = KtcSwitchSensor(
                self.printer,
                self.config,
                pin,
                callback=self._handle_sensor_change,
            )

    def begin_toolchange(self):
        self._in_toolchange = True

    def end_toolchange(self):
        self._in_toolchange = False

    def set_mounted_by_machine(self, value: bool):
        self._mounted_by_machine = bool(value)

    def configure_inherited_params(self):
        """Called during configure_inherited_params phase after all objects are loaded."""
        if self.carriage_sensor is None:
            pin = getattr(self.toolchanger, "tool_present_pin", None) or self.config.get("tool_present_pin", None)
            if pin:
                self.carriage_sensor = KtcSwitchSensor(
                    self.printer,
                    self.config,
                    pin,
                    callback=self._handle_sensor_change,
                )

    def _resolve_gcode_param(
        self,
        attr_name: str,
        tool: typing.Optional["ktc_tool.KtcTool"] = None,
        default: str = "",
    ) -> str:
        """Resolves gcode parameter, prioritizing tool, then toolchanger, then top ktc object."""
        for obj in (tool, self.toolchanger, getattr(self.toolchanger, "_ktc", None)):
            if obj is not None and obj not in getattr(self.toolchanger, "INVALID_TOOLS", ()):
                val = getattr(obj, attr_name, None)
                if val:
                    return val
        return default

    def _get_error_gcode(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> str:
        return self._resolve_gcode_param("_on_tool_change_error_gcode", tool=tool, default="PAUSE")

    def _get_drop_gcode(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> str:
        return self._resolve_gcode_param("_on_tool_drop_gcode", tool=tool, default="PAUSE")

    def _get_mount_gcode(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> str:
        return self._resolve_gcode_param("_on_tool_mount_gcode", tool=tool, default="")

    def _get_dismount_gcode(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> str:
        return self._resolve_gcode_param("_on_tool_dismount_gcode", tool=tool, default="")

    def _is_printer_moving(self, eventtime: float) -> bool:
        # Check idle_timeout (standard Klipper printing check as in filament_switch_sensor)
        try:
            idle_timeout = self.printer.lookup_object("idle_timeout", None)
            if idle_timeout is not None and idle_timeout.get_status(eventtime).get("state", "") == "Printing":
                return True
        except Exception:
            pass

        # Check print_stats (if printing from SD / virtual_sdcard)
        try:
            print_stats = self.printer.lookup_object("print_stats", None)
            if print_stats is not None and print_stats.get_status(eventtime).get("state", "") == "printing":
                return True
        except Exception:
            pass

        return False

    def _handle_sensor_change(
        self,
        eventtime: float,
        state: bool,
        tool: typing.Optional["ktc_tool.KtcTool"] = None,
    ):
        """Real-time callback from switch pin change."""
        if not self.enabled or self._in_toolchange:
            return

        tc_state = self.toolchanger.state
        active_tool = self.toolchanger.selected_tool
        if (active_tool in self.toolchanger.INVALID_TOOLS or active_tool is None) and self.toolchanger._ktc:
            active_tool = self.toolchanger._ktc.active_tool

        target_tool = tool if tool is not None else active_tool

        # Suppress automatic reactions during intentional tool transitions or unconfigured states
        transition_states = (
            self.toolchanger.StateType.NOT_CONFIGURED,
            self.toolchanger.StateType.CONFIGURING,
            self.toolchanger.StateType.CONFIGURED,
            self.toolchanger.StateType.UNINITIALIZED,
            self.toolchanger.StateType.INITIALIZING,
            self.toolchanger.StateType.CHANGING,
            self.toolchanger.StateType.ENGAGING,
            self.toolchanger.StateType.DISENGAGING,
            self.toolchanger.StateType.SELECTING,
            self.toolchanger.StateType.DESELECTING,
        )
        if tc_state in transition_states:
            return

        if self.toolchanger._ktc is not None and self.toolchanger._ktc.state in (
            self.toolchanger.StateType.CHANGING,
            self.toolchanger.StateType.SELECTING,
            self.toolchanger.StateType.DESELECTING,
        ):
            return

        if (
            target_tool is not None
            and target_tool not in self.toolchanger.INVALID_TOOLS
            and target_tool.state in transition_states
        ):
            return

        if any(
            t.state in (
                self.toolchanger.StateType.SELECTING,
                self.toolchanger.StateType.DESELECTING,
                self.toolchanger.StateType.CHANGING,
            )
            for t in self.toolchanger.tools.values()
        ):
            return

        # --- SENSOR STATE: UNTRIGGERED (False) -> Tool Detached / Dismounted / Dropped ---
        if not state:
            # Check if this detachment should be treated as an unexpected DROP:
            # 1. The machine had mounted the tool and it came detached, OR
            # 2. The printer was moving around and the tool was on the toolhead
            is_machine_mounted = getattr(self, "_mounted_by_machine", False)
            is_moving = self._is_printer_moving(eventtime)

            if is_machine_mounted or is_moving:
                # If event came from a specific tool, only process if it is the currently attached tool
                if tool is not None and active_tool is not None and tool != active_tool:
                    return

                # Debounce drop events by at least 1 second
                if eventtime - self._last_drop_eventtime < 1.0:
                    return
                self._last_drop_eventtime = eventtime

                tool_obj = active_tool if active_tool and active_tool not in self.toolchanger.INVALID_TOOLS else tool
                tool_name = (
                    tool_obj.name
                    if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS
                    else "unknown"
                )

                if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS:
                    tool_obj.state = self.toolchanger.StateType.ERROR

                self.toolchanger.state = self.toolchanger.StateType.ERROR
                self._mounted_by_machine = False

                reason = "during motion" if is_moving else "while mounted by machine"
                msg = (
                    f"KTC SAFETY ALERT: Tool drop detected on toolchanger '{self.toolchanger.name}' ({reason})! "
                    f"Active tool '{tool_name}' detached unexpectedly."
                )
                if self.toolchanger.log:
                    self.toolchanger.log.always(msg)
                else:
                    self.printer.lookup_object("gcode").respond_info(msg)

                self._run_gcode_callback(
                    self._get_drop_gcode(tool=tool_obj),
                    tool=tool_obj,
                )

            else:
                # Manual dismount while idle / stationary
                if eventtime - self._last_dismount_eventtime < 1.0:
                    return
                self._last_dismount_eventtime = eventtime

                tool_obj = active_tool if active_tool and active_tool not in self.toolchanger.INVALID_TOOLS else tool
                tool_name = tool_obj.name if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS else "unknown"

                self.toolchanger.selected_tool = self.toolchanger.TOOL_NONE
                if self.toolchanger._ktc:
                    self.toolchanger._ktc.active_tool = self.toolchanger.TOOL_NONE

                if self.toolchanger.state != self.toolchanger.StateType.ERROR:
                    self.toolchanger.state = self.toolchanger.StateType.READY
                if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS:
                    if tool_obj.state != self.toolchanger.StateType.ERROR:
                        tool_obj.state = self.toolchanger.StateType.READY

                self._mounted_by_machine = False

                if tc_state == self.toolchanger.StateType.ERROR:
                    msg = (
                        f"KTC SAFETY: Tool '{tool_name}' manually dismounted from '{self.toolchanger.name}'. "
                        "Safety lock remains active: run KTC_SAFETY_UNLOCK to resume."
                    )
                else:
                    msg = f"KTC SAFETY: Tool '{tool_name}' manually dismounted from '{self.toolchanger.name}'."
                if self.toolchanger.log:
                    self.toolchanger.log.always(msg)
                else:
                    self.printer.lookup_object("gcode").respond_info(msg)

                self._run_gcode_callback(
                    self._get_dismount_gcode(tool=tool_obj),
                    tool=tool_obj,
                )

        # --- SENSOR STATE: TRIGGERED (True) -> Tool Attached / Mounted / Reconnected ---
        else:
            if eventtime - self._last_mount_eventtime < 1.0:
                return
            self._last_mount_eventtime = eventtime

            tool_obj = tool
            if (tool_obj is None or tool_obj in self.toolchanger.INVALID_TOOLS):
                if active_tool and active_tool not in self.toolchanger.INVALID_TOOLS:
                    tool_obj = active_tool
                else:
                    tool_obj = self.get_physically_attached_tool()

            tool_name = (
                tool_obj.name
                if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS
                else "unknown"
            )

            # Manual attachment or reconnection
            self._mounted_by_machine = False

            if tc_state == self.toolchanger.StateType.ERROR:
                # Tool reconnected after error / tool drop
                if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS:
                    self.toolchanger.selected_tool = tool_obj
                    if self.toolchanger._ktc:
                        self.toolchanger._ktc.active_tool = tool_obj
                    tool_obj.state = self.toolchanger.StateType.ERROR

                msg = (
                    f"KTC SAFETY: Tool '{tool_name}' sensor indicates tool re-connected on '{self.toolchanger.name}'. "
                    "Safety lock remains active: run KTC_SAFETY_UNLOCK to resume."
                )
                if self.toolchanger.log:
                    self.toolchanger.log.always(msg)
                else:
                    self.printer.lookup_object("gcode").respond_info(msg)

                self._run_gcode_callback(
                    self._get_mount_gcode(tool=tool_obj),
                    tool=tool_obj,
                )

            else:
                # Manual mount onto carriage
                if tool_obj and tool_obj not in self.toolchanger.INVALID_TOOLS:
                    self.toolchanger.selected_tool = tool_obj
                    if self.toolchanger._ktc:
                        self.toolchanger._ktc.active_tool = tool_obj
                    tool_obj.state = self.toolchanger.StateType.ENGAGED
                    self.toolchanger.state = self.toolchanger.StateType.ENGAGED

                msg = f"KTC SAFETY: Tool '{tool_name}' manually mounted on '{self.toolchanger.name}'."
                if self.toolchanger.log:
                    self.toolchanger.log.always(msg)
                else:
                    self.printer.lookup_object("gcode").respond_info(msg)

                self._run_gcode_callback(
                    self._get_mount_gcode(tool=tool_obj),
                    tool=tool_obj,
                )

    def get_physically_attached_tool(self) -> typing.Optional["ktc_tool.KtcTool"]:
        """Scans all tools on this toolchanger to find which tool's present sensor is triggered."""
        tools_list = list(self.toolchanger.tools.values())
        if not tools_list and getattr(self.toolchanger, "_ktc", None):
            tools_list = [
                t for t in self.toolchanger._ktc.all_tools.values()
                if t not in self.toolchanger.INVALID_TOOLS and getattr(t, "toolchanger", None) == self.toolchanger
            ]
        for tool in tools_list:
            sensor = getattr(tool, "tool_present_sensor", None)
            if sensor is not None and sensor.is_triggered():
                return tool
        return None

    def query_tool_present(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> typing.Optional[bool]:
        """Unified sensor resolution:
        1. Checks tool-specific sensor (if defined on tool).
        2. Checks toolchanger carriage sensor (if defined).
        3. If tool is unspecified/unknown, checks if ANY tool sensor on this toolchanger is triggered.
        4. If sensors exist on tools but none are triggered, returns False.
        5. Returns None if no sensor is configured anywhere.
        """
        # If a specific tool is provided and valid, check tool sensor and/or carriage sensor
        if tool is not None and tool not in self.toolchanger.INVALID_TOOLS:
            tool_sensor = getattr(tool, "tool_present_sensor", None)
            if tool_sensor is not None and self.carriage_sensor is not None:
                return tool_sensor.is_triggered() or self.carriage_sensor.is_triggered()
            if tool_sensor is not None:
                return tool_sensor.is_triggered()
            if self.carriage_sensor is not None:
                return self.carriage_sensor.is_triggered()
            return None

        # Tool is unspecified or in INVALID_TOOLS (e.g. reboot check or unlock)
        if self.carriage_sensor is not None and self.carriage_sensor.is_triggered():
            return True

        # Check all configured tool sensors on this toolchanger
        tools_list = list(self.toolchanger.tools.values())
        if not tools_list and getattr(self.toolchanger, "_ktc", None):
            tools_list = [
                t for t in self.toolchanger._ktc.all_tools.values()
                if t not in self.toolchanger.INVALID_TOOLS and getattr(t, "toolchanger", None) == self.toolchanger
            ]
        tool_sensors = [
            t.tool_present_sensor
            for t in tools_list
            if getattr(t, "tool_present_sensor", None) is not None
        ]
        if tool_sensors:
            return any(s.is_triggered() for s in tool_sensors)

        if self.carriage_sensor is not None:
            return self.carriage_sensor.is_triggered()

        return None

    def has_sensor(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> bool:
        """Returns True if any physical sensor is available for this toolchanger or tool."""
        if tool is not None and tool not in self.toolchanger.INVALID_TOOLS:
            return (
                getattr(tool, "tool_present_sensor", None) is not None
                or self.carriage_sensor is not None
            )
        tools_list = list(self.toolchanger.tools.values())
        if not tools_list and getattr(self.toolchanger, "_ktc", None):
            tools_list = [
                t for t in self.toolchanger._ktc.all_tools.values()
                if t not in self.toolchanger.INVALID_TOOLS and getattr(t, "toolchanger", None) == self.toolchanger
            ]
        return (
            self.carriage_sensor is not None
            or any(getattr(t, "tool_present_sensor", None) is not None for t in tools_list)
        )

    def verify_tool_pickup(self, tool: "ktc_tool.KtcTool"):
        """Called after tool_select_gcode to verify tool is physically mounted."""
        if not self.enabled or not getattr(self.toolchanger, "verify_tool_pickup", True):
            return

        if not self.has_sensor(tool):
            return

        # Ensure all queued movements from tool_select_gcode have physically completed
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is not None:
            toolhead.wait_moves()

        # Wait up to 1.5 seconds for sensor event to be received across MCU/CAN bus
        reactor = self.printer.get_reactor()
        end_time = reactor.monotonic() + 1.5
        is_present = self.query_tool_present(tool)
        while is_present is not True and reactor.monotonic() < end_time:
            reactor.pause(reactor.monotonic() + 0.05)
            is_present = self.query_tool_present(tool)

        if is_present is not True:
            sensor = getattr(tool, "tool_present_sensor", None) or self.carriage_sensor
            if sensor:
                diag = (
                    f" (pin: {sensor.pin_name}, state: {sensor.state}, events: {sensor.event_count}). "
                    "Invert pin logic with '!' in pin name if reversed (e.g. '!pin')"
                )
            else:
                diag = ""
            msg = (
                f"KTC SAFETY ERROR: Pickup verification failed for tool '{tool.name}' "
                f"on toolchanger '{self.toolchanger.name}'. Switch indicates tool is not attached{diag}."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            else:
                self.printer.lookup_object("gcode").respond_info(msg)
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            tool.state = tool.StateType.ERROR
            self._run_gcode_callback(
                self._get_error_gcode(tool=tool),
                tool=tool,
            )
            raise self.printer.command_error(msg)

    def verify_tool_dropoff(self, tool: "ktc_tool.KtcTool"):
        """Called after tool_deselect_gcode to verify tool is physically detached."""
        if not self.enabled or not getattr(self.toolchanger, "verify_tool_dropoff", True):
            return

        if not self.has_sensor(tool) and getattr(tool, "dock_sensor", None) is None:
            return

        # Ensure all queued movements from tool_deselect_gcode have physically completed
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is not None:
            toolhead.wait_moves()

        # Wait up to 1.5 seconds for sensor events to settle
        reactor = self.printer.get_reactor()
        end_time = reactor.monotonic() + 1.5
        while reactor.monotonic() < end_time:
            is_present = self.query_tool_present(tool)
            dock_sensor = getattr(tool, "dock_sensor", None)
            dock_ok = dock_sensor.is_triggered() if dock_sensor is not None else None
            # Success when tool is no longer on carriage and dock sensor (if present) confirms parked
            if is_present is False and (dock_ok is True or dock_ok is None):
                return
            reactor.pause(reactor.monotonic() + 0.05)

        is_present = self.query_tool_present(tool)
        dock_sensor = getattr(tool, "dock_sensor", None)
        dock_ok = dock_sensor.is_triggered() if dock_sensor is not None else None

        if is_present is True or dock_ok is False:
            if is_present is True:
                sensor = getattr(tool, "tool_present_sensor", None) or self.carriage_sensor
                if sensor:
                    diag = (
                        f" (pin: {sensor.pin_name}, state: {sensor.state}, events: {sensor.event_count}). "
                        "Invert pin logic with '!' in pin name if reversed (e.g. '!pin')"
                    )
                else:
                    diag = ""
                detail = f"Switch indicates tool is still attached{diag}"
            else:
                dock_sensor = getattr(tool, "dock_sensor", None)
                diag = f" (pin: {dock_sensor.pin_name})" if dock_sensor else ""
                detail = f"Dock sensor indicates tool not seated in dock{diag}"
            msg = (
                f"KTC SAFETY ERROR: Dropoff verification failed for tool '{tool.name}' "
                f"on toolchanger '{self.toolchanger.name}'. {detail}."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            else:
                self.printer.lookup_object("gcode").respond_info(msg)
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            tool.state = tool.StateType.ERROR
            self._run_gcode_callback(
                self._get_error_gcode(tool=tool),
                tool=tool,
            )
            raise self.printer.command_error(msg)

    def _resolve_tool_from_state_or_sensor(self) -> typing.Tuple[typing.Optional["ktc_tool.KtcTool"], typing.Optional[bool]]:
        """Resolves tool identity from toolchanger state, persistent state, or active physical sensor.
        Returns a tuple of (resolved_tool, is_present)."""
        tool = self.toolchanger.selected_tool
        if tool in self.toolchanger.INVALID_TOOLS or tool is None:
            persisted_name = str.lower(
                self.toolchanger.persistent_state.get(
                    "selected_tool", self.toolchanger.TOOL_UNKNOWN.name
                )
            )
            if persisted_name not in (
                self.toolchanger.TOOL_NONE.name.lower(),
                self.toolchanger.TOOL_UNKNOWN.name.lower(),
            ):
                matched = None
                for t_name, t_obj in self.toolchanger.tools.items():
                    if t_name.lower() == persisted_name:
                        matched = t_obj
                        break
                if matched is None and getattr(self.toolchanger, "_ktc", None):
                    for t_name, t_obj in self.toolchanger._ktc.all_tools.items():
                        if t_name.lower() == persisted_name and getattr(t_obj, "toolchanger", None) == self.toolchanger:
                            matched = t_obj
                            break
                if matched:
                    tool = matched
                    self.toolchanger.selected_tool = tool
            elif persisted_name == self.toolchanger.TOOL_NONE.name.lower():
                self.toolchanger.selected_tool = self.toolchanger.TOOL_NONE

        if (tool in self.toolchanger.INVALID_TOOLS or tool is None) and self.toolchanger._ktc:
            tool = self.toolchanger._ktc.active_tool

        is_present = self.query_tool_present(tool)

        if is_present is True and (tool in self.toolchanger.INVALID_TOOLS or tool is None):
            detected_tool = self.get_physically_attached_tool()
            if detected_tool:
                tool = detected_tool
                self.toolchanger.selected_tool = tool

        return tool, is_present

    def check_reboot_state(self):
        """Called during _handle_ready. If a tool is physically sensed or tracked as attached on reboot, enter ERROR state."""
        if not self.enabled or not getattr(self.toolchanger, "prevent_toolchange_on_reboot_attached", True):
            return

        # Give reactor a brief moment to process any pending async button state events from MCU
        reactor = self.printer.get_reactor()
        reactor.pause(reactor.monotonic() + 0.1)

        tool, is_present = self._resolve_tool_from_state_or_sensor()

        # Determine if tool is attached:
        # 1. Physical sensor confirms tool is present (is_present is True)
        # 2. No physical sensor exists (is_present is None), fall back to persistent software state
        is_attached = False
        if is_present is True:
            is_attached = True
        elif is_present is None:
            if tool is not None and tool not in self.toolchanger.INVALID_TOOLS:
                is_attached = True

        delay = (
            getattr(tool, "on_reboot_tool_attached_delay", None)
            if tool and tool not in self.toolchanger.INVALID_TOOLS
            else None
        )
        if delay is None:
            delay = getattr(self.toolchanger, "on_reboot_tool_attached_delay", None)
        if delay is None and self.toolchanger._ktc:
            delay = getattr(self.toolchanger._ktc, "on_reboot_tool_attached_delay", None)
        if delay is None:
            delay = 2.0

        if is_attached:
            tool_name = (
                tool.name
                if tool and tool not in self.toolchanger.INVALID_TOOLS
                else "unknown"
            )
            detection_source = "physically detected" if is_present is True else "software state indicates tool"
            msg = (
                f"KTC SAFETY WARNING: Tool '{tool_name}' {detection_source} attached on reboot on '{self.toolchanger.name}'! "
                "Toolchanger locked in ERROR state to prevent unexpected tool changes. "
                "Run KTC_SAFETY_UNLOCK to proceed."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            else:
                self.printer.lookup_object("gcode").respond_info(msg)

            self.toolchanger.state = self.toolchanger.StateType.ERROR
            if tool and tool not in self.toolchanger.INVALID_TOOLS:
                tool.state = tool.StateType.ERROR
            if self.toolchanger._ktc and tool and tool not in self.toolchanger.INVALID_TOOLS:
                self.toolchanger._ktc.active_tool = tool

            reboot_gcode = (
                getattr(tool, "_on_reboot_tool_attached_gcode", None)
                or getattr(self.toolchanger, "_on_reboot_tool_attached_gcode", None)
                or (getattr(self.toolchanger._ktc, "_on_reboot_tool_attached_gcode", None) if self.toolchanger._ktc else None)
                or ""
            )
            self._schedule_reboot_action(msg, reboot_gcode, tool, delay)
        elif is_present is False and tool not in self.toolchanger.INVALID_TOOLS and tool is not None:
            # Active tool was tracked in persistent state, but physically NOT attached on reboot!
            msg = (
                f"KTC SAFETY WARNING: Software state indicates Tool '{tool.name}' was active, "
                f"but physical sensor indicates tool is NOT attached on '{self.toolchanger.name}'! "
                "Toolchanger locked in ERROR state. Re-attach tool and run KTC_SAFETY_UNLOCK to proceed."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            else:
                self.printer.lookup_object("gcode").respond_info(msg)

            self.toolchanger.state = self.toolchanger.StateType.ERROR
            tool.state = tool.StateType.ERROR
            if self.toolchanger._ktc:
                self.toolchanger._ktc.active_tool = tool
            self._schedule_reboot_action(msg, self._get_error_gcode(tool=tool), tool, delay)

    def _schedule_reboot_action(
        self,
        msg: str,
        gcode: str,
        tool: typing.Optional["ktc_tool.KtcTool"],
        delay: float,
    ):
        if delay <= 0:
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            else:
                self.printer.lookup_object("gcode").respond_info(msg)
            self._run_gcode_callback(gcode, tool=tool)
            return

        reactor = self.printer.get_reactor()
        if self._reboot_timer is not None:
            reactor.update_timer(self._reboot_timer, reactor.NEVER)
            self._reboot_timer = None

        self._pending_reboot_msg = msg
        self._pending_reboot_gcode = gcode
        self._pending_reboot_tool = tool

        self._reboot_timer = reactor.register_timer(
            self._handle_reboot_attached_timer,
            reactor.monotonic() + delay,
        )

    def _handle_reboot_attached_timer(self, eventtime):
        self._reboot_timer = None
        if self.toolchanger.state == self.toolchanger.StateType.ERROR:
            if self._pending_reboot_msg:
                if self.toolchanger.log:
                    self.toolchanger.log.always(self._pending_reboot_msg)
                else:
                    self.printer.lookup_object("gcode").respond_info(self._pending_reboot_msg)
            if self._pending_reboot_gcode:
                self._run_gcode_callback(
                    self._pending_reboot_gcode,
                    tool=self._pending_reboot_tool,
                )
        self._pending_reboot_msg = None
        self._pending_reboot_gcode = None
        self._pending_reboot_tool = None
        return self.printer.get_reactor().NEVER

    def unlock(self):
        """Clears ERROR state and synchronizes tool state based on sensor query or prior state."""
        if self._reboot_timer is not None:
            reactor = self.printer.get_reactor()
            reactor.update_timer(self._reboot_timer, reactor.NEVER)
            self._reboot_timer = None
            self._pending_reboot_msg = None
            self._pending_reboot_gcode = None
            self._pending_reboot_tool = None

        # Give reactor a brief moment to process any pending async button state events
        reactor = self.printer.get_reactor()
        reactor.pause(reactor.monotonic() + 0.05)

        tool, is_present = self._resolve_tool_from_state_or_sensor()

        # Determine if tool is attached:
        # True: physical sensor says attached
        # False: physical sensor says NOT attached
        # None: no physical sensor; fall back to software state (selected_tool)
        tool_attached = (is_present is True) or (
            is_present is None
            and self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS
        )

        if tool_attached:
            if self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS:
                self.toolchanger.selected_tool.state = self.toolchanger.StateType.ENGAGED
                self.toolchanger.state = self.toolchanger.StateType.ENGAGED
                if self.toolchanger._ktc:
                    self.toolchanger._ktc.active_tool = self.toolchanger.selected_tool
                msg = (
                    f"KTC SAFETY: Unlocked '{self.toolchanger.name}'. "
                    f"Tool '{self.toolchanger.selected_tool.name}' is attached (ENGAGED). "
                    "Normal deselect will run on subsequent toolchange."
                )
            else:
                self.toolchanger.state = self.toolchanger.StateType.ENGAGED
                msg = (
                    f"KTC SAFETY: Unlocked '{self.toolchanger.name}'. "
                    "Tool attached but identity unknown. Use KTC_SET_ACTIVE_TOOL to specify tool if desired."
                )
        else:
            # Sensor confirms no tool attached, or no sensor is configured and software state was TOOL_NONE
            self.toolchanger.selected_tool = self.toolchanger.TOOL_NONE
            self.toolchanger.state = self.toolchanger.StateType.READY
            if self.toolchanger._ktc:
                self.toolchanger._ktc.active_tool = self.toolchanger.TOOL_NONE
            msg = (
                f"KTC SAFETY: Unlocked '{self.toolchanger.name}'. "
                "Carriage empty (TOOL_NONE, READY). Ready for tool selection."
            )

        self._mounted_by_machine = False

        # Reset ERROR state on tools belonging to this toolchanger
        for t in self.toolchanger.tools.values():
            if tool_attached and t == self.toolchanger.selected_tool:
                t.state = self.toolchanger.StateType.ENGAGED
            elif t.state == self.toolchanger.StateType.ERROR:
                t.state = self.toolchanger.StateType.READY

        # Clear error on top ktc object if it was in error
        if self.toolchanger._ktc and self.toolchanger._ktc.state == self.toolchanger.StateType.ERROR:
            self.toolchanger._ktc.state = self.toolchanger.state

        if self.toolchanger.log:
            self.toolchanger.log.always(msg)
        else:
            self.printer.lookup_object("gcode").respond_info(msg)

    def _run_gcode_callback(self, gcode_str: str, tool: typing.Optional["ktc_tool.KtcTool"] = None):
        if not gcode_str or not gcode_str.strip():
            return
        try:
            gcode_macro: "klippy_gcode_macro.PrinterGCodeMacro" = self.printer.lookup_object("gcode_macro")
            template = gcode_macro.load_template(self.config, "", gcode_str)
            context = template.create_template_context()
            if tool is not None and tool not in self.toolchanger.INVALID_TOOLS:
                context["myself"] = tool.get_status()
            else:
                context["myself"] = self.toolchanger.get_status()
            context["toolchanger"] = self.toolchanger.get_status()
            if self.toolchanger._ktc is not None:
                context["ktc"] = self.toolchanger._ktc.get_status()
            context["STATE_TYPE"] = self.toolchanger.StateType
            template.run_gcode_from_command(context)
        except Exception as e:
            msg = f"KTC SAFETY: Error running safety callback: {e}"
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            self.printer.lookup_object("gcode").respond_info(msg)
