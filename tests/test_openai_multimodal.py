#!/usr/bin/env python3
"""Unit tests for OpenAI-path multimodal content conversion.

Reproduces the bug where a user message with an array content (text + image)
was dropped to "" before reaching the Responses API, and verifies text + image
parts now survive as input_text / input_image. No network.

Usage:
    python3 tests/test_openai_multimodal.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.openai import ChatCompletionRequest, Message
from app.services.openai_service import OpenAIService

DATA_IMG = "data:image/png;base64,iVBORw0KGgoAAAANS"


def run():
    svc = OpenAIService(dynamodb_client=None)
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("── plain string user content unchanged ──")
    req = ChatCompletionRequest(model="openai-gpt-5-5", messages=[Message(role="user", content="hello")])
    items = svc._convert_to_responses_input(req)["input"]
    check("string content stays a string", items[0]["content"] == "hello")

    print("── multimodal user content survives (text + image) ──")
    req = ChatCompletionRequest(model="openai-gpt-5-5", messages=[
        Message(role="user", content=[
            {"type": "text", "text": "what is in this image?"},
            {"type": "image_url", "image_url": {"url": DATA_IMG, "detail": "high"}},
        ]),
    ])
    content = svc._convert_to_responses_input(req)["input"][0]["content"]
    check("content is a list (not dropped to '')", isinstance(content, list) and len(content) == 2)
    check("text → input_text", content[0] == {"type": "input_text", "text": "what is in this image?"})
    check("image → input_image w/ url", content[1]["type"] == "input_image" and content[1]["image_url"] == DATA_IMG)
    check("image detail preserved", content[1].get("detail") == "high")

    print("── system list content flattened to instructions text ──")
    req = ChatCompletionRequest(model="openai-gpt-5-5", messages=[
        Message(role="system", content=[{"type": "text", "text": "You are terse."}]),
        Message(role="user", content="hi"),
    ])
    params = svc._convert_to_responses_input(req)
    check("system text → instructions", params.get("instructions") == "You are terse.")

    print("── assistant list content flattened to text ──")
    req = ChatCompletionRequest(model="openai-gpt-5-5", messages=[
        Message(role="user", content="hi"),
        Message(role="assistant", content=[{"type": "text", "text": "hello there"}]),
        Message(role="user", content="more"),
    ])
    items = svc._convert_to_responses_input(req)["input"]
    asst = [i for i in items if i.get("role") == "assistant"][0]
    check("assistant content flattened to str", asst["content"] == "hello there")

    print("── vision disabled drops image but keeps text ──")
    from app.core.config import settings
    orig = settings.enable_vision
    try:
        settings.enable_vision = False
        req = ChatCompletionRequest(model="openai-gpt-5-5", messages=[
            Message(role="user", content=[
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": DATA_IMG}},
            ]),
        ])
        content = svc._convert_to_responses_input(req)["input"][0]["content"]
        check("vision off → only text part remains", content == [{"type": "input_text", "text": "describe"}])
    finally:
        settings.enable_vision = orig

    print()
    if failures:
        print(f"❌ {len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("✅ all checks passed")


if __name__ == "__main__":
    run()
