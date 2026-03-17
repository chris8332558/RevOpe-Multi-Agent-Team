"""
Shared logger configuration for the RevOps pipeline.

Will provide:
- A pre-configured Rich-based logger for structured console output
- get_logger(name: str) -> logging.Logger  for per-module loggers
- Pipeline-stage log formatting with timestamps and level colours
"""
