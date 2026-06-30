# LIMA NVDA Add-on — Approach Plan

This document is the investigation deliverable for session 1 of the LIMA NVDA
add-on work: how NVDA add-ons are built, how this repository is structured,
how we build and test the add-on, and how (and where) it eventually gets
listed for distribution. It closes with prior art and open questions for the
team.

## 1. What an NVDA add-on is

An NVDA add-on is a single zip file with a `.nvda-addon` extension. Inside
that zip are a `manifest.ini` file (the add-on's metadata: name, version,
author, supported NVDA versions, etc.) and an `addon/` folder containing the
actual code and resources.

The add-on installs *into NVDA itself* — NVDA (NonVisual Desktop Access) is a
free, open-source Windows screen-reader application. When a user installs an
add-on, NVDA unpacks it and runs its Python code inside NVDA's own bundled
Python interpreter, as part of the running screen reader process. Code that
should be available globally — i.e., regardless of which application the
user currently has focused — lives under `addon/globalPlugins/`. NVDA
discovers and loads every package/module it finds there at startup (or on a
plugin reload).

**This is not a browser extension.** An NVDA add-on has nothing to do with
Chrome, Edge, Firefox, or any browser's extension store. It is not packaged
as a `.crx`, it does not use the WebExtensions API, and it is never
distributed through the Chrome Web Store. It is a Windows-screen-reader
plugin, full stop. This distinction matters because "browser extension" and
"NVDA add-on" sound similar but are built, packaged, installed, and
distributed through entirely separate mechanisms — conflating them would
send the team down the wrong implementation path.

## 2. Folder/file structure

The repository is laid out as follows:

```
LIMA - NVDA Addon/
├─ buildVars.py            # addon metadata: name "LIMA", summary, version, min/lastTested NVDA
├─ manifest.ini.tpl        # from AddonTemplate
├─ sconstruct, site_scons/ # SCons build (from AddonTemplate)
├─ addon/
│  ├─ globalPlugins/
│  │  └─ lima/             # plugin as a PACKAGE (room to grow)
│  │     └─ __init__.py    # GlobalPlugin: one hotkey → ui.message(...)
│  └─ doc/en/readme.md
├─ docs/
│  ├─ plan.md              # the Asana investigation deliverable (committed)
│  └─ superpowers/         # local-only workflow docs (gitignored)
└─ .gitignore
```

What each piece is for:

- **`buildVars.py`** — the single file we're meant to edit when configuring
  the add-on. It declares `addon_info` (name `LIMA`, summary, description,
  version `0.1.0`, author, minimum NVDA version `2023.1.0`, last-tested NVDA
  version `2026.1.1`, license `GPL v2`) and `pythonSources`, the list of
  source files SCons should treat as the add-on's Python code (currently
  `addon/globalPlugins/lima/*.py`).
- **`manifest.ini.tpl`** — a template for the manifest that ships inside the
  final zip. SCons substitutes the values from `buildVars.py` into this
  template to produce the real `manifest.ini` (e.g. the template's `name`
  placeholder becomes the literal line `name = LIMA`). The rendered
  `manifest.ini` is a build artifact and is gitignored — we only commit the
  template.
- **`sconstruct`** (plus `site_scons/`) — the SCons build script and its
  supporting tooling (`site_scons/site_tools/NVDATool/`, `gettexttool/`).
  This is what actually drives the build: rendering the manifest, compiling
  translation files, generating documentation, and zipping everything into
  the final `.nvda-addon` artifact. We did not write this tooling — it comes
  from the official template — we only configure it via `buildVars.py`.
- **`addon/globalPlugins/lima/`** — the add-on's actual code, structured as a
  Python *package* (a directory with `__init__.py`) rather than a single
  flat module. This is a deliberate forward-looking choice: it costs nothing
  now and means that when later features (e.g. a `narration.py` module, or
  an `auth/` package for Firebase) are added, they simply drop into this
  package without any restructuring. Those modules are **not** created yet —
  this session is YAGNI by design.

## 3. How it's built

The project is scaffolded from the official, NV Access–maintained template:
**`nvaccess/AddonTemplate`**. Note for anyone searching for it: an older
template repository, `nvdaaddons/AddonTemplate`, was **archived on
2025-12-01** — links to it will look dead or stale. `nvaccess/AddonTemplate`
is the current, correct one to use.

The template's build system is **SCons** (a Python-based build tool, not
Make). NV Access recommends a build environment running **Python 3.13+**;
in practice, this project's build was carried out successfully on
**Python 3.12**, which also matches the Python version used in LIMA's own
CI, so 3.12 is an acceptable build environment here too.

The build flow is:

1. `scons` is invoked from the repository root.
2. It reads `buildVars.py` for the add-on's metadata and source file list.
3. It renders `manifest.ini` from `manifest.ini.tpl`, substituting in the
   values from `buildVars.py` (this is where `name = LIMA` ends up in the
   generated manifest).
4. It collects the Python sources and other add-on resources and zips them,
   together with the rendered manifest, into the final artifact.

For this scaffold, that produces **`LIMA-0.1.0.nvda-addon`**. Inside that
zip, the plugin code lives at `globalPlugins/lima/__init__.py` — i.e. the
`addon/` prefix from the source tree is stripped, and the package structure
underneath it is preserved.

## 4. How we test during development

