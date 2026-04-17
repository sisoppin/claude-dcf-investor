# AI Agent (Online + Offline) with Local MCP Servers

A Python ReAct-style agent that runs against either **Perplexity** (online) or
**local Ollama** (offline), with four **local MCP servers** for internet search,
file editing, financial data, and DCF modelling.

Everything is configured through a single `.env` file.

---

## Features

- **Two backends, one switch** — `AGENT_MODE=online|offline` toggles between
  Perplexity and Ollama. Both use OpenAI-compatible endpoints under the hood.
- **ReAct loop** — Think → Act → Observe → repeat, using native function calling.
  Each step is shown in colored panels when `VERBOSE=true`.
- **Local MCP servers** — spawned as subprocesses over stdio. No hosting required.
  - `search` — `web_search`, `news_search`, `research`, `fetch_url`
  - `file_editor` — sandboxed read/write/edit for json/yaml/csv/xlsx
  - `finance` — yfinance quotes, financials, treasury yield, Damodaran ERP, SEC EDGAR
  - `dcf` — build a multi-sheet DCF valuation xlsx from a structured spec
- **Pluggable** — add more MCP servers by editing `config/mcp_servers.json`.
- **Sandboxed file ops** — every file path is resolved inside `WORKSPACE_PATH`.

---

## Project layout

```
ai-agent/
├── .env.example
├── requirements.txt
├── config/
│   └── mcp_servers.json        # which MCP servers to launch
├── src/
│   ├── config.py               # loads .env into a typed Settings object
│   ├── main.py                 # CLI entry point (--valuation flag for DCF mode)
│   ├── agent/
│   │   ├── prompts.py          # DEFAULT_SYSTEM_PROMPT + VALUATION_PROMPT
│   │   └── react_agent.py      # think → act → observe loop
│   ├── providers/
│   │   ├── base.py
│   │   ├── perplexity.py       # online
│   │   ├── ollama.py           # offline
│   │   └── factory.py
│   └── mcp_client/
│       └── manager.py          # spawns + routes calls to MCP servers
├── mcp_servers/
│   ├── search_server.py        # MCP: search & fetch
│   ├── file_editor_server.py   # MCP: file CRUD (json/yaml/csv/xlsx)
│   ├── finance_server.py       # MCP: yfinance research, beta, peers, Rf, ERP
│   ├── dcf_builder_server.py   # MCP: build the DCF xlsx from a spec
│   └── dcf/                    # DCF builder library (used by dcf_builder_server)
│       ├── styles.py           # color/font/format constants
│       ├── spec.py             # spec schema + validation
│       └── builder.py          # 5-sheet xlsx generator
├── test_builder.py             # offline test of the DCF builder
└── workspace/                  # sandbox root for file_editor + DCF outputs
```

---

## Setup

### 1. Install dependencies

```bash
cd ai-agent
python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# then edit .env
```

Key settings:

| Variable             | Purpose                                                  |
|----------------------|----------------------------------------------------------|
| `AGENT_MODE`         | `online` (Perplexity) or `offline` (Ollama)              |
| `PERPLEXITY_API_KEY` | Required when `AGENT_MODE=online`                        |
| `PERPLEXITY_MODEL`   | e.g. `sonar`, `sonar-pro`                                |
| `OLLAMA_BASE_URL`    | Default `http://localhost:11434/v1` — note the `/v1`     |
| `OLLAMA_MODEL`       | Must support tool calling: `llama3.1`, `qwen2.5`, …      |
| `MAX_ITERATIONS`     | Cap on ReAct loop steps per user turn                    |
| `WORKSPACE_PATH`     | Sandbox dir for the file editor MCP                      |
| `SEARCH_PROVIDER`    | `duckduckgo` (no key) or `tavily` (set `TAVILY_API_KEY`) |

### 3. Make sure Ollama can call tools (offline mode only)

Pull a model that supports function calling:

```bash
ollama pull llama3.1
# or: qwen2.5, mistral-nemo, llama3.2 (3B+), etc.
```

Then make sure Ollama is running:

```bash
ollama serve     # if not already running as a service
```

### 4. Run

```bash
python -m src.main
```

You'll get a CLI prompt:

```
you › find the top 3 python web frameworks in 2026 and write them to frameworks.json
```

CLI commands:

- `/tools`  — list every MCP tool the agent has loaded
- `/reset`  — clear conversation history (keeps the system prompt)
- `/exit`   — quit

---

## Switching between online and offline

Just change one line in `.env`:

```bash
# online
AGENT_MODE=online

# offline
AGENT_MODE=offline
```

No code changes needed.

---

## Adding more MCP servers

Edit `config/mcp_servers.json`:

```json
{
  "mcpServers": {
    "search":      { "command": "python", "args": ["-m", "mcp_servers.search_server"],      "enabled": true },
    "file_editor": { "command": "python", "args": ["-m", "mcp_servers.file_editor_server"], "enabled": true },
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "/path/to/repo"],
      "enabled": true
    }
  }
}
```

Anything that speaks MCP over stdio works — community servers, your own, or
the official reference servers.

---

## DCF Valuation Mode

The agent ships with a specialized **valuation workflow** that produces a
complete, formula-linked, 5-sheet DCF xlsx for any company.

### One-shot CLI

```bash
python -m src.main --valuation "Reliance Industries"
# or with a ticker
python -m src.main --valuation "RELIANCE.NS"
python -m src.main --valuation "AAPL"
```

The agent will:

