# Install Just Build

Just Build is an **experimental preview**. It runs inside **Codex** or **Claude Code**, not as a standalone executable. Install only the package matching your host. It does not require a marketplace plugin, API key for this skill, or a Python `pip install` for ordinary use. The host itself must already be installed/configured.

Installing from a clone or the source ZIP? Start with [Install from source](#install-from-source). Using a host ZIP? Follow the [Codex](#install-into-codex) or [Claude Code](#install-into-claude-code) steps. Maintainers can jump to [GitHub upload](#upload-the-full-project-to-github).

## Package files

- `just-build-source.zip` — complete GitHub source checkout, including `.github/`, docs, tests, and both host skill trees.
- `just-build-codex.zip` — ready-to-copy `just-build/` skill folder for Codex.
- `just-build-claude-code.zip` — ready-to-copy `just-build/` skill folder for Claude Code.
- `SHA256SUMS` — SHA-256 hashes for the ZIPs, useful for checking download integrity against the source you trust.

This source preview is **0.0.1**, recorded in `VERSION`. The release builder produces these four files with simple filenames. A source-only download contains the repository, not the separate host ZIPs.

You can share the **entire source repository** on GitHub while installing only one host ZIP on your computer. The included runnable examples are actual repository files; they are **not** required to run the skill.

## Requirements

1. Codex or Claude Code with local skill support, running on your computer.
2. Python **3.11+** reachable by the agent's terminal tools (`python --version`, or `python3 --version`).
3. Git **2.36+** for guarded Git checks (`git --version`).
4. A workspace where you are comfortable letting the agent read and edit files. If possible, use a sandboxed or disposable directory for your first run. The skill does not isolate commands from your system by itself.

## Install from source

Extract `just-build-source.zip`, or clone the repository, then open a terminal in the folder containing `README.md`, `codex/` and `claude-code/`. Choose one host below. These commands install a personal copy; they refuse to copy over an existing destination.

### macOS/Linux

For Codex, use:

```sh
skill_source="codex/just-build"
skill_target="$HOME/.agents/skills/just-build"
```

For Claude Code, use these two lines instead:

```sh
skill_source="claude-code/just-build"
skill_target="$HOME/.claude/skills/just-build"
```

Then run:

```sh
if [ -e "$skill_target" ] || [ -L "$skill_target" ]; then
  echo "Destination exists. Back it up or rename it before installing." >&2
else
  mkdir -p "$(dirname "$skill_target")" &&
    cp -R "$skill_source" "$skill_target" &&
    ls "$skill_target/SKILL.md"
fi
```

### Windows PowerShell

For Codex, use:

```powershell
$skillSource = ".\codex\just-build"
$skillTarget = "$HOME\.agents\skills\just-build"
```

For Claude Code, use these two lines instead:

```powershell
$skillSource = ".\claude-code\just-build"
$skillTarget = "$HOME\.claude\skills\just-build"
```

Then run:

```powershell
if (Test-Path -LiteralPath $skillTarget) {
    throw "Destination exists. Back it up or rename it before installing."
}
New-Item -ItemType Directory -Force (Split-Path -Parent $skillTarget) | Out-Null
Copy-Item -LiteralPath $skillSource -Destination $skillTarget -Recurse -ErrorAction Stop
Test-Path -LiteralPath (Join-Path $skillTarget "SKILL.md")
```

The last command should print `True`. For a project-only copy, set the target to your project's `.agents/skills/just-build` (Codex) or `.claude/skills/just-build` (Claude Code). Keep the complete skill folder. Continue with [Start using it](#start-using-it).

## Install into Codex

**Personal installation** (available across projects):

- macOS/Linux: `~/.agents/skills/just-build/SKILL.md`
- Windows: `%USERPROFILE%\.agents\skills\just-build\SKILL.md`

**Project-only installation** (available only inside a particular Git project or folder):

- `<your-project>/.agents/skills/just-build/SKILL.md`

Choose **one** location per host so you do not have two competing copies. The folder must contain `SKILL.md` *and* its `scripts/`, `references/`, `examples/` and other supporting files; do not copy only `SKILL.md`.

### macOS/Linux — Codex personal install

Extract `just-build-codex.zip` somewhere, such as your Downloads folder; the extracted folder should be named `just-build`. From the directory **containing** that extracted folder:

```sh
if [ -e "$HOME/.agents/skills/just-build" ] || [ -L "$HOME/.agents/skills/just-build" ]; then
  echo "Destination exists. Back it up or rename it before installing." >&2
else
  mkdir -p "$HOME/.agents/skills" &&
    cp -R just-build "$HOME/.agents/skills/just-build" &&
    ls "$HOME/.agents/skills/just-build/SKILL.md"
fi
```

If the target already exists, **back up or rename the existing folder first**; `cp -R` is not a clean update strategy for existing installations.

### Windows PowerShell — Codex personal install

Extract `just-build-codex.zip` via File Explorer. In PowerShell, `cd` to the directory containing the extracted `just-build` folder, then run:

```powershell
if (Test-Path -LiteralPath "$HOME\.agents\skills\just-build") {
    throw "Destination exists. Back it up or rename it before installing."
}
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -LiteralPath ".\just-build" -Destination "$HOME\.agents\skills\just-build" -Recurse -ErrorAction Stop
Test-Path -LiteralPath "$HOME\.agents\skills\just-build\SKILL.md"
```

The last command should print `True`. If the destination exists, back it up or rename it before copying.

For project-only Codex installation, use `<your-project>/.agents/skills/` instead of the personal `~/.agents/skills/` directory.

## Install into Claude Code

Choose **one** of these locations:

- Personal: `~/.claude/skills/just-build/SKILL.md` (Windows: `%USERPROFILE%\.claude\skills\just-build\SKILL.md`)
- Project-only: `<your-project>/.claude/skills/just-build/SKILL.md`

### macOS/Linux — Claude Code personal install

Extract `just-build-claude-code.zip`, open a terminal in the directory containing its `just-build` folder, then:

```sh
if [ -e "$HOME/.claude/skills/just-build" ] || [ -L "$HOME/.claude/skills/just-build" ]; then
  echo "Destination exists. Back it up or rename it before installing." >&2
else
  mkdir -p "$HOME/.claude/skills" &&
    cp -R just-build "$HOME/.claude/skills/just-build" &&
    ls "$HOME/.claude/skills/just-build/SKILL.md"
fi
```

### Windows PowerShell — Claude Code personal install

Extract `just-build-claude-code.zip`, open PowerShell in its containing directory, then:

```powershell
if (Test-Path -LiteralPath "$HOME\.claude\skills\just-build") {
    throw "Destination exists. Back it up or rename it before installing."
}
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -LiteralPath ".\just-build" -Destination "$HOME\.claude\skills\just-build" -Recurse -ErrorAction Stop
Test-Path -LiteralPath "$HOME\.claude\skills\just-build\SKILL.md"
```

For project-only installation, use `<your-project>/.claude/skills/` instead of the personal directory. Before replacing any existing `just-build` folder, back it up.

## Start using it

Restart the host, or start a **new session** in your authorized project directory so it can discover the skill. Do not run from a folder containing private credentials or other files you do not want the agent to read.

| What you want | Codex chat | Claude Code chat |
|---|---|---|
| Research and build | `$just-build` | `/just-build` |
| Select a mode explicitly | `$just-build auto` | `/just-build auto` |
| Choose with guidance | `$just-build guided` | `/just-build guided` |
| Build a specific idea | `$just-build build a local notes app` | `/just-build build a local notes app` |

The host may ask for terminal/file permissions. Review them instead of granting unrestricted system access. Generated projects go in the project/workspace you authorize, not inside the installed skill folder.

If the skill is not recognized: verify `SKILL.md` is directly under the `just-build/` folder, verify you installed the **correct host's ZIP**, refresh/restart your host, and check that local skill support is enabled. For Claude Code, try `/help` to discover available skills; for Codex, explicitly enter `$just-build` in chat.

## Upload the full project to GitHub

**Do not upload the source ZIP as a single file into the repository.** GitHub needs the *extracted files and folders* to show source code, render the README and discover `.github/workflows/`.

1. Extract `just-build-source.zip`. This creates a directory called `just-build` containing `README.md`, `INSTALL.md`, `.github/`, `codex/`, `claude-code/`, `examples/`, `tools/`, and `docs/`.
2. On GitHub, create a new **empty** repository called `just-build` (or choose a name). Do **not** initialize it with another README, license or `.gitignore`; those are included.
3. Open a terminal **inside the extracted `just-build` directory** and run:

```sh
git init
git add .
git commit -m "Initial public preview"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/just-build.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username and update `just-build` if the repository has a different name. `git push` requires you to authenticate with GitHub using your configured credential manager, token, or SSH key; password-based Git HTTPS authentication is not supported.

4. On GitHub, open **Actions** and check that CI succeeds. In **Settings**, review branch protection/rulesets, secret scanning, and Dependabot recommendations in [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md).
5. Share the repository URL after checking the README and CI. The project is currently an experimental preview, particularly for Claude Code: a local skill test does not establish a verified native Claude build.

You can optionally add the install ZIPs as assets in a manual GitHub prerelease (mark it as a prerelease). GitHub requires a tag when publishing a release; you can use `v0.0.1`, pointing it to the reviewed commit. The repository itself requires **no** release or tag to be used.

## Maintenance verification (optional for end users)

From the extracted source folder, run:

```sh
python -m pip install -r requirements-dev.txt
python tools/check_repo.py
python tools/run_repository_tests.py
python codex/just-build/scripts/run_skill_tests.py
python claude-code/just-build/scripts/run_skill_tests.py
python tools/run_examples.py
python tools/build_release.py
python tools/verify_release.py --artifacts dist
```

The development dependencies are for repository maintainers, **not** ordinary skill installation. The release builder refuses to overwrite existing artifacts, so delete or rename the generated `dist/` directory before a repeat build. The manual GitHub release-check workflow verifies a reviewed commit; it does not publish or modify your repository.

Official host references: [Codex skills](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) · [Claude Code skills](https://code.claude.com/docs/en/skills#choose-where-skills-load).
