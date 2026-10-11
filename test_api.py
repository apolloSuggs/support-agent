"""First API call: confirms our key works and we get a response back."""

from dotenv import load_dotenv
import anthropic

# Reads .env and puts ANTHROPIC_API_KEY into the environment.
load_dotenv()

# The client finds ANTHROPIC_API_KEY in the environment automatically.
client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-haiku-4-5-20251001",  # small, fast, cheap model — fine for a connection test
    max_tokens=100,                     # cap on how long the reply can be
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)

# response.content is a list of blocks; a plain text reply is one text block.
print(response.content[0].text)
print("stop_reason:", response.stop_reason)
