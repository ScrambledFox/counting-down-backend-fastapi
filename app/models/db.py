from typing import Any

# Document type alias for MongoDB documents
type Document = dict[str, Any]

type Query = dict[str, str | int | float | bool]
