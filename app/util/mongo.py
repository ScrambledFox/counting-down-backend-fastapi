from app.models.db import Document


def from_mongo(doc: Document) -> Document:
    """
    Return a shallow copy of `doc` where a MongoDB '_id' field is replaced
    by an 'id' field containing the string representation of the original value.

    Example:
        {"_id": ObjectId("..."), "name": "x"} -> {"id": "507f1f77bcf86cd799439011", "name": "x"}
    """
    out: Document = doc.copy()
    if "_id" in out:
        raw = out.pop("_id")
        # Convert ObjectId (or any other value) to its string form
        out["id"] = str(raw) if raw is not None else None
    return out
