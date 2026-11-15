# The built-in player

Watch a recording inside the Workbench instead of in another program. The
**Built-in player** plays the video, lets you choose which audio track you
hear, and shows the transcript line for the spot you are hearing, including
the lines that were left out of your package and why. When a recording is not
worth keeping, one button marks it never-use and moves you on to the next one.

Your recordings are only read. The player never changes, moves or uploads a
recording, and nothing is written next to it.

## Play a video from anywhere

Most lists that show a recording, or a moment inside one, can play it.

- **Double-click** it. This works in every list that shows a recording: both
  lists in **Find my bug reports** (before and during a run), **Queue /
  Progress**, **History**, **Recent runs** on **Home**, the source list in
  **New Review**, and the evidence moments in **Evidence** and **Session
  Review**. In **History** and **Recent runs**, a run of several recordings
  asks which one to play. A run with nothing to play (a web address, or
  configured folders) opens its output folder, as double-click did before;
  for any run, right-click offers **Open output folder** and **Open log**.
- **Right-click** it and choose **Play**. For a moment inside a recording the
  entry reads **Play this moment**, and the video opens at that moment.
- **Right-click > Play with** offers the **Built-in player**, **VLC** or your
  **Default video app** for this one time, whatever your usual choice is.
  **Show in folder** opens the folder that holds the recording.
- Use the visible buttons where there is one: **Play recording** on
  **History**, **Play this moment** on the **Evidence** and **Session Review**
  pages, and **Watch a recording…** on the **Find my bug reports** results
  screen, which lists that run's recordings. Opened from there, the built-in
  player is pointed at the package the run made, so it can show the
  transcript.

There is one player window. Playing another recording reuses it, and asking
for a moment in the recording that is already open simply jumps there. The
window title is the file name followed by **Built-in player**. The window
remembers where you left it on this PC, unless you turned off **Restore last
window size/position** in Settings.

## Choose your player

**Settings > Video player** holds both settings below.

### Play videos with

There are three choices.

| Choice | What you get |
| --- | --- |
| **Built-in player** | Everything on this page. The Workbench starts with this choice. |
| **VLC** | Plain playback in VLC, which you install yourself. It can open at a moment. |
| **Default video app** | Plain playback in whatever app your PC normally opens videos with. It always starts from the beginning, because the Workbench cannot tell another app to jump to a moment. |

In this release, only the built-in player gives you:

- the transcript line at the moment you hear it, including left-out lines and
  the reason each one was left out;
- **Hear: Track N** with the track the app took as your voice pointed out;
- a waveform of every audio track, and **Next sound** / **Previous sound** to
  jump between the sounds on the track you hear;
- the moments the package found, marked on the timeline, with **Next moment**
  / **Previous moment**;
- **Never use this recording** without going back to the list.

VLC and your default video app play the recording their own way, in their own
window. The Workbench adds nothing to them.

When your choice is **Default video app** and you right-click a moment, the
first entry reads **Play from the start (your default video app can't jump to
a moment)**, and a second entry, **Open this moment in the built-in player**,
takes you to the moment itself.

### Start playing straight away

This is ticked to begin with, so a recording starts playing as soon as it
opens. Untick it and a recording opens paused, showing its first picture, or
the picture at the moment you asked for, and waits for you to press Space. VLC
follows the same choice. Your default video app decides for itself.

Applying a profile never changes how videos open, where VLC is, or where the
player window sits. See [Settings and migration](SETTINGS_MIGRATION.md).

## Moving around

