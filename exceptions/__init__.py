class BotError(Exception):
    """Base bot exception."""

class PermissionDenied(BotError):
    """Raised when user lacks proper role."""

class RconError(BotError):
    """Raised when RCON fails."""
