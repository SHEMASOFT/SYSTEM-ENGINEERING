"""SE-CONSOLE :: a local-first, read-only console over SYSTEM-ENGINEERING.

Non-goals, enforced structurally rather than by convention:
  * no writes to SYSTEM-ENGINEERING
  * no cache/ledger/state/registry of its own
  * no re-implementation of SE governance

Everything the console shows is either an `se` CLI verdict relayed verbatim
or a transcription of a canonical file.
"""

__all__ = ["se_cli", "se_reader", "read_model", "api", "server"]
__version__ = "0.1.0-poc"
