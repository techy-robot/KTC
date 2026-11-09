# Type annotations stub for Klippy interface
# This file may be distributed under the terms of the GNU GPLv3 license.

from typing import Any, Dict, List, Optional, Type

class error(Exception): ...

class ConfigWrapper:
    error: Type[error]
    def __init__(
        self,
        printer: Any,
        name: str,
        section_dict: Optional[Dict[str, Any]] = ...,
        file_config: Optional[Any] = ...,
    ) -> None: ...
    def get_name(self) -> str: ...
    def get_printer(self) -> Any: ...
    def get(self, option: str, default: Any = ...) -> Any: ...
    def getboolean(self, option: str, default: Any = ...) -> bool: ...
    def getint(
        self,
        option: str,
        default: Any = ...,
        minval: Optional[int] = ...,
        maxval: Optional[int] = ...,
    ) -> int: ...
    def getfloat(
        self,
        option: str,
        default: Any = ...,
        minval: Optional[float] = ...,
        maxval: Optional[float] = ...,
        above: Optional[float] = ...,
        below: Optional[float] = ...,
    ) -> float: ...
    def getchoice(
        self,
        option: str,
        choices: Any,
        default: Any = ...,
    ) -> Any: ...
    def getsection(self, section: str) -> ConfigWrapper: ...
    def has_section(self, section: str) -> bool: ...
    def get_prefix_sections(self, prefix: str) -> List[ConfigWrapper]: ...
    def get_prefix_options(self, prefix: str) -> List[str]: ...
