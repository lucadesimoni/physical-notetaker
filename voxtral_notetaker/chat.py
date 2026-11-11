# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""Helpers for OpenAI-compatible chat completion responses"""

from typing import Any


def message_text(response_json: dict) -> str:
    """
    The answer text of a chat completion. Reasoning models (e.g. Mistral
    Large 4) return a list of parts, with their thinking before the answer:
    only the text parts are the answer.
    """
    content: Any = response_json['choices'][0]['message']['content']
    if isinstance(content, list):
        return ''.join(part.get('text', '') for part in content
                       if isinstance(part, dict) and part.get('type') == 'text')
    return content or ''
