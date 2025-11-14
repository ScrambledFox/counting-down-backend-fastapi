from typing import Any

from fastapi.routing import APIRoute


class NoAliasAPIRoute(APIRoute):
    def __init__(self, *args: Any, **kwargs: Any):
        # Force disable alias-based serialization so fields use their Python names.
        # FastAPI's decorator injects response_model_by_alias=True explicitly; using
        # setdefault would not override it. We assign unconditionally.
        kwargs["response_model_by_alias"] = False
        super().__init__(*args, **kwargs)
