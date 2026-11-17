"""The few LLM calls the recipes make, through any OpenAI-compatible chat API.

Gemini, OpenAI, Anthropic, Mistral and self-hosted servers such as vLLM all offer one, so
the provider is a setting: the URL of its chat completions endpoint, a model name and an
API key. Calls use the standard library only, so the package installs nothing.
"""

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# There's no default provider or model: they're the user's choice. Some endpoints:
# https://api.openai.com/v1/chat/completions, https://api.anthropic.com/v1/chat/completions,
# https://generativelanguage.googleapis.com/v1beta/openai/chat/completions (Gemini),
# https://api.mistral.ai/v1/chat/completions, or your own server's.
FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class LLM:
    api_key: str
    model: str
    url: str
    timeout: float = 60
    usage: Dict[str, int] = field(default_factory=lambda: {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0})

    def complete(self, prompt: str) -> str:
        """The model's answer to one prompt, at temperature 0, without a code fence."""
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        self.usage["calls"] += 1
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            out = json.load(resp)
        used = out.get("usage") or {}
        self.usage["input_tokens"] += int(used.get("prompt_tokens") or 0)
        self.usage["output_tokens"] += int(used.get("completion_tokens") or 0)
        return FENCE_RE.sub("", out["choices"][0]["message"]["content"].strip()).strip()

    def lines(self, prompt: str, limit: int) -> List[str]:
        """The answer's non-empty lines, without list markers, at most ``limit``."""
        found = []
        for line in self.complete(prompt).splitlines():
            line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"')
            if line and line not in found:
                found.append(line)
        return found[:limit]

    def summary(self) -> str:
        u = self.usage
        return (
            f"{u['calls']} calls to {self.model} ({u['failed']} failed), "
            f"{u['input_tokens']:,} input and {u['output_tokens']:,} output tokens"
        )


def from_settings(api_key: Optional[str], model: str, url: str) -> Optional[LLM]:
    """The LLM a recipe's ``llm_*`` arguments describe, or None without a key."""
    if api_key is None:
        return None
    missing = [arg for arg, value in (("--llm-model", model), ("--llm-url", url)) if not value.strip()]
    if missing:
        raise ValueError(
            f"--llm-api-key also needs {' and '.join(missing)}: your provider's model name and its "
            "OpenAI-compatible chat completions endpoint."
        )
    return LLM(api_key, model.strip(), url.strip())


def proposer(llm: LLM, prompt: Callable[..., str], n: int = 5) -> Callable[..., List[str]]:
    """A function that asks ``llm`` for up to ``n`` names, with the prompt ``prompt(*args)``.
    A failed call counts in ``llm.usage`` and proposes nothing; a run where every call
    fails stops, since its questions would silently miss the LLM's names."""

    def propose(*args) -> List[str]:
        try:
            return llm.lines(prompt(*args, n=n), n)
        except Exception as err:  # noqa: BLE001 - one failed call shouldn't stop the run
            llm.usage["failed"] += 1
            if llm.usage["failed"] >= 5 and llm.usage["failed"] == llm.usage["calls"]:
                raise RuntimeError(f"The LLM calls are failing: {err}") from err
            return []

    return propose
