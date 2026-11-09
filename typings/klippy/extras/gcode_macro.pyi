# Type annotations stub for Klippy interface
# This file may be distributed under the terms of the GNU GPLv3 license.

from typing import Any, Dict, Optional

class GCodeMacro:
    def __init__(self, printer: Any, name: str) -> None: ...
    def run_gcode_from_command(
        self,
        context: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

class TemplateWrapper:
    def __init__(self, printer: Any, text: str) -> None: ...
    def create_template_context(self) -> Dict[str, Any]: ...
    def render(self, context: Optional[Dict[str, Any]] = ...) -> str: ...

class PrinterGCodeMacro:
    def __init__(self, printer: Any = ...) -> None: ...
    def load_template(
        self,
        config: Any,
        option: str,
        default: Optional[str] = ...,
    ) -> TemplateWrapper: ...
