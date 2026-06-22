# Minimal type stub for the Calamares-injected `libcalamares` runtime module.
# The Calamares C++ host provides this at module-exec time; it is never on the
# type-checker's path, so without this stub every plugin under
# calamares/modules-src/ reports unresolved imports. Typed Any where the host
# contract is dynamic, to declare the surface without inventing precise types.
from typing import Any

from . import utils as utils

class _GlobalStorage:
    def value(self, key: str) -> Any: ...
    def insert(self, key: str, value: Any) -> None: ...

globalstorage: _GlobalStorage
