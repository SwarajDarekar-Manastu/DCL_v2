# Open WebUI functions (DCL)

Two functions connect the stack's Open WebUI (v0.12.3, port `DCL_OPENWEBUI_PORT`, default 8300) to the
DCL backend:

| Function id | File to install | What it adds |
|-------------|-----------------|--------------|
| `manastu_engine` | `bundled/manastu_engine.py` | the model "Manastu Propulsion Engine" (`manastu_engine.main`) |
| `manastu_actions` | `bundled/manastu_actions.py` | Show trace, Add to benchmark and Report issue under the engine's answers |

The files in `bundled/` are generated: edit `pipe_manastu_engine.py`, `actions_manastu.py`,
`api_endpoint.py` or `config.py`, then run `uv run python frontend/openwebui/build_functions.py`.

## Install or update (a person runs this once Open WebUI is up)

1. Open `http://<host>:8300` in a browser and create the first account; it becomes the admin.
   Sessions and scripts never create this account.
2. As that admin: Admin Panel › Settings › General › enable API keys; then Settings › Account › API
   keys › create a key.
3. Make sure `.env` has `DCL_PIPE_SHARED_SECRET` (same value the API container reads) and
   `DCL_CONSOLE_BASE_URL` (the Console address engineers open in their browser).
4. From the repository root:

   ```bash
   OWUI_API_KEY=<the key> uv run python frontend/openwebui/install_functions.py --dry-run
   OWUI_API_KEY=<the key> uv run python frontend/openwebui/install_functions.py
   ```

The script is safe to run again after every update of the bundles. It:

- creates or updates both functions and switches them on;
- sets the valves: `ENGINE_URL = http://api:8200` (the API container inside the stack;
  override with `DCL_ENGINE_URL_FOR_OWUI`), `ENGINE_SHARED_SECRET` from `.env`, `CONSOLE_URL` from
  `DCL_CONSOLE_BASE_URL`;
- attaches the three actions to the model `manastu_engine.main` only (they do not appear under the
  plain Gemini model);
- never prints the secret or the API key. `OWUI_URL` overrides the Open WebUI address
  (default `http://localhost:${DCL_OPENWEBUI_PORT}`).

5. In Admin Panel › Models, set who sees "Manastu Propulsion Engine" (the engineering groups).
   The only provider connection in Open WebUI is the Manastu Gemini gateway (file 08 §3.1).

## What links from chat open

Citations and the Show-trace embed link to `DCL_CONSOLE_BASE_URL/docs/{doc_id}/viewer?anchor=…`.
The Console (container in `frontend/console/Dockerfile`) serves every route from `index.html`, so
these links open the right page. The page shows the document once the Console's Entra ID
registration is configured (the `VITE_ENTRA_*` build arguments and the `DCL_CONSOLE_*` settings);
until then it shows which settings are missing. After sign-in, the browser returns to the
link that was opened.
