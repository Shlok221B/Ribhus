# Setup

Local install for Ribhus on macOS (Apple Silicon or Intel). For contributor skill format, see [skills.md](skills.md).

## 1. Install `uv`

Ribhus uses [uv](https://docs.astral.sh/uv/) for the Python env and CLI.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Installs to `~/.local/bin`. Ensure it is on your PATH (zsh):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
uv --version
```

If a terminal still says `command not found: uv`, open a new tab or run `source ~/.zshrc`. You can always call `~/.local/bin/uv` directly.

## 2. Clone and sync

```bash
git clone https://github.com/<you>/Ribhus.git
cd Ribhus

cp .env.example .env

uv sync --extra dev
uv run playwright install chromium
```

## 3. Choose a model provider

Edit `.env`. Ribhus speaks the OpenAI Chat Completions API — any compatible endpoint works.

### Option A — OpenAI (cloud)

```env
RIBHUS_API_KEY=sk-...
RIBHUS_BASE_URL=https://api.openai.com/v1
RIBHUS_MODEL=gpt-4o-mini
```

### Option B — Ollama on this Mac (e.g. Gemma 4 26B)

1. Install [Ollama](https://ollama.com) and pull a model (example used in local testing):

```bash
ollama pull gemma4:26b
ollama list                    # confirm the name
curl -s http://localhost:11434/v1/models   # OpenAI-compatible API up
```

2. Point Ribhus at Ollama. The API key can be any non-empty string:

```env
RIBHUS_API_KEY=ollama
RIBHUS_BASE_URL=http://localhost:11434/v1
RIBHUS_MODEL=gemma4:26b
```

Prefer a model with **tools** (and ideally **thinking**) support if you want agent tool-calling. Check with:

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

Keep `ollama serve` running (the Mac app usually does this). First reply after idle can be slow while a large model loads into memory.

### Option C — OpenRouter

```env
RIBHUS_API_KEY=sk-or-...
RIBHUS_BASE_URL=https://openrouter.ai/api/v1
RIBHUS_MODEL=google/gemma-3-27b-it   # example; use an OpenRouter model id
```

## 4. Run

```bash
uv run ribhus --help
uv run ribhus                 # interactive
uv run ribhus "What's 2+2?"
```

Optional: install bundled skills

```bash
uv run ribhus skill install travel
uv run ribhus skill install company-research
uv run ribhus skill install football
```

## Quick checklist

| Step | Check |
|------|--------|
| `uv` | `uv --version` |
| env | `.env` exists with `RIBHUS_*` set |
| deps | `uv sync --extra dev` succeeded |
| browser | `uv run playwright install chromium` once |
| Ollama (if used) | `ollama list` shows your model; port `11434` responds |

## Troubleshooting

**`zsh: command not found: uv`**  
PATH missing `~/.local/bin`. Run `source ~/.zshrc`, or use `~/.local/bin/uv run ribhus`.

**`RIBHUS_API_KEY is required`**  
Empty key in `.env`. For Ollama set `RIBHUS_API_KEY=ollama`.

**Connection refused to `localhost:11434`**  
Start Ollama (`open -a Ollama` or `ollama serve`), then retry.

**Model not found**  
`RIBHUS_MODEL` must match `ollama list` exactly (e.g. `gemma4:26b`).

**Slow first response on 26B**  
Normal cold start. Subsequent turns are faster while the model stays loaded.
