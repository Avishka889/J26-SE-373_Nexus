"""How contract vocabulary becomes TypeScript vocabulary. Deterministic."""

import re

_NON_WORD = re.compile(r"[^A-Za-z0-9]+")


def pascal(text: str) -> str:
    parts = [part for part in _NON_WORD.split(text) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def camel(text: str) -> str:
    name = pascal(text)
    return name[:1].lower() + name[1:] if name else name


def ts_type(field_type: str, item_ref: str = "") -> str:
    mapping = {
        "string": "string",
        "number": "number",
        "boolean": "boolean",
        "date": "string",
        "id": "string",
        "object": (item_ref and pascal(item_ref)) or "Record<string, unknown>",
        "array": f"{pascal(item_ref)}[]" if item_ref else "unknown[]",
    }
    return mapping.get(field_type, "string")


def client_method_name(endpoint_id: str) -> str:
    """post-orders -> postOrders. From the id, so it survives regeneration."""
    return camel(endpoint_id)


def express_path(path: str) -> str:
    """/orders/{id} -> /orders/:id."""
    return re.sub(r"\{([^}]+)\}", r":\1", path)


def path_params(path: str) -> list[str]:
    return re.findall(r"\{([^}]+)\}", path)
