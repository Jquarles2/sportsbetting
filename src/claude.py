"""One place that calls Claude (Haiku), shared by the pick write-ups and the game talks.

Needs ANTHROPIC_API_KEY in secrets (see .streamlit/secrets.toml.example). Each call costs a
fraction of a cent.
"""
import anthropic

from src.config import get_secret

MODEL = "claude-haiku-5-5"


def ask(system, prompt, client=None, max_tokens=500):
    """Send one prompt and return Claude's reply as text.

    Raises RuntimeError if there's no key or the reply is empty (for example a refusal or a
    cut-off), and anthropic.APIError if the call itself fails. client is for tests.
    """
    if client is None:
        api_key = get_secret("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("No ANTHROPIC_API_KEY found. Add it to your secrets.")
        client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        output_config={"effort": "low"},  # short notes don't need deep thinking
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(f"No reply returned (stop reason: {response.stop_reason}).")
    return text
