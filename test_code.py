import os
import sys

from dotenv import load_dotenv
from openrouter import OpenRouter
from openrouter.types import UNSET

load_dotenv()

MODEL = "openrouter/owl-alpha"
MAX_TURNS = 5

ASSISTANT_NAME = "RamBabu"
ASSISTANT_INITIALS = "RB"
ASSISTANT_LABEL = f"[{ASSISTANT_INITIALS}] {ASSISTANT_NAME}"


def trim_history(messages):
    pairs = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "user":
            user_msg = messages[i]
            assistant_msg = None
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                assistant_msg = messages[i + 1]
                i += 2
            else:
                i += 1
            pairs.append((user_msg, assistant_msg))
        else:
            i += 1

    pairs = pairs[-MAX_TURNS:]
    trimmed = []
    for user_msg, assistant_msg in pairs:
        trimmed.append(user_msg)
        if assistant_msg:
            trimmed.append(assistant_msg)
    return trimmed


def chunk_text(chunk):
    """Pull text from one stream chunk (like TS: chunk.choices[0]?.delta?.content)."""
    if not chunk.choices:
        return ""
    delta = chunk.choices[0].delta
    content = delta.content
    if content is None or content is UNSET:
        return ""
    return content


def chat_stream(client, messages):
    """Stream tokens to stdout; return full assistant reply."""
    stream = client.chat.send(
        model=MODEL,
        messages=messages,
        stream=True,
    )

    parts = []
    print(f"{ASSISTANT_LABEL}: ", end="", flush=True)

    with stream:
        for chunk in stream:
            text = chunk_text(chunk)
            if text:
                parts.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()

    print("\n")
    return "".join(parts)


def chat_once(client, messages):
    """Non-streaming fallback."""
    response = client.chat.send(model=MODEL, messages=messages)
    reply = response.choices[0].message.content or ""
    print(f"{ASSISTANT_LABEL}: {reply}\n")
    return reply


def main():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Set OPENROUTER_API_KEY in your .env file.")
        return

    history = []
    use_stream = True

    print(f"Chat with {ASSISTANT_NAME} ({ASSISTANT_INITIALS}). Type 'quit' or 'exit' to stop.\n")

    with OpenRouter(api_key=api_key) as client:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Bye!")
                break

            history.append({"role": "user", "content": user_input})
            messages = trim_history(history)

            try:
                if use_stream:
                    reply = chat_stream(client, messages)
                else:
                    reply = chat_once(client, messages)
            except Exception as e:
                print(f"Error: {e}\n")
                history.pop()
                continue

            if reply:
                history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
