"""newsdataapi — official Python SDK for the NewsData.io REST API."""

from .client import NewsDataApiClient
from .csv_export import save_to_csv
from .exceptions import (
    NewsdataAPIError,
    NewsdataAuthError,
    NewsdataException,
    NewsdataNetworkError,
    NewsdataRateLimitError,
    NewsdataServerError,
    NewsdataValidationError,
    NewsdataWebSocketAuthError,
    NewsdataWebSocketError,
)
from .newsdata_websocket import NewsDataApiWebSocket

__version__ = "0.2.1"

__all__ = [
    "NewsDataApiClient",
    "NewsDataApiWebSocket",
    "NewsdataAPIError",
    "NewsdataAuthError",
    "NewsdataException",
    "NewsdataNetworkError",
    "NewsdataRateLimitError",
    "NewsdataServerError",
    "NewsdataValidationError",
    "NewsdataWebSocketAuthError",
    "NewsdataWebSocketError",
    "__version__",
    "save_to_csv",
]
