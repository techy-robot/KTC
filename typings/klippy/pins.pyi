# Type annotations stub for Klippy interface
# This file may be distributed under the terms of the GNU GPLv3 license.

from typing import Any, Dict, Type

class error(Exception): ...

class PrinterPins:
    error: Type[error]
    def __init__(self, printer: Any) -> None: ...
    def setup_pin(self, pin_type: str, pin_name: str) -> Any: ...
    def register_chip(self, chip_name: str, chip: Any) -> None: ...
    def parse_pin(
        self,
        pin_desc: str,
        can_invert: bool = ...,
        can_pullup: bool = ...,
    ) -> Dict[str, Any]: ...
