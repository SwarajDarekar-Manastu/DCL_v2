"""Read-only Microsoft Graph client (file 02 §1: the app never calls write endpoints).

The client has a GET method and nothing else, so no code path can modify OneDrive. It takes
relative paths (``/drives/{d}/items/{i}``) or the absolute ``@odata.nextLink`` /
``@odata.deltaLink`` URLs Graph returns, which must stay on the Graph host.
"""

from collections.abc import Callable, Mapping
from types import TracebackType
from urllib.parse import urlsplit

import httpx

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"


class GraphClient:
    def __init__(
        self,
        access_token: Callable[[], str],
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._access_token = access_token
        self._http = httpx.Client(base_url=GRAPH_BASE_URL, transport=transport, timeout=timeout_s)

    def get(self, path_or_url: str, params: Mapping[str, str] | None = None) -> httpx.Response:
        """One GET with a fresh silent token. Status handling is the caller's decision."""
        if path_or_url.startswith("https://"):
            if urlsplit(path_or_url).hostname != GRAPH_HOST:
                raise ValueError("refusing to send the Graph token to a host other than graph.microsoft.com")
        elif not path_or_url.startswith("/"):
            raise ValueError("Graph paths start with '/'")
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        return self._http.get(path_or_url, params=params, headers=headers)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