1. **Research** — pull financials, beta, peer multiples, Rf, ERP via the
   `finance__*` MCP tools (yfinance + web fallbacks).
2. **Fill the spec** — populate the structured DCF model spec.
3. **Validate** — call `dcf_builder__validate_model_spec` to catch missing
   fields before building.
4. **Build** — call `dcf_builder__build_dcf_model` to write the .xlsx into
   `WORKSPACE_PATH`.
5. **Report** — summarize headline numbers and flag any `[ESTIMATED]` inputs.

### Output workbook

| Sheet               | Color    | Contents                                                     |
|---------------------|----------|--------------------------------------------------------------|
| Cover               | navy     | Bear/Base/Bull summary, color legend, key observations       |
| Assumptions         | navy     | All inputs in blue; WACC build; scenario table; peer comps   |
| DCF                 | navy     | 7 sections: revenue → ebitda → fcff → wacc → val → sens → reverse |
| Returns_DCF         | **teal** | IRR matrix; exit = DCF intrinsic only; 20% IRR row yellow    |
| Returns_Multiple    | **dark red** | Multiple-based IRR; peer comps; synthesis A vs B          |

Format conventions enforced by the builder:

- **Blue** text = hardcoded input (Assumptions only)
- **Black** text = formula
- **Green** text = cross-sheet link
- **Yellow** background = key cells (CMP, WACC, TGR, Implied Price, 20% IRR row)
- Negatives in parentheses; zeros displayed as `–`
- Zero formula errors guaranteed (verified in CI: `python test_builder.py`)

### Architecture: LLM extracts → code generates

Building a multi-sheet DCF cell-by-cell with an LLM is slow and error-prone.
This agent uses a **hybrid pattern**: the LLM does the research (which it's
good at) and fills a JSON spec; a deterministic Python builder consumes the
spec and produces the xlsx with all formulas correctly wired (which code is
good at). You get the best of both worlds — flexible inputs, bulletproof
output.

### Interactive valuation

You can also drive valuation interactively. From the REPL:

```
you › Build a DCF for HDFC Bank. Ticker is HDFCBANK.NS, this is an Indian
      company. Use FY24 and FY23 actuals. Save the file as hdfc_dcf.xlsx.
```

The agent will discover and use the `finance__*` and `dcf_builder__*` tools
automatically, but you'll get better results by invoking with `--valuation`
which switches in the dedicated valuation system prompt.

### Testing the builder offline

The builder is independently testable with no network or LLM:

```bash
python test_builder.py
```

This builds a workbook from a synthetic spec and verifies:
- spec validates,
- all 5 sheets are created in the right order,
- no `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#NULL!`, `#N/A`, or `#NUM!`
  cells after `openpyxl` write.

For a stricter check, recalculate with LibreOffice and re-scan:

```bash
libreoffice --headless --calc --convert-to xlsx /tmp/test_dcf.xlsx --outdir /tmp/recalc
python -c "
from openpyxl import load_workbook; import re
wb = load_workbook('/tmp/recalc/test_dcf.xlsx', data_only=True)
bad = re.compile(r'#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A|#NUM!')
errs = [(s, c.coordinate, c.value) for s in wb.sheetnames
        for r in wb[s].iter_rows() for c in r
        if c.value and bad.search(str(c.value))]
print('errors after live recalc:', len(errs))
"
```

---

## How the ReAct loop works

For each user message:

1. The agent sends the conversation + the full tool list to the LLM.
2. The LLM responds with either:
   - **A final answer** (no tool calls) → loop ends.
   - **One or more tool calls** → the agent runs each via the right MCP server,
     appends the results as `role=tool` messages, and loops.
3. Loop runs at most `MAX_ITERATIONS` times.

In verbose mode you'll see three panels per step:

- 🧠 **Thought** — the model's reasoning text
- 🛠 **Action** — the tool name + arguments
- 👀 **Observation** — the tool result

---

## Tool reference

### `search__*`

- `web_search(query, num_results=5)` — general web search
- `news_search(query, num_results=5)` — news search
- `research(topic, num_results=5)` — runs three angles (overview / latest / criticism)
- `fetch_url(url, max_chars=8000)` — fetch and clean a single URL's text

### `file_editor__*` (all paths relative to `WORKSPACE_PATH`)

- `list_files(subdir="")`
- `read_file(path)` — auto-detects json/yaml/csv/xlsx
- `write_file(path, content)` — raw text write
- `edit_json(path, json_path, value)` — JSONPath edit, e.g. `$.users[0].name`
- `edit_yaml(path, yaml_path, value)` — dotted path, e.g. `db.host` or `users[0].name`
- `read_csv(path, max_rows=100)`
- `append_csv(path, row)` — `row` may be a list or dict
- `read_xlsx(path, sheet="", max_rows=100)`
- `write_xlsx(path, sheet, rows)` — `rows` may be `list[list]` or `list[dict]`
- `delete_file(path)`

---

## Troubleshooting

**`PERPLEXITY_API_KEY is empty`** — set it in `.env` or switch to `AGENT_MODE=offline`.

**Ollama returns no tool calls** — your model probably doesn't support function
calling. Use `llama3.1`, `qwen2.5`, or `mistral-nemo`.

**`Reached max_iterations`** — bump `MAX_ITERATIONS` or simplify the request.

**Path escapes workspace** — the file editor refuses paths that resolve outside
`WORKSPACE_PATH`. Use a relative path inside the workspace.

**MCP server fails to start** — run it directly to see the error:
`python -m mcp_servers.search_server`
