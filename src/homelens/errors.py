"""Domain-specific exceptions with user-facing messages."""


class HomeLensError(Exception):
    """Base exception for expected HomeLens failures."""


class DataSchemaError(HomeLensError):
    """Raised when a source no longer contains the required fields."""


class DataUnavailableError(HomeLensError):
    """Raised when a required generated dataset is not available."""


class MissingCredentialError(HomeLensError):
    """Raised only when an optional integration is explicitly called without a key."""
