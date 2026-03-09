from __future__ import annotations

import json
import re
from typing import Any


def extract_next_initial_state(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return {}
    payload = json.loads(match.group(1))
    return payload.get("props", {}).get("initialState", {})