The bar under the video is a timeline of the whole recording, labelled in
hours, minutes and seconds. Click anywhere on it to jump there, or drag along
it to look for a spot. A playing video pauses while you drag and carries on
when you let go. Small marks show where the transcript lines are: blue for
kept lines, amber for left-out lines. Just under them sit the
[moments the package found](#moments-the-package-found).

## Keys

| Key | What it does |
| --- | --- |
| Space | Play or pause |
| Left / Right | Back or forward 5 seconds. Hold the key to keep moving. |
| Up / Down | Previous line / Next line |
| Ctrl+Left / Ctrl+Right | Previous sound / Next sound, on the track you hear |
| [ / ] | Previous moment / Next moment |
| Page Up / Page Down | Previous speech / Next speech, once the app knows where you spoke |
| W | Show or hide the waveforms |
| , (comma) / . (period) | Step back / step forward, a small step for landing on the exact spot |

The main keys are always shown along the bottom of the window, and every
button that has a key ends its tooltip with it.

## Choosing which track you hear

A recording often carries several audio tracks: the game, your microphone,
voice chat and so on. **Hear: Track N**, in the row under the playback buttons
beside **Speed** (1x / 2x / 4x) and **Volume**, picks the one you hear. Tracks
are counted from 1. The change takes effect straight away and the video keeps
its place. A recording with only one audio track has nothing to choose, so the
list is greyed out.

**Volume** changes only the built-in player, and it is remembered for next
time.

When you open a recording from **Find my bug reports**, the track a run took
as your voice, or the one you forced with **Always use Track N**, ends with
**your voice**.

The player starts on the track its transcript was made from, so you hear what
the transcriber heard. A page can ask for a track instead: the raw bin library
opens a recording on your narration track. Once you pick a track yourself, the
player keeps your choice. When the package says which track the app took as
your voice, the transcript panel shows that explanation with **Hear this
track** beside it, to go back to that track after listening to another.

## Waveforms of every track

Under the picture, every audio track has a lane of its own (up to eight),
showing how loud it is across the whole recording. Each lane is named with its
track number and what the track is, from the track's own name or from **Track
roles**, for example `2 Narration · your voice` or `3 Game audio`. The track you
hear is drawn brighter.

- Click a lane to go to that point in the recording.
- Click a lane's name to hear that track. It is the same as choosing it in
  **Hear: Track N**.
- **Waveforms** in the row of playback buttons, or W, shows or hides the lanes
  at any time, even while playing. It never pauses, moves or changes the track
  you hear. Hiding them gives the room back to the picture. The player
  remembers your choice.

The first time a recording is opened, its sound is measured: the lanes fill in
from left to right and say how far it has got, for example
`Measuring the sound of every track: 40% (about 2 minutes left).` You can
watch and move around while it measures. It is measured once and kept in the
cache folder (**Settings > General > Cache folder**), so the next time the
lanes appear at once. A recording the raw bin library has scanned has its
waveforms already.

- Measuring pauses for a moment whenever you drag or jump, so the picture
  comes first.
- It never runs while a review is running. The lanes then say
  `The sound is measured once the run has finished.` and it carries on
  afterwards from where it stopped.
- `This recording is still being written; its sound is measured once it is finished.`
  The file changed in the last two minutes, so it may still be recording.
- `This recording has no sound to show.` The file has no audio track.
- `The sound of this recording could not be measured.` The file could not be
  read. The video still plays.
- `No Next speech yet: it needs the Whisper model base.en. Approve its download in Settings > Dependencies.`
  The waveforms are there, but finding where speech starts needs that model,
  and a background job never downloads one. Once you approve it and it has
  downloaded, the recording is listened to by itself, with no restart.

Right-click the lanes and choose **Measure the sound again** to measure the
whole recording again from the start. For a recording the raw bin library has
scanned, the entry is greyed out, and its tooltip says why:
`These waveforms come from the Raw bin's scan of this recording. The Raw bin measures them again by itself when the recording changes.`

After **Find my bug reports**, **Full Review**, **Transcript Only**, **AI /
Ticket Evidence** or a Review Media Inbox run finishes, the waveforms of its
recordings are measured in the background, one at a time, at low priority, so
they are ready before you open the player. This is not a run: it is not on
**Queue / Progress** or in **History**. Starting a run, or closing the
Workbench, stops it at once and keeps what was measured; it carries on later.

### Next sound and Previous sound

**Next sound** (Ctrl+Right) goes to the start of the next sound on the track
you hear, and **Previous sound** (Ctrl+Left) to the start of the one before.
A sound is a stretch clearly louder than that track's own quiet background;
sounds less than 2 seconds apart count as one. They work in the part measured
so far, and while the lanes are hidden. Hear another track, and they follow
that track.

Next sound finds sound, not speech. On a microphone track that also picks up a
steady background, such as the game or a fan, quiet talking can be no louder
than that background, so Next sound may land a few seconds before or after the
words, or pass over them. To go from one thing you said to the next, use
**Next line** (Down) when the recording has a transcript, or **Next speech**
(Page Down) when it came with its stretches.

## Moments the package found

When the recording has been through a review that made a package, the timeline
marks what the package found in it, in the words **Session Review** uses:

- the requests for a bug report, in a strong colour: `ticket mention`,
  `review needed` and `explicit marker`. A marker that a ticket mention already
  covers is left out, because it is the same request said twice;
- the moments `you were talking`, in a pale colour.

Hover over a mark to see what it is, its time and a few of its words. A short
line under a mark means several moments sit there; hovering lists them all.
Click a mark to go to it. **Next moment** (]) and **Previous moment** ([) visit
each one in turn; they appear only when the recording has moments.

## Jumping between stretches

A recording opened from the [raw bin library](RAW_BIN_LIBRARY.md), from the
Review Media Inbox track choice, or from **Preview track** in **New Review**
comes with the stretches where you talk (or, without narration, where you were
driving). **Next speech** (Page Down) and **Previous speech** (Page Up) jump
between them.

Any other recording gets the same two buttons once the app knows where you
spoke. It measures that in the background, with the waveforms, only for the
recording you open and the recordings a run just used, and the buttons appear
without reopening. It never runs during a run, and a run or closing the app
stops it; it carries on from where it was. Each jump lands half a second before
the speech, and it never changes the track you hear. If the app could not tell
which track is your voice, or heard no narration, the waveform area says so.

If you chose a track for this recording and the app heard your voice on another,
the player says so in one calm line. Your choice is used.

**Preview track** in **New Review** opens the built-in player on the track you
chose, at the **Preview region** you chose, and plays it straight away, so you
can hear whether it is your microphone. It always uses the built-in player,
whatever **Play videos with** says, like the Review Media Inbox track choice.

## The transcript panel

If the recording has been through **Find my bug reports**, or another review
that made a package, the panel shows what was transcribed at the spot you are
hearing. While the player looks for that package it says
`Looking for a transcript…`. It looks in the package the list named, the
package you have open or opened last on **Evidence**, and the output folders
of your most recent runs. When it finds one, the panel names the run folder it
came from.

- A **kept line** is a line that went into your package.
- A **left-out line** is something the transcriber wrote that the transcript
  filter then left out. It is shown at the moment it was heard, together with
  the reason, so you can check that nothing you really said was thrown away.
- Between lines the panel says `Nothing transcribed here. Next line at H:MM:SS.`

A package is matched to a recording by where the recording was when the
package was made, or by its file name if it has moved since. When the package
says how long the recording was, a file of another length is turned away, so a
recording that was recorded over does not get the old one's transcript. When
nothing matches, or two recordings in the package share that file name, the
player shows no transcript rather than guess.

### What each "Left out" reason means

| The panel says | What it means |
| --- | --- |
| `Left out: a stock phrase the transcriber tends to invent over silence or engine noise, like "thanks for watching".` | The line was one of a short list of phrases that transcribers make up when nobody is talking. |
| `Left out: there were no words in it.` | The transcriber produced only punctuation or symbols, so there was nothing to keep. |
| `Left out: the transcriber was repeating itself here, which usually means it was making text up.` | The text looped over the same words again and again. |
| `Left out: the transcriber was not confident anyone was speaking here.` | The transcriber's own scores said this was probably not speech. |
| `This whole stretch (H:MM:SS–H:MM:SS) was thrown out: the transcriber kept repeating itself even on a second try.` | A whole stretch was tried twice and thrown out both times. It is shown as one span, with the text the transcriber had written for it. |
| `Left out — reason recorded as "…".` | The package recorded a reason the player has no plain words for, so it shows the recorded reason as it is. |

When a stretch was transcribed twice, only the attempt that was used is shown.

### Other things the panel tells you

- `No filtering ran for this recording — it was transcribed in <mode> mode.`
  The transcript filter runs only in Sparse mode. This is not the same as
  "nothing was left out": no line was checked, so none could be left out.
- `This package does not say whether any filtering ran.` The package does not
  name the mode it was transcribed in, so the player cannot tell you either
  way.
- `This package was made before left-out lines were recorded.` Older packages
  hold the kept lines only.
- `No transcript found for this recording. Run Find my bug reports on it to get one.`
  The video still plays.
- A kept line can carry the mark `Kept — it sits next to real speech`. The
  transcriber was unsure of the line, and on its own it would have been left
  out; it was kept only because of the real speech beside it. Give these a
  second look.
- `This package does not say which lines were kept only for sitting next to real speech.`
  Older packages did not record it, so there the mark never appears.
- A kept line that is mostly spotter call-outs, the game's spotter or race
  engineer rather than you, is marked `Sounds like the spotter, not you`.
- **Show the numbers** adds up to three plain lines with the transcriber's own
  scores for the line. These are the figures the transcript filter works from.
  Leave it off unless you are curious.
  - `Chance nobody was speaking:` a percentage.
  - `How sure it was of the words:` high, medium or low, with the
    transcriber's own figure beside it. The closer that figure is to 0, the
    surer it was.
  - `How much it repeated itself:` a figure; above 2.4 means it was looping.

  When your glossary corrected the line, the transcriber's own wording follows
  as `Before your glossary: …`. When the package holds none of this for a
  line, the player says `This package recorded no numbers for this line.`

### Previous line and Next line

| Button | Key | What it does |
| --- | --- | --- |
| **Previous line** | Up | More than a second into a line, it goes back to the start of that line. Otherwise it goes to the line before, so two quick presses keep going back. |
| **Next line** | Down | Goes to the start of the next line. |

The filter beside them, **All lines** / **Kept only** / **Left out only**,
chooses which lines the panel shows, which marks the timeline shows and which
lines the two buttons stop at. **Left out only** is the quick way to check
everything the filter removed.

## This recording

The row at the bottom says where the recording stands: `Ready`,
`Done on <date>` when **Find my bug reports** has already been through it, or
`On your never-use list`.

### Never use this recording

Press it when a recording should not be offered to you again. The player:

1. stops playing at once;
2. adds the recording to your never-use list, the same list **Find my bug
   reports** uses, and saves it;
3. opens the next recording from the list you opened the player from, passing
   over any that are already on the never-use list.

A banner then says `You marked "<file name>" never-use.` with **Undo**.
**Undo** allows the recording again and reopens it, paused, where it was
stopped.

When there is nothing next, the player says so:

- `Marked never-use. There is nothing next — this recording was opened on its own.`
  You opened one recording or one moment, so there is no list to move along.
- `Marked never-use. That was the last recording in this list.` The player
  does not start again from the top.

**Undo** is offered in all three cases.

If the list could not be saved, the player says `Could not save that — try again`
and stays on the recording.

While a recording that is on your never-use list is open, the button reads
**Allow again**. Press it to take the recording off the list.

The recording itself is never changed or deleted. In **Find my bug reports**
it also leaves your chosen recordings, unless a run is going: never-use is
about future runs, so a run in progress keeps its list, and the recording
leaves the list when that run ends. To leave it out of the run that is going
now, use **Skip this recording**.

To take a recording off the list later, open **Never-use list…** in **Find my
bug reports**, select it and press **Allow again**. You can double-click a
recording in that list to watch it first. **Allow again** only takes it off
the list. Add it to your chosen recordings yourself if you want it in the next
run.

### A clip or a small review copy is not a recording

A clip, or the small review copy of a session, that you open from inside a
package is a file the Workbench made, not one of your recordings. The player
still plays it, and says what is different:

- The row at the bottom reads `A clip or a small copy from a package`.
  **Never use this recording** is greyed out, and its tooltip says why:
  `This is a clip or a small copy made for a package, not one of your recordings, so it cannot be marked never-use.`
  **Skip this recording** is not offered.
- The transcript panel says
  `This is a clip or a small copy from a package, so there is no transcript to show for it.`
- No waveforms are shown, and there is no **Next sound**: its one track is not
  the recording's tracks. **Waveforms** is greyed out, and W says why:
  `No waveforms for a clip from a package. Open the recording itself to see every track.`

The one exception is the small review copy played in place of a recording that
could not be found (see
[The recording is not where it was](#the-recording-is-not-where-it-was)).
The player then says `Playing the small review copy of <file name>.`, and
everything else stays about the recording: the window title names it, the
transcript and the moments are the recording's, and **Never use this
recording** and **Skip this recording** mark the recording itself, not the
copy. It shows no waveforms either, for the same reason as a clip, and W says
`No waveforms for a small review copy. Open the recording itself to see every track.`

### Skip this recording

This button appears only while a run is going. It skips the recording in that
run, and nothing from it goes into the package. Its tooltip says it plainly:
`Skips it in the run that is going now. This cannot be taken back for this run.`
The player answers `This recording will be skipped in the run that is going now.`
and greys the button out for that recording. When the recording had already
been skipped, or the run could not take the request, it says
`This recording is not waiting in the run that is going now.` instead.
Skipping is not never-use: the recording is offered again next time.

## When something is in the way

### The recording is not where it was

If a recording has been moved or renamed, or its drive is not connected, the
Workbench tells you instead of opening a folder:
`"<file name>" is not where it was. It may have been moved or renamed, or its drive is not connected.`

- **Find it…** lets you point to where the recording is now. That is
  remembered until you close the Workbench.
- **Play the small review copy instead** appears when the list you opened the
  recording from names its package, and that package holds its small review
  video of the session. It is enough to hear what was said and see what was on
  screen.

### VLC was not found

When **Play videos with** is set to **VLC** and the Workbench cannot find VLC,
the video opens in the built-in player instead, without asking, and the player
says so:
`VLC was not found, so this opened in the built-in player. To use VLC, go to Settings > Video player and press Find VLC…`
**Settings > Video player** tells you the same:
`VLC was not found on this computer. Videos open in the built-in player until you install VLC or press Find VLC.`

When you ask for VLC yourself, with **Right-click > Play with > VLC**, the
Workbench asks what to do instead:
`VLC was not found on this computer. Point to it with Find VLC…, or play this video in the built-in player.`
Choose **Find VLC…** to point to `vlc.exe`, **Play here instead** to use the
built-in player this time, or **Cancel**. The place you point to is remembered
on this PC.

If VLC is found but does not start, the Workbench asks the same way:
`VLC could not be started. Point to it again with Find VLC…, or play this video in the built-in player.`

### A file the built-in player cannot play

The player shows `The built-in player can't play this file.` with **Open in
VLC** and **Open in the default video app**, so you can still watch it.

If VLC cannot be found from there, the Workbench offers **Find VLC…** only:
`VLC was not found on this computer. Press Find VLC… to point to it.`
It does not offer the built-in player, which is the player that has just said
it cannot play the file.

### The player stopped when you closed the Workbench

Closing the Workbench stops the built-in player first, so that no recording is
held open. If the Workbench then stays open, because you chose not to cancel a
run that was still going, say, the player says
`Stopped. Press Play to carry on from <time>.` Press **Play**, or Space, and
the recording opens again where it was. If the player had not found a
transcript yet, the panel says
`The transcript will be looked for again when you press Play.`

If the Workbench will not close and the player comes to the front saying
`The built-in player is still finishing. Close the Workbench again in a moment.`,
the player was still looking for a recording or its transcript on a slow disk.
Wait a few seconds and close the Workbench again.

See also [Troubleshooting](TROUBLESHOOTING.md#the-built-in-player-has-no-sound)
for a player with no sound.

[Find my bug reports](FIND_BUG_REPORTS.md) · [Back to Help](README.md)
