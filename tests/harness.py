# KTC Test Harness and Mock Environment
# Simulated Klipper environment for KTC unit and integration testing
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import os
import shutil
import sys
import tempfile
import types
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
import unittest


# ---------------------------------------------------------------------------
# Klipper core mock classes for testing without Klipper source code
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised on config parsing or validation errors."""
    pass


class ConfigWrapper:
    """Mock ConfigWrapper providing typed configuration getters."""

    error = ConfigError

    def __init__(
        self,
        printer: Any,
        name: str,
        section_dict: Optional[Dict[str, Any]] = None,
        file_config: Optional[Any] = None,
    ) -> None:
        self._printer = printer
        self._name = name
        self._section = dict(section_dict or {})
        self._file_config = file_config

    def get_name(self) -> str:
        return self._name

    def get_printer(self) -> Any:
        return self._printer

    def get(self, option: str, default: Any = ...) -> Any:
        if option in self._section:
            return self._section[option]
        if default is not ...:
            return default
        raise self.error(f"Option '{option}' in section '{self._name}' must be specified")

    def getboolean(self, option: str, default: Any = ...) -> Any:
        if option not in self._section:
            if default is not ...:
                return default
            raise self.error(f"Option '{option}' in section '{self._name}' must be specified")
        v = self._section[option]
        if isinstance(v, bool):
            return v
        val = str(v).lower().strip()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        raise self.error(f"Option '{option}' in section '{self._name}' must be boolean, got '{v}'")

    def getint(
        self,
        option: str,
        default: Any = ...,
        minval: Optional[int] = None,
        maxval: Optional[int] = None,
    ) -> Any:
        if option not in self._section:
            if default is not ...:
                return default
            raise self.error(f"Option '{option}' in section '{self._name}' must be specified")
        v = self._section[option]
        try:
            res = int(v)
        except Exception:
            raise self.error(f"Option '{option}' in section '{self._name}' must be int, got '{v}'")
        if minval is not None and res < minval:
            raise self.error(f"Option '{option}' must be >= {minval}")
        if maxval is not None and res > maxval:
            raise self.error(f"Option '{option}' must be <= {maxval}")
        return res

    def getfloat(
        self,
        option: str,
        default: Any = ...,
        minval: Optional[float] = None,
        maxval: Optional[float] = None,
        above: Optional[float] = None,
        below: Optional[float] = None,
    ) -> Any:
        if option not in self._section:
            if default is not ...:
                return default
            raise self.error(f"Option '{option}' in section '{self._name}' must be specified")
        v = self._section[option]
        try:
            res = float(v)
        except Exception:
            raise self.error(f"Option '{option}' in section '{self._name}' must be float, got '{v}'")
        if minval is not None and res < minval:
            raise self.error(f"Option '{option}' must be >= {minval}")
        if maxval is not None and res > maxval:
            raise self.error(f"Option '{option}' must be <= {maxval}")
        if above is not None and res <= above:
            raise self.error(f"Option '{option}' must be > {above}")
        if below is not None and res >= below:
            raise self.error(f"Option '{option}' must be < {below}")
        return res

    def getchoice(self, option: str, choices: Any, default: Any = ...) -> Any:
        if option not in self._section:
            if default is not ...:
                return default
            raise self.error(f"Option '{option}' in section '{self._name}' must be specified")
        val = self._section[option]
        if isinstance(choices, dict):
            if val in choices:
                return choices[val]
            raise self.error(f"Choice '{val}' not valid for '{option}'")
        elif val in choices:
            return val
        raise self.error(f"Choice '{val}' not valid for '{option}'")

    def getsection(self, section: str) -> ConfigWrapper:
        if self._file_config and self._file_config.has_section(section):
            return TestConfigWrapper(self._printer, section, self._file_config.get_section(section), self._file_config)
        return TestConfigWrapper(self._printer, section, {}, self._file_config)

    def has_section(self, section: str) -> bool:
        if self._file_config:
            return self._file_config.has_section(section)
        return section == self._name

    def get_prefix_sections(self, prefix: str) -> List[TestConfigWrapper]:
        if self._file_config:
            return [
                TestConfigWrapper(self._printer, s, self._file_config.get_section(s), self._file_config)
                for s in self._file_config.get_prefix_sections(prefix)
            ]
        return []

    def get_prefix_options(self, prefix: str) -> List[str]:
        return [opt for opt in self._section if opt.startswith(prefix)]


class MockConfigFile:
    """Simulates Klipper's internal raw config file."""

    def __init__(self, sections: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.sections: Dict[str, Dict[str, Any]] = sections or {}

    def has_section(self, section: str) -> bool:
        return section in self.sections

    def get_section(self, section: str) -> Dict[str, Any]:
        return self.sections.get(section, {})

    def get_prefix_sections(self, prefix: str) -> List[str]:
        return [s for s in self.sections if s.startswith(prefix)]


class TestConfigWrapper(ConfigWrapper):
    """ConfigWrapper for test scenarios with section lookups."""
    pass


class CommandError(Exception):
    """Raised when a GCode command execution encounters an error."""
    pass


class GCodeCommand:
    """Mock GCodeCommand representing an executed command with arguments."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if len(args) == 3:
            if isinstance(args[0], str):
                self._command = args[0]
                self._params = dict(args[1] or {})
                self._gcode = args[2]
            else:
                self._gcode = args[0]
                self._command = args[1]
                self._params = dict(args[2] or {})
        elif len(args) == 2:
            if isinstance(args[0], str):
                self._command = args[0]
                self._params = dict(args[1] or {})
                self._gcode = None
            else:
                self._gcode = args[0]
                self._command = args[1]
                self._params = {}
        elif len(args) == 1:
            self._command = args[0]
            self._params = {}
            self._gcode = None
        else:
            self._command = kwargs.get("command", "")
            self._params = dict(kwargs.get("params", {}))
            self._gcode = kwargs.get("gcode", None)

    def get_command(self) -> str:
        return self._command

    def get_commandline(self) -> str:
        param_str = " ".join(f"{k}={v}" if v else k for k, v in self._params.items())
        return f"{self._command} {param_str}".strip()

    def get_command_parameters(self) -> Dict[str, str]:
        return dict(self._params)

    def get(self, key: str, default: Any = ..., parser: Optional[Callable[[str], Any]] = None) -> Any:
        if key in self._params:
            val = self._params[key]
            return parser(val) if parser else val
        if default is not ...:
            return default
        raise self.error(f"Missing parameter '{key}' in command '{self._command}'")

    def get_int(
        self,
        key: str,
        default: Any = ...,
        minval: Optional[int] = None,
        maxval: Optional[int] = None,
    ) -> Any:
        if key not in self._params:
            if default is not ...:
                return default
            raise self.error(f"Missing parameter '{key}' in command '{self._command}'")
        val = self._params[key]
        try:
            res = int(val)
        except Exception:
            raise self.error(f"Invalid integer for '{key}': {val}")
        if minval is not None and res < minval:
            raise self.error(f"Parameter '{key}' must be >= {minval}")
        if maxval is not None and res > maxval:
            raise self.error(f"Parameter '{key}' must be <= {maxval}")
        return res

    def get_float(
        self,
        key: str,
        default: Any = ...,
        minval: Optional[float] = None,
        maxval: Optional[float] = None,
        above: Optional[float] = None,
        below: Optional[float] = None,
    ) -> Any:
        if key not in self._params:
            if default is not ...:
                return default
            raise self.error(f"Missing parameter '{key}' in command '{self._command}'")
        val = self._params[key]
        try:
            res = float(val)
        except Exception:
            raise self.error(f"Invalid float for '{key}': {val}")
        if minval is not None and res < minval:
            raise self.error(f"Parameter '{key}' must be >= {minval}")
        if maxval is not None and res > maxval:
            raise self.error(f"Parameter '{key}' must be <= {maxval}")
        if above is not None and res <= above:
            raise self.error(f"Parameter '{key}' must be > {above}")
        if below is not None and res >= below:
            raise self.error(f"Parameter '{key}' must be < {below}")
        return res

    def respond_info(self, msg: str) -> None:
        if self._gcode:
            self._gcode.respond_info(msg)

    def error(self, msg: str) -> CommandError:
        return CommandError(msg)


class GCodeDispatch:
    """Mock GCode Dispatcher supporting command and mux registration and execution."""

    error = CommandError

    def __init__(self, printer: Any) -> None:
        self.printer = printer
        self.commands: Dict[str, Callable[[GCodeCommand], None]] = {}
        self.mux_commands: Dict[str, Dict[str, Dict[str, Callable[[GCodeCommand], None]]]] = {}
        self.responses: List[str] = []

    def register_command(
        self,
        cmd: str,
        func: Callable[[GCodeCommand], None],
        when_not_ready: bool = False,
        desc: Optional[str] = None,
    ) -> None:
        self.commands[cmd.upper()] = func

    def register_mux_command(
        self,
        cmd: str,
        key: str,
        value: str,
        func: Callable[[GCodeCommand], None],
        desc: Optional[str] = None,
    ) -> None:
        cmd_upper = cmd.upper()
        if cmd_upper not in self.mux_commands:
            self.mux_commands[cmd_upper] = {}
        if key.upper() not in self.mux_commands[cmd_upper]:
            self.mux_commands[cmd_upper][key.upper()] = {}
        self.mux_commands[cmd_upper][key.upper()][value.upper()] = func

    def run_script(self, script: str) -> None:
        for raw_line in script.strip().split("\n"):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            cmd_name = parts[0].upper()
            params: Dict[str, str] = {}
            for p in parts[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k.upper()] = v
                else:
                    params[p.upper()] = ""
            gcmd = GCodeCommand(self, cmd_name, params)
            if cmd_name in self.commands:
                self.commands[cmd_name](gcmd)
            elif cmd_name in self.mux_commands:
                matched = False
                for mux_key, values in self.mux_commands[cmd_name].items():
                    if mux_key in params:
                        val = params[mux_key].upper()
                        if val in values:
                            values[val](gcmd)
                            matched = True
                            break
                if not matched:
                    pass

    def run_script_from_command(self, script: str) -> None:
        self.run_script(script)

    def respond_info(self, msg: str) -> None:
        self.responses.append(msg)

    def respond_raw(self, msg: str) -> None:
        self.responses.append(msg)


NOW: float = 0.0
NEVER: float = 1e9


class TimerHandle:
    def __init__(self, callback: Callable[[float], Optional[float]], waketime: float) -> None:
        self._callback = callback
        self.waketime = waketime
        self._active = True


class Reactor:
    """Mock Reactor supporting virtual time progression and timers."""

    NOW = NOW
    NEVER = NEVER

    def __init__(self) -> None:
        self._time = 100.0
        self._timers: List[TimerHandle] = []
        self._callbacks: List[Callable[[float], None]] = []

    def monotonic(self) -> float:
        return self._time

    def get_monotonic(self) -> float:
        return self._time

    def advance_time(self, seconds: float) -> None:
        target_time = self._time + seconds
        while True:
            active_timers = [t for t in self._timers if t._active and t.waketime <= target_time]
            if not active_timers:
                break
            active_timers.sort(key=lambda t: t.waketime)
            earliest = active_timers[0]
            self._time = earliest.waketime
            next_wake = earliest._callback(self._time)
            if next_wake is not None and next_wake != NEVER and earliest._active:
                earliest.waketime = next_wake
            else:
                earliest._active = False
                if earliest in self._timers:
                    self._timers.remove(earliest)
        self._time = target_time
        for cb in list(self._callbacks):
            cb(self._time)
        self._callbacks.clear()

    def register_timer(
        self,
        callback: Callable[[float], Optional[float]],
        waketime: float = 0.0,
    ) -> TimerHandle:
        handle = TimerHandle(callback, waketime if waketime > 0 else self._time)
        self._timers.append(handle)
        return handle

    def unregister_timer(self, handle: TimerHandle) -> None:
        handle._active = False
        handle.waketime = NEVER
        if handle in self._timers:
            self._timers.remove(handle)

    def update_timer(self, handle: TimerHandle, waketime: float) -> None:
        handle.waketime = waketime

    def register_callback(self, callback: Callable[[float], None]) -> None:
        self._callbacks.append(callback)

    def pause(self, waketime: float) -> None:
        if waketime > self._time:
            self.advance_time(waketime - self._time)


class PinError(Exception):
    pass


class MockSwitchSensorDevice:
    """Mock physical hardware switch/sensor for safety and interlock testing."""

    def __init__(self, pin_name: str, active_state: bool = True) -> None:
        self.pin_name = pin_name
        self.is_triggered: bool = False
        self.callback: Optional[Callable[[float, bool], None]] = None

    def trigger(self, eventtime: float = 0.0) -> None:
        self.is_triggered = True
        if self.callback:
            self.callback(eventtime, True)

    def release(self, eventtime: float = 0.0) -> None:
        self.is_triggered = False
        if self.callback:
            self.callback(eventtime, False)


class PrinterPins:
    """Mock PrinterPins subsystem."""

    error = PinError

    def __init__(self, printer: Any) -> None:
        self.printer = printer
        self.pins: Dict[str, Any] = {}

    def parse_pin(self, pin_desc: str, can_invert: bool = False, can_pullup: bool = False) -> Dict[str, Any]:
        invert = pin_desc.startswith("!")
        name = pin_desc.lstrip("!^~")
        return {"chip": None, "pin": name, "invert": invert}

    def setup_pin(self, pin_type: str, pin_name: str) -> Any:
        sensor = MockSwitchSensorDevice(pin_name)
        if hasattr(self.printer, "sensors"):
            self.printer.sensors[pin_name] = sensor
        return sensor

    def register_chip(self, chip_name: str, chip: Any) -> None:
        pass


class Heater:
    """Mock Heater representation."""

    def __init__(self, printer: Any, name: str) -> None:
        self.printer = printer
        self.name = name
        self.target_temp: float = 0.0
        self.current_temp: float = 20.0
        self.smoothed_temp: float = 20.0

    def get_temp(self, eventtime: float = 0.0) -> Tuple[float, float]:
        return (self.current_temp, self.target_temp)

    def set_temp(self, degrees: float) -> None:
        self.target_temp = degrees
        self.current_temp = degrees

    def alter_target(self, degrees: float) -> None:
        self.target_temp = degrees

    def check_busy(self, eventtime: float = 0.0) -> bool:
        return abs(self.current_temp - self.target_temp) > 1.0


class PrinterHeaters:
    """Mock PrinterHeaters subsystem."""

    def __init__(self, printer: Any) -> None:
        self.printer = printer
        self.heaters: Dict[str, Heater] = {}

    def add_heater(self, name: str) -> Heater:
        h = Heater(self.printer, name)
        self.heaters[name] = h
        return h

    def lookup_heater(self, name: str) -> Heater:
        if name not in self.heaters:
            self.heaters[name] = Heater(self.printer, name)
        return self.heaters[name]

    def get_all_heaters(self) -> List[str]:
        return list(self.heaters.keys())


class GCodeMacro:
    """Mock GCodeMacro object."""

    def __init__(self, printer: Any, name: str) -> None:
        self.printer = printer
        self.name = name

    def run_gcode_from_command(self, context: Optional[Dict[str, Any]] = None) -> None:
        pass


class PrinterGCodeMacro:
    """Mock PrinterGCodeMacro subsystem."""

    def __init__(self, printer: Any = None) -> None:
        self.printer = printer

    def load_template(self, config: Any, option: str, default: Optional[str] = None) -> Any:
        class TemplateWrapper:
            def __init__(self, printer: Any, text: str) -> None:
                self.printer = printer
                self.text = text
            def create_template_context(self) -> Dict[str, Any]:
                return {}
            def render(self, context: Optional[Dict[str, Any]] = None) -> str:
                res = self.text
                if context:
                    for k, v in context.items():
                        if isinstance(v, dict):
                            for sub_k, sub_v in v.items():
                                res = res.replace(f"{{{k}.{sub_k}}}", str(sub_v))
                                res = res.replace(f"{{ {k}.{sub_k} }}", str(sub_v))
                                res = res.replace(f"{{{{{k}.{sub_k}}}}}", str(sub_v))
                                res = res.replace(f"{{{{ {k}.{sub_k} }}}}", str(sub_v))
                        elif hasattr(v, "name"):
                            res = res.replace(f"{{{k}.name}}", str(v.name))
                            res = res.replace(f"{{ {k}.name }}", str(v.name))
                        res = res.replace(f"{{{k}}}", str(v))
                        res = res.replace(f"{{{{{k}}}}}", str(v))
                return res
            def run_gcode_from_command(self, context: Optional[Dict[str, Any]] = None) -> None:
                rendered = self.render(context)
                if rendered and self.printer and hasattr(self.printer, "gcode"):
                    self.printer.gcode.run_script(rendered)
        raw = config.get(option, default or "")
        return TemplateWrapper(self.printer, raw)


class PrinterFanGeneric:
    """Mock fan_generic subsystem."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.speed: float = 0.0
        self.fan = self

    def get_status(self, eventtime: float = 0.0) -> Dict[str, Any]:
        return {"speed": self.speed}

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def set_speed_from_command(self, speed: float) -> None:
        self.speed = speed


# ---------------------------------------------------------------------------
# Dynamic module injection into sys.modules so KTC imports succeed cleanly
# ---------------------------------------------------------------------------

def install_klippy_mocks() -> None:
    """Inject mock klippy modules into sys.modules to satisfy runtime imports."""
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    klippy_dir = os.path.join(repo_dir, "klippy")
    extras_dir = os.path.join(klippy_dir, "extras")

    if "klippy" not in sys.modules:
        k_mod = types.ModuleType("klippy")
        k_mod.__path__ = [klippy_dir]
        sys.modules["klippy"] = k_mod
    else:
        k_mod = sys.modules["klippy"]
        if not hasattr(k_mod, "__path__"):
            k_mod.__path__ = [klippy_dir]

    # klippy.pins
    p_mod = types.ModuleType("klippy.pins")
    p_mod.PrinterPins = PrinterPins
    p_mod.error = PinError
    sys.modules["klippy.pins"] = p_mod
    k_mod.pins = p_mod

    # klippy.configfile
    cf_mod = types.ModuleType("klippy.configfile")
    cf_mod.ConfigWrapper = ConfigWrapper
    cf_mod.error = ConfigError
    sys.modules["klippy.configfile"] = cf_mod
    k_mod.configfile = cf_mod

    # klippy.gcode
    gc_mod = types.ModuleType("klippy.gcode")
    gc_mod.GCodeCommand = GCodeCommand
    gc_mod.GCodeDispatch = GCodeDispatch
    gc_mod.CommandError = CommandError
    sys.modules["klippy.gcode"] = gc_mod
    k_mod.gcode = gc_mod

    # klippy.reactor
    r_mod = types.ModuleType("klippy.reactor")
    r_mod.Reactor = Reactor
    r_mod.TimerHandle = TimerHandle
    r_mod.NOW = NOW
    r_mod.NEVER = NEVER
    sys.modules["klippy.reactor"] = r_mod
    k_mod.reactor = r_mod

    # klippy.klippy
    kl_mod = types.ModuleType("klippy.klippy")
    kl_mod.Printer = TestPrinter
    sys.modules["klippy.klippy"] = kl_mod
    k_mod.klippy = kl_mod

    # klippy.extras
    if "klippy.extras" not in sys.modules:
        ke_mod = types.ModuleType("klippy.extras")
        ke_mod.__path__ = [extras_dir]
        sys.modules["klippy.extras"] = ke_mod
        k_mod.extras = ke_mod
    else:
        ke_mod = sys.modules["klippy.extras"]
        if not hasattr(ke_mod, "__path__"):
            ke_mod.__path__ = [extras_dir]

    h_mod = types.ModuleType("klippy.extras.heaters")
    h_mod.PrinterHeaters = PrinterHeaters
    h_mod.Heater = Heater
    sys.modules["klippy.extras.heaters"] = h_mod
    ke_mod.heaters = h_mod

    gm_mod = types.ModuleType("klippy.extras.gcode_macro")
    gm_mod.PrinterGCodeMacro = PrinterGCodeMacro
    gm_mod.GCodeMacro = GCodeMacro
    sys.modules["klippy.extras.gcode_macro"] = gm_mod
    ke_mod.gcode_macro = gm_mod

    fg_mod = types.ModuleType("klippy.extras.fan_generic")
    fg_mod.PrinterFanGeneric = PrinterFanGeneric
    sys.modules["klippy.extras.fan_generic"] = fg_mod
    ke_mod.fan_generic = fg_mod


# ---------------------------------------------------------------------------
# Test Printer and Harness classes
# ---------------------------------------------------------------------------

class TestPrinter:
    """Simulated Klipper Printer instance for testing."""

    command_error = CommandError

    def __init__(self, temp_dir: str) -> None:
        self.temp_dir = temp_dir
        self.log_file = os.path.join(temp_dir, "ktc_test.log")
        self.start_args = {"log_file": self.log_file}

        self.reactor = Reactor()
        self.objects: Dict[str, Any] = {}
        self.event_handlers: Dict[str, List[Callable[..., Any]]] = {}

        # Standard subsystems
        self.gcode = GCodeDispatch(self)
        self.pins = PrinterPins(self)
        self.heaters = PrinterHeaters(self)
        self.gcode_macro = PrinterGCodeMacro()
        self.gcode_macro.printer = self

        self.objects["gcode"] = self.gcode
        self.objects["pins"] = self.pins
        self.objects["heaters"] = self.heaters
        self.objects["gcode_macro"] = self.gcode_macro

        class MockToolhead:
            def __init__(self) -> None:
                self.homed_axes = "xyz"
                self.position = [0.0, 0.0, 0.0, 0.0]

            def wait_moves(self) -> None:
                pass

            def get_status(self, eventtime: Optional[float] = None) -> Dict[str, Any]:
                return {"homed_axes": self.homed_axes, "position": self.position}

            def get_kinematics(self) -> Any:
                from unittest.mock import MagicMock
                return MagicMock()

        self.objects["toolhead"] = MockToolhead()
        self.sensors: Dict[str, MockSwitchSensorDevice] = {}

    def get_reactor(self) -> Reactor:
        return self.reactor

    def get_start_args(self) -> Dict[str, Any]:
        return dict(self.start_args)

    def register_event_handler(self, event: str, callback: Callable[..., Any]) -> None:
        if event not in self.event_handlers:
            self.event_handlers[event] = []
        self.event_handlers[event].append(callback)

    def send_event(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        results = []
        if event in self.event_handlers:
            for handler in list(self.event_handlers[event]):
                results.append(handler(*args, **kwargs))
        return results

    def add_object(self, name: str, obj: Any) -> None:
        self.objects[name] = obj

    def lookup_object(self, name: str, default: Any = ...) -> Any:
        if name in self.objects:
            return self.objects[name]
        if default is not ...:
            return default
        if name == "ktc_log":
            cfg = TestConfigWrapper(self, "ktc_log", {"logfile_level": "-1"})
            return self.load_object(cfg, "ktc_log")
        raise KeyError(f"Printer object '{name}' not found")

    def lookup_objects(self, prefix: str = "") -> List[Tuple[str, Any]]:
        return [(k, v) for k, v in self.objects.items() if k.startswith(prefix)]

    def load_object(self, config: Any, name: str) -> Any:
        if name in self.objects:
            return self.objects[name]

        if name == "gcode":
            return self.gcode
        elif name == "heaters":
            return self.heaters
        elif name == "pins":
            return self.pins
        elif name == "gcode_macro":
            return self.gcode_macro
        elif name == "ktc_log":
            from klippy.extras.ktc_log import KtcLog
            log_cfg = config
            if not config.has_section("ktc_log"):
                log_cfg = TestConfigWrapper(self, "ktc_log", {"logfile_level": "-1"})
            log_obj = KtcLog(log_cfg)
            self.objects["ktc_log"] = log_obj
            return log_obj
        elif name == "ktc_persisting":
            from klippy.extras.ktc_persisting import KtcPersisting
            p_obj = KtcPersisting(config)
            self.objects["ktc_persisting"] = p_obj
            return p_obj
        elif name == "gcode_move":
            from unittest.mock import MagicMock
            gmove = MagicMock()
            gmove.get_status.return_value = {"position": [0.0, 0.0, 0.0, 0.0]}
            self.objects["gcode_move"] = gmove
            return gmove
        elif name.startswith("ktc_tool "):
            if not self.file_config.has_section(name):
                return None
            from klippy.extras.ktc_tool import KtcTool
            t_cfg = TestConfigWrapper(self, name, self.file_config.get_section(name), self.file_config)
            tool = KtcTool(t_cfg)
            self.objects[name] = tool
            return tool
        elif name.startswith("fan_generic "):
            fan_name = name.split(" ", 1)[1]
            fan = PrinterFanGeneric(fan_name)
            self.objects[name] = fan
            return fan

        from unittest.mock import MagicMock
        mock_obj = MagicMock()
        self.objects[name] = mock_obj
        return mock_obj


class KtcTestHarness:
    """Comprehensive test harness for setting up KTC test scenarios."""

    def __init__(self, raw_config: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ktc_test_")
        self.printer = TestPrinter(self.temp_dir)
        self.file_config = MockConfigFile(raw_config or {})
        self._setup_default_configs()

    def _setup_default_configs(self) -> None:
        if not self.file_config.has_section("ktc"):
            self.file_config.sections["ktc"] = {
                "default_toolchanger": "toolchanger",
                "propagate_state": "True",
            }
        if not self.file_config.has_section("ktc_log"):
            self.file_config.sections["ktc_log"] = {
                "log_level": "3",
                "logfile_level": "-1",
            }
        if not self.file_config.has_section("ktc_persisting"):
            var_file = os.path.join(self.temp_dir, "ktc_variables.cfg")
            self.file_config.sections["ktc_persisting"] = {
                "filename": var_file,
            }

    def get_config_wrapper(self, section_name: str) -> TestConfigWrapper:
        section = self.file_config.get_section(section_name)
        return TestConfigWrapper(self.printer, section_name, section, self.file_config)

    def load_ktc_stack(
        self,
        num_tools: int = 2,
        has_heaters: bool = True,
        has_fans: bool = False,
    ) -> Any:
        from klippy.extras.ktc import Ktc
        from klippy.extras.ktc_toolchanger import KtcToolchanger
        from klippy.extras.ktc_tool import KtcTool
        from klippy.extras.ktc_heater import KtcHeater
        from klippy.extras.ktc_log import KtcLog
        from klippy.extras.ktc_persisting import KtcPersisting

        log_cfg = self.get_config_wrapper("ktc_log")
        self.printer.load_object(log_cfg, "ktc_log")

        pers_cfg = self.get_config_wrapper("ktc_persisting")
        self.printer.load_object(pers_cfg, "ktc_persisting")

        if not any(s.startswith("ktc_toolchanger") for s in self.file_config.sections):
            self.file_config.sections["ktc_toolchanger toolchanger"] = {
                "init_mode": "MANUAL",
                "init_order": "INDEPENDENT",
            }
            tc_cfg = self.get_config_wrapper("ktc_toolchanger toolchanger")
            tc = KtcToolchanger(tc_cfg)
            self.printer.add_object("ktc_toolchanger toolchanger", tc)

        tools = []
        for i in range(num_tools):
            sec_name = f"ktc_tool {i}"
            if not self.file_config.has_section(sec_name):
                t_dict: Dict[str, Any] = {
                    "tool_number": str(i),
                    "toolchanger": "toolchanger",
                    "tool_select_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=SELECTED",
                    "tool_deselect_gcode": "KTC_SET_STATE TOOL={myself.name} STATE=READY",
                }
                if has_heaters:
                    heater_name = f"extruder{i}" if i > 0 else "extruder"
                    t_dict["heater"] = heater_name
                    self.printer.heaters.add_heater(heater_name)
                    h_cfg = self.get_config_wrapper(f"ktc_heater {heater_name}")
                    h_obj = KtcHeater(h_cfg)
                    self.printer.add_object(f"ktc_heater {heater_name}", h_obj)
                if has_fans:
                    fan_name = f"fan{i}"
                    t_dict["fans"] = fan_name
                    self.printer.load_object(None, f"fan_generic {fan_name}")

                self.file_config.sections[sec_name] = t_dict

            t_cfg = self.get_config_wrapper(sec_name)
            tool = KtcTool(t_cfg)
            self.printer.add_object(sec_name, tool)
            tools.append(tool)

        ktc_cfg = self.get_config_wrapper("ktc")
        ktc = Ktc(ktc_cfg)
        self.printer.add_object("ktc", ktc)

        return ktc

    def connect_and_ready(self) -> None:
        self.printer.send_event("klippy:connect")
        self.printer.send_event("klippy:ready")

    def run_gcode(self, script: str) -> None:
        self.printer.gcode.run_script(script)

    def advance_time(self, seconds: float) -> None:
        self.printer.reactor.advance_time(seconds)

    def cleanup(self) -> None:
        log_obj = self.printer.lookup_object("ktc_log", None)
        if log_obj is not None and getattr(log_obj, "queue_listener", None):
            try:
                log_obj.queue_listener.stop()
            except Exception:
                pass
        import logging
        logger = logging.getLogger("ktc")
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)


class KtcTestCase(unittest.TestCase):
    """Base test case with automated harness lifecycle management."""

    def setUp(self) -> None:
        self.harness = KtcTestHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()


# Install mock modules automatically when harness is imported
install_klippy_mocks()
