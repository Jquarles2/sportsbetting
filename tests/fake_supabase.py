"""A small in-memory imitation of Supabase's REST API (PostgREST), just faithful enough to test against.

It checks the same things the real service would: the apikey headers, that the table exists, filter
syntax like id=eq.5, on_conflict with ignore/merge duplicates, the 1000-row cap, and empty bodies for
return=minimal. It can't prove we match the real service, but it catches the mistakes we're likely to make.
"""
import json
from urllib.parse import urlparse

import requests

SCHEMAS = {
    "nobet": {"key": ["kind", "name"], "defaults": {}},
    "picks_log": {"key": ["logged_on", "sport", "risk", "game", "market", "pick"], "identity": "id",
                  "defaults": {"result": "pending", "graded_on": None}},
    "cache": {"key": ["key"], "defaults": {}},
}


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.text = "" if body is None else json.dumps(body)
        self.ok = status < 400

    def json(self):
        return json.loads(self.text)


class FakeSupabase:
    def __init__(self, url="https://proj.supabase.co", key="secret-key", tables=("nobet", "picks_log", "cache")):
        self.url, self.key = url, key
        self.rows = {t: [] for t in tables}
        self.next_id = 1
        self.calls = []

    def request(self, method, url, params=None, headers=None, data=None, timeout=None):
        self.calls.append((method, urlparse(url).path.rsplit("/", 1)[-1], dict(params or {})))
        if not url.startswith(self.url + "/rest/v1/"):
            raise requests.ConnectionError("wrong host")
        if (headers or {}).get("apikey") != self.key or headers.get("Authorization") != f"Bearer {self.key}":
            return FakeResponse(401, {"message": "Invalid API key"})
        table = url.rsplit("/", 1)[-1]
        if table not in self.rows:
            return FakeResponse(404, {"code": "PGRST205",
                                      "message": f"Could not find the table 'public.{table}' in the schema cache"})
        params, body = params or {}, json.loads(data) if data else None
        prefer = headers.get("Prefer", "")
        if method == "GET":
            return self._get(table, params)
        if method == "POST":
            return self._post(table, params, body, prefer)
        matches = self._filter(table, params)
        if method == "PATCH":
            for row in matches:
                row.update(body)
            return FakeResponse(204)
        if method == "DELETE":
            self.rows[table] = [r for r in self.rows[table] if r not in matches]
            return FakeResponse(204)
        return FakeResponse(405)

    def _filter(self, table, params):
        rows = self.rows[table]
        for col, cond in params.items():
            if col in ("select", "order", "limit", "offset", "on_conflict"):
                continue
            assert cond.startswith("eq."), f"unsupported filter {col}={cond}"
            rows = [r for r in rows if str(r[col]) == cond[3:]]
        return rows

    def _get(self, table, params):
        rows = list(self._filter(table, params))
        if "order" in params:
            col, direction = params["order"].split(".")
            rows.sort(key=lambda r: r.get(col) if r.get(col) is not None else 0, reverse=direction == "desc")
        start = int(params.get("offset", 0))
        rows = rows[start:start + min(int(params.get("limit", 1000)), 1000)]  # the real service caps pages at 1000
        select = params.get("select", "*")
        if select != "*":
            rows = [{c: r[c] for c in select.split(",")} for r in rows]
        return FakeResponse(200, rows)

    def _post(self, table, params, body, prefer):
        schema = SCHEMAS[table]
        incoming = body if isinstance(body, list) else [body]
        on_conflict = params.get("on_conflict", ",".join(schema["key"])).split(",")
        for new in incoming:
            existing = next((r for r in self.rows[table] if all(r[c] == new.get(c) for c in on_conflict)), None)
            if existing is not None:
                if "ignore-duplicates" in prefer:
                    continue
                if "merge-duplicates" in prefer:
                    existing.update(new)
                    continue
                return FakeResponse(409, {"message": "duplicate key value violates unique constraint"})
            row = {**schema["defaults"], **new}
            if "identity" in schema:
                row[schema["identity"]] = self.next_id
                self.next_id += 1
            self.rows[table].append(row)
        return FakeResponse(201) if "return=minimal" in prefer else FakeResponse(201, incoming)
