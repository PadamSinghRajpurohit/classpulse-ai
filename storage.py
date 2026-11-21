"""Compatibility shim; the app uses the uniquely named classpulse_storage module."""
from __future__ import annotations

import classpulse_storage as _backend

globals().update({name: getattr(_backend, name) for name in dir(_backend) if not name.startswith("__")})