Because the add-on's code imports NVDA-only modules (`globalPluginHandler`,
`ui`, `addonHandler`, `scriptHandler`), it cannot run or be exercised outside
of a real NVDA process — there is no way to unit-test "does the hotkey speak
the message" without NVDA itself. Testing therefore happens at two levels:

**Automated (what CI/the dev machine can check without NVDA installed):**
- `py_compile` over the plugin source, to catch syntax errors.
- `tests/test_package.py`, a packaged-artifact smoke test that: confirms a
  `.nvda-addon` file exists after a build, opens it as a zip and checks that
  `manifest.ini` and `globalPlugins/lima/__init__.py` are both present inside
  it, and asserts the manifest contains the line `name = LIMA`.

This automated layer can only prove the add-on *packages* correctly — it
cannot prove the add-on *behaves* correctly inside NVDA. The spoken response
to the hotkey must be verified manually, in a real NVDA install. The
concrete steps for that are below.

**Manual, fast inner loop — NVDA Developer Scratchpad:**
NVDA has a "Developer Scratchpad" directory specifically for iterating on
add-on code without packaging and reinstalling on every change. Enable it
under Settings → Advanced, drop the plugin's `globalPlugins/lima/` folder
into the scratchpad directory, and reload NVDA's plugins with
`NVDA+Ctrl+F3` after each edit — no rebuild or reinstall required. This is
the loop used while writing and debugging plugin code.

**Manual, packaged install — Add-on Store "Install from external source":**
Once `scons` has produced the `.nvda-addon` file, it can be installed the
same way an end user would install it, via NVDA's Add-on Store using
"Install from external source," to confirm the actual distributable artifact
works end-to-end (not just the scratchpad copy).

The exact, click-by-click steps for both of these are in
["Testing this scaffold in real NVDA"](#testing-this-scaffold-in-real-nvda)
below.

## 5. How and where we list/distribute

The distribution channel is the **NVDA Add-on Store**
(`addonstore.nvaccess.org`), which is NVDA's built-in, in-app catalog of
add-ons (reachable from NVDA's Tools menu). It currently lists 461 add-ons
and is backed by a public GitHub repository, **`nvaccess/addon-datastore`**,
which holds the metadata (not necessarily the code itself) for every listed
add-on.

Listing an add-on works like this:

- **Submission is a pull request** against `nvaccess/addon-datastore` that
  adds the new add-on's metadata (the PR does not need to include the add-on
  binary itself, just the metadata pointing to where it's hosted/its
  release).
- The PR author must be on an **approved-submitters list**. NV Access
  manually maintains this list (`submitters.json` in that repo); first-time
  submitters go through an approval process before their PR can be merged.
- Submitted files are **scanned by VirusTotal**. There is **no manual code
  review/audit** of the add-on's source by NV Access — the integrity
  guarantee instead comes from **SHA256 checksums**, which are recorded and
  enforced so that what a user downloads matches exactly what was submitted.
- The official submission guide lives at
  `docs/submitters/submissionGuide.md` inside the `addon-datastore` repo.
- Listing on the NVDA Add-on Store is **not exclusive** — the add-on can
  also be hosted and distributed elsewhere (e.g. our own GitHub releases or
  website) in parallel with the Store listing.

No submission work is in scope for this session; this section documents the
process for when the team is ready to list LIMA's add-on.

## 6. Prior art

Several LLM-powered assistants are already listed in the NVDA Add-on Store,
which is useful context for the eventual feature decision:

- **AIAssistant**
- **AIContentDescriber**
- **AIChatbot**
- **AISummarizer**

Of these, **AIContentDescriber** is the closest analog to the direction LIMA
is likely to take: it is essentially a screenshot-to-LLM-description
pipeline — the user triggers it, it captures the screen (or a region), sends
it to an LLM, and speaks back a description. That maps closely onto LIMA's
own Dynamic Video/Website Narration concept, so it's a good reference point
to look at (functionality, UX, gesture choices, settings) when the team and
the blind software tester scope LIMA's first real feature.

## 7. Open questions

These are tracked for the team and the blind software tester to weigh in
on — they are intentionally not resolved in this session:

- Which single feature is the MVP for the add-on (e.g. screen/video
  narration, or something else the tester prioritizes)?
- How does the funnel work — does the add-on call the LIMA backend directly,
  and what functionality is free versus paid?
- Where does Firebase auth sit in the add-on's flow, and at what point is
  the user prompted to sign in?
- Which NVDA version(s) should be officially supported? This determines the
  `minimumNVDAVersion` and `lastTestedNVDAVersion` values in `buildVars.py`
  (currently `2023.1.0` and `2026.1.1` respectively, as placeholders for this
  scaffold).

## Testing this scaffold in real NVDA

1. In NVDA: NVDA menu → Preferences → Settings → Advanced → tick
   "Enable loading custom code from Developer Scratchpad directory". Apply/OK.
2. Open the scratchpad folder: NVDA menu → Tools → "Open developer scratchpad directory".
3. Inside it, create `globalPlugins\lima\` and copy `__init__.py` there
   (or copy the whole `addon\globalPlugins\lima` folder in).
4. Reload plugins: press NVDA+Ctrl+F3.
5. Press NVDA+Shift+L. You should hear: "LIMA add-on is running".
6. To test the packaged build instead: NVDA menu → Tools → Add-on Store →
   "Install from external source", choose `LIMA-0.1.0.nvda-addon`, restart NVDA,
   then press NVDA+Shift+L.
