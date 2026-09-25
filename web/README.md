# Ribhus dashboard

Local prompt-first UI for running tasks, managing skills and memory, and toggling channels / MCP / config.

Python serves the API and the built SPA (`ribhus dashboard` → http://127.0.0.1:8742/). This folder is the Vite + React frontend.

<p align="center">
  <img src="public/ribhus-2.png" alt="The Ribhus" width="720" />
</p>

## Run

From the repo root:

```bash
uv sync --extra dashboard --extra dev
cd web && npm install && npm run build && cd ..
uv run ribhus dashboard
```

| Flag | Effect |
| --- | --- |
| `--no-open` | Do not open a browser tab |
| `--no-build` | Skip `npm run build` even if `web/dist` is missing |
| `--host` / `--port` | Bind address (default `127.0.0.1:8742`) |

Loopback only by default. The server injects a session token into the HTML; API calls send it as `Authorization: Bearer …`.

### Frontend hot reload

```bash
uv run ribhus dashboard --no-open   # terminal 1 — API on :8742
cd web && npm run dev               # terminal 2 — UI on :5173
```

Vite proxies `/api` to `RIBHUS_DASHBOARD_URL` (default `http://127.0.0.1:8742`) and copies the session token from the Python HTML.

```bash
npm run typecheck
npm run build     # writes web/dist (gitignored)
```

## Pages

| Route | What it does |
| --- | --- |
| `/` | Start a task |
| `/tasks` | Task list |
| `/tasks/:id` | Result, events, approvals |
| `/skills` | List / install / remove |
| `/memory` | Search, add, forget |
| `/channels` | WhatsApp + email kill / resume |
| `/mcp` | Server status + test |
| `/config` | Model, flags (writes `.env`; restart to apply fully) |

Brand art: `public/ribhus-2.png` (sidebar mark; low-opacity home background). The engraving `public/ribhus-1.png` is used in the repo README.

## Stack

- React 19 + React Router 7 + Tailwind CSS 4
- FastAPI routers in `src/ribhus/web/`
- Tokens in `src/index.css` (source of truth)

Components use **shadcn / Tailwind role names** (`bg-background`, `text-foreground`, `bg-primary`, `text-muted-foreground`, `border-border`, `ring-ring`). Do not use palette hexes in JSX.

## Color — Forged Light

Direction: ancient Vedic craftsmanship × modern intelligence × divine fire/light. Not a saffron/gold “spiritual” product.

`#0B1020` → `#D97745` → `#D6A84F` → `#F4E8CF`

Cosmic darkness → human craft → divine fire → illumination.

Dark indigo is the default canvas. Copper and gold stay rare (~5% of a screen). Light mode remaps the **roles** only — add `class="light"` on `<html>` when you want it (no toggle yet).

### Palette (layer A — never on components)

| Name | Hex | Notes |
| --- | --- | --- |
| Indigo | `#0B1020` | Page canvas (dark) / ink (light) |
| Midnight | `#121A2E` | Cards |
| Dusk | `#1A2340` | Raised / hover |
| Bronze | `#2C3040` | Dark borders |
| Slate | `#474F66` | Input borders; muted text on light |
| Ivory | `#F7F3EA` | Body text (dark) / page (light) |
| Sand | `#A9A18F` | Muted text (dark) |
| Copper | `#D97745` | CTAs, focus, Ribhu |
| Gold | `#D6A84F` | Approvals / warning, Vaja |
| Glow | `#F4E8CF` | Generation glow only |
| Blue | `#7BA7C7` | Links / info, Vibhvan |
| Verdigris | `#5FAF8F` | Success |
| Rose | `#E0607E` | Errors |

CSS: `--palette-indigo`, `--palette-copper`, … plus `--ribhu` / `--vibhvan` / `--vaja` (brand art, not dashboard chrome).

### Theme roles (layer B — what the UI uses)

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `background` / `foreground` | indigo / ivory | ivory / indigo | Page + body text |
| `card` / `card-foreground` | midnight / ivory | `#FFFCF6` / indigo | Cards |
| `popover` / `popover-foreground` | dusk / ivory | `#FFFFFF` / indigo | Menus |
| `primary` / `primary-foreground` | copper / indigo | copper / indigo | One CTA per view, focus |
| `secondary` / `secondary-foreground` | dusk / ivory | `#E8E0D0` / indigo | Quiet buttons |
| `muted` / `muted-foreground` | midnight / sand | `#EDE6D6` / slate | Labels, helper text |
| `accent` / `accent-foreground` | dusk / ivory | `#EDE6D6` / indigo | Hover / selected — **not gold** |
| `destructive` / `destructive-foreground` | rose / indigo | rose / indigo | Errors, delete |
| `border` | bronze | `#D4CFC4` | Dividers |
| `input` | slate | `#C4BDB0` | Form edges |
| `ring` | copper | copper | Focus ring |
| `success` | verdigris | verdigris | Completed |
| `warning` | gold | gold | Approvals (fill, not body text) |
| `info` | blue | blue | Links |
| `chart-1` … `chart-5` | copper, gold, blue, verdigris, rose | same | Data |

Filled `primary`, `warning`, `success`, and `destructive` always use indigo as their foreground — never white.

### Gradients

Defined on `:root`, unused as page fills:

| Name | Stops | Where |
| --- | --- | --- |
| `--gradient-forge` | indigo → copper → gold → glow | Landing / lockup only |
| `--gradient-ember` | copper → gold | Primary hover / progress |
| `--gradient-horizon` | indigo → dusk | Dark atmosphere, low opacity |
| `--gradient-paper` | ivory → glow | Light atmosphere, low opacity |

`.glow-generate` is a soft `--palette-glow` shadow for “agent is working”.

### Agent colors (brand only)

| Ribhu | Role | Token |
| --- | --- | --- |
| Ribhu | Creation / craft | copper |
| Vibhvan | Expansion / intelligence | blue |
| Vaja | Abundance / power | gold |

Not assigned in the dashboard until multi-agent ships.
