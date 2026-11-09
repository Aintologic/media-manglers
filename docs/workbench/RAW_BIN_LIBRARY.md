# Raw bin library

The **Raw bin** page lists every recording in your recordings folders: what the
app thinks is in it, how much of it is idle, what you decided to do with it,
and what it is for. It is a lasting library, not a one-off report: reopening
the page is instant, because it reads only the library, never your recordings.

The app only marks. It never writes, moves, renames or deletes anything on the
drive that holds your recordings.

## Your recordings folder

The library watches the same folders as Review Media Inbox: **Review Media
Inbox > Settings > Review source folders**. Set them once and both use them.

## Scanning

Press **Scan now**. The scan runs on Queue / Progress like every
other run, so **Pause**, **Skip** and **Cancel review** work there.

- A recording that has not changed since the last scan is not read at all.
- A new or changed recording is read once, front to back. Everything the
  library keeps about it comes from that one read. A recording that could not be
  read is tried again on the next scan.
- A recording still being written (changed in the last two minutes) waits for
  the next scan.
- Each recording is saved as soon as it is done. A power cut, a restart or a
  drive dropping off loses at most the recording in progress; the next scan
  carries on from there.
- If a recordings folder cannot be reached (the drive is unplugged), the scan
  stops and says so. Nothing is marked missing.
- The scan runs at low priority, so the PC stays usable. A first scan of a
  large USB drive takes many hours: run it overnight.

## The app's guess

| Guess | What it means |
| --- | --- |
| **Keep likely** | Your narration track has at least a minute of speech. The list shows the minutes of speech. |
| **Check** | Your narration track has under a minute of speech; or it is silent but another track has someone talking (the audio may be on the wrong track); or the app is not sure, or the file could not be read. The reason is shown when you select it. |
| **Probably nothing** | No speech on the narration track for the whole recording. |
| **Empty** | The file is almost empty or under two seconds long. |

The guess uses the same track choice as every other feature: track names,
**Settings > General > Narration track**, then voice detection. Voice detection
listens to a short sample of each track that has sound; it makes no
transcript.

**Flags** count your "flag for AI" requests, found with the same rules Find my
bug reports uses. They appear only once a recording has a transcript: select
recordings and press **Deep scan** to transcribe them. A Deep scan is
slow; the normal scan never transcribes.

## Idle time

**Idle** is the share of the recording where the game audio was quiet for at
least a minute: paused, in a menu, or away from the rig. The game-audio track
is found by its name (for example "Game"), then by **Game audio** in the
narration track setting (Track roles). When either says which track is the
game, that track is used and no other track is ever picked instead.

- When the recording has no such track, or it is silent the whole recording
  (an early recording with everything on Track 1, say), idle time is estimated
  from the full mix and Idle shows **(estimated)**. The full mix is the track
  named "Full Mix", the track set to **Full mix** in Track roles, a recording's
  only track, or the only track with any sound.
- Without a full mix to estimate from, Idle says **unknown**; select the
  recording to see why.
- With no track named or set as the game audio, the app guesses: the one track
  left that is neither your narration nor a full mix. A track whose name says
  music, spotter, engineer, Discord or voice chat is never that track (a track
  named "System" still can be, because desktop sound is often the game). When
  that leaves no track, idle time is estimated from the full mix, or is
  **unknown**, and the reason names the track.

Changing **Game audio** or **Full mix** in Track roles takes effect at the next
**Scan** without reading your recordings again: the library keeps every track's
sound levels in the cache and works the idle times out from those. (Changing
**Narration** or **Never narration** reaches a recording only when it is read
again, because the narration track is chosen by listening.) Clearing the cache
keeps the idle times you have. If you then change the game track, a recording
whose levels were cleared shows Idle **unknown** and says why.

## Your decisions and labels

The line under the list always describes the highlighted recording. After
**Scan now**, a **Deep scan**, coming back to the page, or a change of filter
or search, the same recording stays highlighted and in view. If it is no
longer listed, nothing is highlighted, the line under the list is empty, and
**Play** and the decision buttons are greyed out until you select one.

Select one or more recordings, then:

- **Keep**, **Delete candidate** or **Undecided**. A scan never changes these.
- **Labels**: Bug report, YouTube, Short, B-roll, Training, or **New label…**
  for your own. A recording can have any number.

Decisions and labels follow a recording if you rename it or move it to another
folder: the library knows a recording by its content, not its name. A moved
recording is read once to confirm it is the same, and keeps its guess; it is not
listened to again. Two copies
of the same recording are listed twice. A recording no longer in your folders
is kept with its tags and shown with **Show missing**.

A different recording saved under a file name the library already knows is a
new recording in the list: it starts Undecided, with no labels. The one that
was there before keeps its decision and labels and is shown with **Show
missing**, by the name it had, like any recording no longer in your folders. If
you put that recording back, it gets its place, decision and labels back.

The **Mined** column says which feature already mined a recording for tickets:

- **Inbox**: Review Media Inbox reviewed it.
- **Bugs**: Find my bug reports made a package from it, or from an identical
  copy of it (the same content, wherever it is).
- **Bugs: no narration**: Find my bug reports went through it and found no
  narration.
- **Bugs (old list)**: Find my bug reports' list from before the library kept
  it has this file's path, and the library could not prove it is the same
  recording. It is matched by its path, as that list was.
- **Inbox + Bugs** (and **Inbox + Bugs: no narration**, **Inbox + Bugs (old
  list)**): both.

A different recording saved under a mined recording's file name is not shown as
mined, except by an old-list entry, which only ever knew the path. What Find my
bug reports did is personal: it is never in the export below.

The app never deletes a recording. **Delete candidate** is a mark for you.

## Play

**Play** (or double-click) opens the recording in the built-in player at its
first speech, on your narration track. **Next speech** and **Previous speech**
jump between the stretches where you talk (for a recording without narration,
between the active stretches). The first time you open a recording the player
measures it once more in the background, and then the jumps get finer. The player shows the waveform of every audio
track straight away, from the levels this scan kept; see
[Waveforms of every track](REVIEW_PLAYER.md#waveforms-of-every-track).

## Export

**Export view…** saves the recordings shown now, with their guesses, decisions
and labels, as a CSV file (opens in a spreadsheet) or a JSON file. An export is
never written to the recordings drive.

## Where the library lives

The library is one database in the app's local data folder on this PC, with a
dated backup copy each day the app is used. Waveforms and other data that can be
rebuilt go in the cache folder (**Settings > General > Cache folder**, with a
size cap and **Clear cache**). A folder you choose gets a **Media Manglers cache**
folder inside it, and only that folder is ever cleared. Clearing the cache never loses a guess, a
decision or a label.

The same database also keeps every run the Workbench makes, for History (243). The first time a
new version opens it, it copies the whole library into **backups\migrations** before it changes
anything; those copies are never pruned. When it moves your run history out of settings.json, it
copies settings.json there too, with **HOW_TO_RESTORE.txt** saying how to put both back.

[Back to Help](README.md)
