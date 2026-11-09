# Type annotations stub for Klippy interface
# This file may be distributed under the terms of the GNU GPLv3 license.

from typing import Any, Callable, Dict, Optional, Type

class CommandError(Exception): ...

class GCodeCommand:
    def __init__(
        self,
        gcode: Any,
        command: str,
        params: Optional[Dict[str, str]] = ...,
    ) -> None: ...
    def get_command(self) -> str: ...
    def get_commandline(self) -> str: ...
    def get_command_parameters(self) -> Dict[str, str]: ...
    def get(
        self,
        key: str,
        default: Any = ...,
        parser: Optional[Callable[[str], Any]] = ...,
    ) -> Any: ...
    def get_int(
        self,
        key: str,
        default: Any = ...,
        minval: Optional[int] = ...,
        maxval: Optional[int] = ...,
    ) -> int: ...
    def get_float(
        self,
        key: str,
        default: Any = ...,
        minval: Optional[float] = ...,
        maxval: Optional[float] = ...,
        above: Optional[float] = ...,
        below: Optional[float] = ...,
    ) -> float: ...
    def respond_info(self, msg: str) -> None: ...
    def error(self, msg: str) -> CommandError: ...

class GCodeDispatch:
    error: Type[CommandError]
    def __init__(self, printer: Any) -> None: ...
    def register_command(
        self,
        cmd: str,
        func: Callable[[GCodeCommand], None],
        when_not_ready: bool = ...,
        desc: Optional[str] = ...,
    ) -> None: ...
    def register_mux_command(
        self,
        cmd: str,
        key: str,
        value: str,
        func: Callable[[GCodeCommand], None],
        desc: Optional[str] = ...,
    ) -> None: ...
    def run_script(self, script: str) -> None: ...
    def run_script_from_command(self, script: str) -> None: ...
    def respond_info(self, msg: str) -> None: ...
    def respond_raw(self, msg: str) -> None: ...
