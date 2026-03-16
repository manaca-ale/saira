#!/usr/bin/env python3
"""Hook chamado pelo Gemini CLI após cada tool use.

Configure em .gemini/settings.json (ou equivalente) do seu projeto:
  {
    "hooks": {
      "post_tool_use": "python3 /path/to/hooks/gemini_hook.py"
    }
  }

O Gemini passa o payload via stdin como JSON.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(os.getenv("HOOK_SERVER_PORT", "7123"))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    # Gemini pode usar keys ligeiramente diferentes
    tool_name = data.get("tool_name") or data.get("name") or "unknown"
    tool_input = data.get("tool_input") or data.get("input") or {}
    # Gemini CLI usa "tool_response"; Claude usa "tool_result"
    tool_result = data.get("tool_response") or data.get("tool_result") or data.get("output") or ""

    payload = json.dumps(
        {
            "agent": "gemini",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_result": str(tool_result)[:500],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            f"http://localhost:{PORT}/hook",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except (urllib.error.URLError, OSError):
        pass


if __name__ == "__main__":
    main()
