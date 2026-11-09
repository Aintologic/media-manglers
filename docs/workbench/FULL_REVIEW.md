# Full Review

1. Choose **1 Full Review** on Home.
2. In **Source**, choose a local file/folder, or choose URL and paste one or
   more supported web-video URLs with one complete URL per line.
3. Keep **Recommended settings** or choose an optional plain-language preset,
   then choose an output folder.
4. On **Review and run**, resolve any named dependency blocker.
5. Choose the green **Start review** action.

**Expected:** URLs are processed sequentially in pasted order. Duplicate lines
are removed automatically, and a failure identifies the affected URL while
preserving other completed items.

The output root and every per-video folder include `README_FOR_AI.md` and
`AI_PACKAGE_MANIFEST.json`. These are the agent-neutral starting points for
Claude Code, Codex, or another file-capable AI. Their links are package-relative,
so the complete output folder can be moved to another folder or drive.

> **Warning:** URL input belongs only to Full Review. Other workflows require
> local sources.

**Which track is transcribed.** On Auto, Full Review finds your voice the same
way every feature does, reading track names and the main **Narration track**
setting (Settings > General). In **Advanced settings**, **Transcript audio
mode** says **Using main setting** while it is Auto with no track forced, and
**Overridden** once you choose a track there.

[Previous: Getting started](GETTING_STARTED.md) · [Back to Help](README.md) · [Next: Transcript Only](TRANSCRIPT_ONLY.md)
