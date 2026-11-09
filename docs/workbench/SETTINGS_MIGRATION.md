# Settings and migration

- Use **Export settings** for a portable, privacy-safe copy by default.
- Include this-PC paths only when the destination is the same trusted machine.
- Import reports what was applied, skipped, unresolved, incompatible, or
  ignored for safety.
- Built-in profiles migrate safely and remain protected from overwrite/delete.
- Settings schema 6 replaces the old profile-driven startup with **Full Review**
  and **Recommended settings**. Existing presets remain available as optional
  choices, and machine-local tool paths continue to be preserved.
- Review Media Inbox defaults each clean launch and completed run to **Next 3**.
  **All pending** is never restored as the default. Fast remains the default,
  and Full confirmation is never saved.
- Review Media Inbox source, evidence, scratch, ledger, and exact audio-layout
  values remain machine-local and follow the existing portable-export safety
  rules.
- Your **Never-use list**, the record of recordings already done by Find my
  bug reports and a stopped run waiting for **Continue** stay on this PC. They
  are never exported, not even with this-PC paths included, never imported, and
  never copied into a saved profile.
- Since the bug-report lists moved into the library (244), settings.json no
  longer holds them. The first start of this version moves them in once, after
  copying settings.json, your own profiles and the library into
  `backups\migrations` beside the library, with a `HOW_TO_RESTORE.txt`. It also
  takes a stopped run, or an old copy of the lists, out of your own profiles.
  A profile that cannot be written at that moment is cleaned at a later start,
  after a backup of that profile alone (none when the same file is already
  backed up). Built-in profiles are not touched. Recordings on the old lists are treated
  exactly as before; an old "done" entry the library cannot tie to the
  recording now at that path keeps working by its path.
- **Narration track, for recordings without track names** (General / Startup)
  is new and starts with every track on **Auto**, so existing settings files
  find the voice automatically, as before. Like the audio-track choices, it belongs to
  your own recording layout: applying a profile never changes it.
- Settings schema 7 moves the Advanced *Profile transcription glossary* to
  **Words to spell right** (General / Startup). What you saved is kept, and
  *iRacing*, *SimHub* and *Crew Chief* are added once if they are missing; a
  word you remove afterwards stays removed. Like the narration track setting,
  applying a profile never changes it.
- Applying a profile never changes how videos open (**Play videos with** and
  **Start playing straight away**), where VLC is, or where the built-in
  player's window sits. The VLC location is a this-PC path like the other tool
  paths, and the window position always stays on this PC.
- Portable imports never create missing local folders or silently replace a
  working path with an inaccessible one. Review the import summary before using
  optional this-PC values on another computer.
- **Advanced / Diagnostics**, **Debug details**, and Build information keep
  technical identity available without exposing it on normal screens.

## Where Media Manglers keeps your files

Media Manglers uses the folders Windows provides for each kind of file, like
any other desktop app:

| What | Where |
|---|---|
| Your results (packages, transcripts, edited videos) | A *Media Mangler* folder inside your own **Videos** folder, unless you choose another. Audio Mangler uses your **Music** folder. If you moved Videos or Music to OneDrive or another drive, Media Manglers follows it. |
| Settings, profiles and privacy masks | `%APPDATA%\MediaManglers` (your account's application data) |
| Logs | `%LOCALAPPDATA%\MediaManglers` (this PC only) |
| Short-lived scratch files | The Windows temp folder, removed when the job finishes |

Results are never kept in a temp folder. If the output folder is the Windows
temp folder, or any folder inside a folder named *Temp* or *Tmp* (for example
`C:\TEMP`), the run does not start and says why: those folders can be emptied
without warning, by Windows or by a clean-up tool. Choose a folder you keep.
Nothing you already have is moved: if a saved setting points at a temp folder,
pick a new folder and move any old results yourself.

[Previous: Progress and results](PROGRESS_RESULTS.md) · [Back to Help](README.md) · [Next: Troubleshooting](TROUBLESHOOTING.md)
