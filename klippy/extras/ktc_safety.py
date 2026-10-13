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
import typing

if typing.TYPE_CHECKING:
    from ...klipper.klippy import configfile
    from ...klipper.klippy.extras import gcode_macro as klippy_gcode_macro
    from . import ktc, ktc_log, ktc_tool, ktc_toolchanger, ktc_base


class KtcSwitchSensor:
    """Encapsulates a physical microswitch / optical sensor pin using Klipper's pins and buttons."""

    def __init__(self, printer, config: "configfile.ConfigWrapper", pin_name: str, callback=None):
        self.printer = printer
        self.config = config
        self.pin_name = pin_name.strip() if pin_name else ""
        self.callback = callback
        self.state: bool = False

        if self.pin_name:
            self._setup_sensor()

    def _setup_sensor(self):
        ppins = self.printer.lookup_object("pins")
        # Allow multi-use pin if referenced elsewhere
        clean_pin = self.pin_name.replace("^", "").replace("!", "")
        ppins.allow_multi_use_pin(clean_pin)
        pin_params = ppins.lookup_pin(self.pin_name, can_invert=True, can_pullup=True)

        buttons = self.printer.load_object(self.config, "buttons")
        buttons.register_buttons([pin_params], self._handle_button_event)

    def _handle_button_event(self, eventtime, state):
        self.state = bool(state)
        if self.callback:
            self.callback(eventtime, self.state)

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

    def configure_inherited_params(self):
        """Called during configure_inherited_params phase after all objects are loaded."""
        pin = getattr(self.toolchanger, "tool_present_pin", None)
        if pin and self.carriage_sensor is None:
            self.carriage_sensor = KtcSwitchSensor(
                self.printer,
                self.config,
                pin,
                callback=self._handle_sensor_change,
            )

    def _handle_sensor_change(self, eventtime: float, state: bool):
        """Real-time callback from switch pin change."""
        if not self.enabled:
            return

        tc_state = self.toolchanger.state
        # Suppress drop detection during intentional tool changes or unconfigured states
        if tc_state in (
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
            self.toolchanger.StateType.READY,
            self.toolchanger.StateType.ERROR,
        ):
            return

        # If carriage is in ENGAGED or ACTIVE, the tool should be locked.
        # If switch transitioned to untriggered (False), a tool drop occurred!
        if not state:
            # Debounce drop events by at least 1 second
            if eventtime - self._last_drop_eventtime < 1.0:
                return
            self._last_drop_eventtime = eventtime

            tool_name = (
                self.toolchanger.selected_tool.name
                if self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS
                else "unknown"
            )
            msg = (
                f"KTC SAFETY ALERT: Tool drop detected on toolchanger '{self.toolchanger.name}'! "
                f"Active tool '{tool_name}' detached unexpectedly."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)

            # Transition state to ERROR
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            if (
                self.toolchanger.selected_tool
                and self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS
            ):
                self.toolchanger.selected_tool.state = self.toolchanger.StateType.ERROR

            # Execute drop callback
            self._run_gcode_callback(getattr(self.toolchanger, "_on_tool_drop_gcode", "PAUSE"))

    def query_tool_present(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> typing.Optional[bool]:
        """Unified sensor resolution:
        1. Checks tool-specific sensor (if defined on tool).
        2. Checks toolchanger carriage sensor (if defined).
        3. Returns None if no sensor is configured.
        """
        if tool is None:
            tool = self.toolchanger.selected_tool
            if tool in self.toolchanger.INVALID_TOOLS:
                tool = None

        if tool is not None and getattr(tool, "tool_present_sensor", None) is not None:
            return tool.tool_present_sensor.is_triggered()

        if self.carriage_sensor is not None:
            return self.carriage_sensor.is_triggered()

        return None

    def has_sensor(self, tool: typing.Optional["ktc_tool.KtcTool"] = None) -> bool:
        """Returns True if any physical sensor is available for this toolchanger or tool."""
        return self.query_tool_present(tool) is not None

    def verify_tool_pickup(self, tool: "ktc_tool.KtcTool"):
        """Called after tool_select_gcode to verify tool is physically mounted."""
        if not self.enabled or not getattr(self.toolchanger, "verify_tool_pickup", True):
            return

        is_present = self.query_tool_present(tool)
        if is_present is False:
            msg = (
                f"KTC SAFETY ERROR: Pickup verification failed for tool '{tool.name}' "
                f"on toolchanger '{self.toolchanger.name}'. Switch indicates tool is not attached."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            tool.state = tool.StateType.ERROR
            self._run_gcode_callback(getattr(self.toolchanger, "_on_tool_change_error_gcode", "PAUSE"))
            raise self.printer.command_error(msg)

    def verify_tool_dropoff(self, tool: "ktc_tool.KtcTool"):
        """Called after tool_deselect_gcode to verify tool is physically detached."""
        if not self.enabled or not getattr(self.toolchanger, "verify_tool_dropoff", True):
            return

        is_present = self.query_tool_present(tool)
        if is_present is True:
            msg = (
                f"KTC SAFETY ERROR: Dropoff verification failed for tool '{tool.name}' "
                f"on toolchanger '{self.toolchanger.name}'. Switch indicates tool is still attached."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            tool.state = tool.StateType.ERROR
            self._run_gcode_callback(getattr(self.toolchanger, "_on_tool_change_error_gcode", "PAUSE"))
            raise self.printer.command_error(msg)

    def check_reboot_state(self):
        """Called during _handle_ready. If a tool is physically sensed on reboot, enter ERROR state."""
        if not self.enabled or not getattr(self.toolchanger, "prevent_toolchange_on_reboot_attached", True):
            return

        is_present = self.query_tool_present()
        if is_present is True:
            msg = (
                f"KTC SAFETY WARNING: Tool physically detected on reboot on '{self.toolchanger.name}'! "
                "Toolchanger locked in ERROR state to prevent unexpected tool changes. "
                "Run KTC_SAFETY_UNLOCK to proceed."
            )
            if self.toolchanger.log:
                self.toolchanger.log.always(msg)
            self.toolchanger.state = self.toolchanger.StateType.ERROR
            if (
                self.toolchanger.selected_tool
                and self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS
            ):
                self.toolchanger.selected_tool.state = self.toolchanger.StateType.ERROR

            self._run_gcode_callback(getattr(self.toolchanger, "_on_reboot_tool_attached_gcode", ""))

    def unlock(self):
        """Clears ERROR state and synchronizes tool state based on sensor query or prior state."""
        is_present = self.query_tool_present()

        if is_present is True:
            # Physical sensor confirms tool is attached on carriage
            # If selected_tool is unknown, try to restore from persistent storage
            if self.toolchanger.selected_tool in self.toolchanger.INVALID_TOOLS:
                persisted_name = str.lower(
                    self.toolchanger.persistent_state.get(
                        "selected_tool", self.toolchanger.TOOL_UNKNOWN.name
                    )
                )
                if persisted_name in self.toolchanger.tools:
                    self.toolchanger.selected_tool = self.toolchanger.tools[persisted_name]

            if self.toolchanger.selected_tool not in self.toolchanger.INVALID_TOOLS:
                self.toolchanger.selected_tool.state = self.toolchanger.StateType.ENGAGED
                self.toolchanger.state = self.toolchanger.StateType.ENGAGED
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
            # Sensor confirms no tool attached, or no sensor is configured (assume in dock)
            self.toolchanger.selected_tool = self.toolchanger.TOOL_NONE
            self.toolchanger.state = self.toolchanger.StateType.READY
            msg = (
                f"KTC SAFETY: Unlocked '{self.toolchanger.name}'. "
                "Carriage empty (TOOL_NONE, READY). Ready for tool selection."
            )

        # Clear error on top ktc object if it was in error
        if self.toolchanger._ktc and self.toolchanger._ktc.state == self.toolchanger.StateType.ERROR:
            self.toolchanger._ktc.state = self.toolchanger.state

        if self.toolchanger.log:
            self.toolchanger.log.always(msg)
        else:
            self.printer.lookup_object("gcode").respond_info(msg)

    def _run_gcode_callback(self, gcode_str: str):
        if not gcode_str or not gcode_str.strip():
            return
        try:
            gcode_macro: "klippy_gcode_macro.PrinterGCodeMacro" = self.printer.lookup_object("gcode_macro")
            template = gcode_macro.load_template(self.config, "", gcode_str)
            context = template.create_template_context()
            context["myself"] = self.toolchanger.get_status()
            if self.toolchanger._ktc is not None:
                context["ktc"] = self.toolchanger._ktc.get_status()
            context["STATE_TYPE"] = self.toolchanger.StateType
            template.run_gcode_from_command(context)
        except Exception as e:
            if self.toolchanger.log:
                self.toolchanger.log.always(
                    f"KTC SAFETY: Error running safety callback: {e}"
                )
