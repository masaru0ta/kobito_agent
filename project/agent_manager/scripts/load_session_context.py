#!/usr/bin/env python3
"""
SessionStart hook script for loading agent context files.
Reads mission.md, task.md, chat history summary, output index, and team info
and provides them as additional context for the session.
"""

import json
import sys
from pathlib import Path
import os


def load_session_context():
    """Load context files for session start"""

    # Get the current working directory (should be agent/adam/)
    cwd = Path.cwd()

    # Define files to load (relative to agent/adam/ directory)
    files_to_load = [
        "mission.md",
        "task.md",
        "chat_history/summary.md",
        "output/index.md"
    ]

    content_parts = []

    for file_path in files_to_load:
        full_path = cwd / file_path

        if full_path.exists() and full_path.is_file():
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()

                if file_content:  # Only include non-empty files
                    content_parts.append(f"# File: {file_path}\n\n{file_content}\n")

            except Exception as e:
                print(f"Error reading {file_path}: {e}", file=sys.stderr)

    if content_parts:
        combined_content = "\n".join(content_parts)

        # Return JSON with additional context for the session
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": combined_content
            }
        }

        print(json.dumps(result))
    else:
        # No content found, return empty result
        print("{}")


if __name__ == "__main__":
    load_session_context()