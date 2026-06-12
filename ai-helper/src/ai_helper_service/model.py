from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings


class MissingModelRuntime(RuntimeError):
    pass


def resolve_model_path(model: str) -> str:
    """Resolve supported model locators to a local/Transformers-compatible path."""
    if model.startswith("kaggle://"):
        try:
            import kagglehub
        except ImportError as error:
            raise MissingModelRuntime(
                "Missing Kaggle model dependency. Run: "
                'cd ~/bin/home-services/ai-helper && .venv/bin/python -m pip install -e ".[local,voice,dev]"'
            ) from error

        return kagglehub.model_download(model.removeprefix("kaggle://"))

    expanded = Path(model).expanduser()
    if expanded.exists():
        return str(expanded)

    if model.startswith("/") or model.startswith("~"):
        raise FileNotFoundError(
            f"AI helper model directory not found: {expanded}. "
            "Install the model there, or set AI_HELPER_LOCAL_MODEL to a local model directory, "
            "a model id supported by the local runtime, or a kaggle:// model handle."
        )

    return model


@dataclass
class ModelRunner:
    settings: Settings
    processor: Any | None = None
    model: Any | None = None

    def load(self) -> None:
        if self.processor is not None and self.model is not None:
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as error:
            raise MissingModelRuntime(
                "Missing local model dependencies. Run: "
                'cd ~/bin/home-services/ai-helper && .venv/bin/python -m pip install -e ".[local,voice,dev]"'
            ) from error

        model_path = resolve_model_path(self.settings.local_model)
        print(f"ai-helper: loading model from {model_path}", file=sys.stderr, flush=True)

        self.processor = AutoProcessor.from_pretrained(model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=torch.bfloat16,
            device_map="auto",
        )

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # device_map="auto" generally handles placement. This branch is
            # intentionally observational so CPU fallback still works.
            return

    def generate(self, prompt: str) -> str:
        self.load()
        assert self.processor is not None
        assert self.model is not None
        print("ai-helper: generating response", file=sys.stderr, flush=True)

        messages = [
            {
                "role": "system",
                "content": self.settings.system_prompt,
            },
            {"role": "user", "content": prompt},
        ]

        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=self.settings.enable_thinking,
        )
        inputs = self.processor(text=text, return_tensors="pt").to(self.model.device)
        input_len = inputs["input_ids"].shape[-1]
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=self.settings.max_output_tokens,
        )
        response = self.processor.decode(
            outputs[0][input_len:], skip_special_tokens=False
        )

        parse_response = getattr(self.processor, "parse_response", None)
        if callable(parse_response):
            parsed = parse_response(response)
            if isinstance(parsed, str):
                return parsed.strip()
            if isinstance(parsed, dict):
                return str(parsed.get("response") or parsed.get("answer") or parsed).strip()

        return response.strip()
