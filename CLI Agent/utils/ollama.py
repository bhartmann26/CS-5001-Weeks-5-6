"""
Ollama client — wraps HTTP calls to local Ollama server.
Supports streaming and non-streaming generation.
"""

import json
import urllib.request
import urllib.error
from utils.console import Console


OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"


class OllamaClient:
    def __init__(self, url: str = OLLAMA_URL, model: str = DEFAULT_MODEL):
        self.url = url.rstrip("/")
        self.model = model

    def health_check(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                data = json.loads(r.read())
                models = [m["name"] for m in data.get("models", [])]
                # Accept exact match or prefix (llama3.2:3b matches llama3.2:3b-instruct etc.)
                if any(m == self.model or m.startswith(self.model) for m in models):
                    return True
                Console.warning(
                    f"Model '{self.model}' not found. Available: {', '.join(models) or 'none'}\n"
                    f"  Run: ollama pull {self.model}"
                )
                return False
        except Exception as e:
            Console.warning(f"Cannot reach Ollama at {self.url}: {e}")
            return False

    def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        """Single-turn generation (non-streaming)."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                return data.get("response", "").strip()
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama generate failed: {e}") from e

    def generate_stream(self, prompt: str, temperature: float = 0.2, max_tokens: int = 2048):
        """Stream tokens. Yields str chunks."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            for line in r:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    if chunk.get("response"):
                        yield chunk["response"]
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    def generate_json(self, prompt: str, temperature: float = 0.1, max_tokens: int = 2048) -> dict:
        """Generate and parse JSON response. Retries once on parse failure."""
        for attempt in range(2):
            raw = self.generate(prompt, temperature=temperature, max_tokens=max_tokens)
            if not raw or not raw.strip():
                Console.warning(f"Ollama returned empty response (attempt {attempt+1}/2)")
                if attempt == 1:
                    raise ValueError("Ollama returned empty response after 2 attempts")
                continue
            
            # Strip markdown fences
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            # Extract first JSON object
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start == -1 or end == 0:
                if attempt == 0:
                    Console.warning(f"AI returned non-JSON (attempt 1/2): {raw[:100]}")
                    continue
                raise ValueError(f"No JSON object found in response:\n{raw[:500]}")
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError as e:
                if attempt == 0:
                    Console.warning(f"JSON parse error ({e}), retrying…")
                    continue
                raise ValueError(f"Failed to parse AI JSON: {e}\nRaw:\n{raw[:500]}") from e
        return {}
