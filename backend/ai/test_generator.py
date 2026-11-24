"""
backend/ai/test_generator.py
AI-powered test scenario generation from natural language using Gemini API.
Falls back to helpful template if API key is not configured.
"""

from __future__ import annotations

import os

SYSTEM_PROMPT = """You are an expert automotive HMI test engineer who writes CANvas test scenarios.

CANvas test YAML format:
```yaml
name: "Test Name"
description: "What this test verifies"
bus: virtual
steps:
  - action: send_signal
    message: <MessageName>
    signal: <SignalName>
    value: <float>
    description: "Human readable description"
  - action: wait
    ms: <milliseconds>
  - action: assert_signal
    message: <MessageName>
    signal: <SignalName>
    expected: <float>
    description: "What we expect"
  - action: log
    message: "Log message"
```

Available actions: send_signal, send_message, wait, assert_signal, assert_visual, log

Rules:
- Only use signals and messages that exist in the DBC context provided
- Use realistic physical values (e.g. VehicleSpeed in km/h 0-250, FuelLevel 0-100%)
- Always start by setting initial conditions, then apply the test scenario
- Include wait steps between signal sends to allow HMI to react (200-500ms typical)
- Add assert_signal steps to verify expected behavior
- Write descriptive names and step descriptions

Respond with ONLY the YAML content, no markdown code blocks, no explanation.
"""


async def generate_test_yaml(prompt: str, dbc_context: str = "") -> str:
    """Generate a CANvas test YAML from natural language."""

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        return _fallback_template(prompt, dbc_context)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        user_message = f"""DBC Database Context:
{dbc_context or "(No DBC loaded — use generic signal names as examples)"}

Test to generate:
{prompt}

Generate the CANvas test YAML:"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=2048,
            ),
        )

        yaml_text = response.text.strip()
        # Strip markdown code fences if model added them
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            yaml_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        return yaml_text

    except ImportError:
        return _fallback_template(prompt, dbc_context) + "\n# Note: Install google-genai for AI generation: pip install google-genai"
    except Exception as exc:
        return f"# AI generation failed: {exc}\n" + _fallback_template(prompt, dbc_context)


def _fallback_template(prompt: str, dbc_context: str) -> str:
    """Return a helpful template when AI is not available."""
    return f"""# Generated template for: {prompt}
# Set GEMINI_API_KEY environment variable for AI-powered generation
#
# Available signals from your DBC:
# {chr(10).join('# ' + line for line in dbc_context.splitlines()) if dbc_context else '# (No DBC loaded)'}

name: "{prompt[:60]}"
description: "Auto-generated template — customize the values below"
bus: virtual
steps:
  - action: send_signal
    message: BodyControl
    signal: FuelLevel
    value: 5.0
    description: "Set initial condition"
  - action: wait
    ms: 500
    description: "Wait for HMI to react"
  - action: assert_signal
    message: BodyControl
    signal: WarningLamp
    expected: 1.0
    description: "Verify warning activated"
  - action: log
    message: "Test complete"
"""
