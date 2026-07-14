"""Connector-specific exceptions."""


class ConnectorError(RuntimeError):
    """A remote source could not be read reliably."""


class ConnectorConfigurationError(ConnectorError):
    """A connector is disabled because required configuration is missing."""


class UnsafeQueryError(ValueError):
    """A structured query contains an unsafe identifier or unsupported operation."""
