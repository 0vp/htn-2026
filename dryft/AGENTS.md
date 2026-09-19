# Workspace conventions

- Use uv for all Python installation, dependency management, and execution. Do not use pip, Conda, or bare system Python for this project.
- Python is pinned in `.python-version` and `pyproject.toml`; uv is pinned by `tool.uv.required-version`. Preserve these pins unless deliberately updating them.
- Use `uv sync --locked` and `uv run --locked ...`. For Linux x86_64 GPU development, use `uv sync --locked --extra gpu` and `uv run --locked --extra gpu ...`.
- Pin direct dependencies exactly and regenerate `uv.lock` with `uv lock` after an intentional dependency change. Keep the lockfile with the project to pin transitive dependencies and artifact hashes.
- Windows is for preparation tooling. The Linux-only GPU extra targets the published CUDA 12.4 runtime; Windows does not install that extra's packages.
- Do not create a nested Git repository in dryft. The Git repository is the parent `htn-2026` folder. The user subsequently authorized committing and pushing immediately, superseding the earlier 00:08 schedule. Exclude ignored environments, binaries, credentials, logs, and results. Preserve existing parent history.
- Keep the official starter unchanged until it is available and its instructions have been read. Do not invent a replacement engine.
- The official starter has been imported at revision `c2405f19fae577539969c5face3914b116757ae6`. Read `QWEN_ENGINE_CONTRACT.md` before engine edits and `OPTIMIZATION_GUIDE.md` before replacing model operations. Upstream agent guidance is preserved in `docs/starter/AGENTS.md`; the uv conventions here take precedence over upstream pip examples.
- Only `dryft/engine` relative to the parent repository is the submission folder. Keep agents, notes, tokens, and tools outside it. Consult live website/CLI behavior when old starter public-run instructions conflict with the current participant guide.
