# AI Video Editor

Turn a long narrated race recording into a short video that tells the story of
the race: the set-up, the battles, the mistakes, the finish. Media Manglers
watches the race on your PC. Your AI agent (Claude Code or Codex) decides the
story and makes the edit. You watch each version and say, in plain words, what
should change. Nothing is uploaded or published, and your recording is only
read, never changed.

Open it with **AI Editor** in the left rail, or **Start** on its card on
Home.

## The start view

- **Make a video from a recording** is the way in: it opens **Choose a
  recording** (below).
- **Continue:** with a video's name opens the video you worked on last, and
  says where it is (*Version 2 is ready to watch*).
- **Your videos** shows each video as a card: a picture from its newest
  version, its name, the title of its story, a status and how many versions it
  has. The status is one of **Ready to watch**, **Waiting for your AI agent**,
  **Exported**, **Getting ready…** (with how far Prepare has got), **Not
  prepared yet** or **Needs a preview**. Click a card to open the video.
- The pictures come from what the app rendered (with your privacy masks
  applied), never from the recording itself, and are kept in the app's cache
  folder.
- The page notices new versions by itself every few seconds while it is shown;
  **Refresh** beside *Your videos* (and under a video's **Files** button) looks
  at once.
- **Editor settings** opens **Settings › AI Video Editor**.

## 1. Prepare a recording

1. Press **Make a video from a recording**. **Choose a recording** lists the
   recordings the **Raw bin** has looked at, newest first, with what the app
   already knows about each: the Raw bin's guess (*Keep likely*, *Check*…), the
   minutes of your speech and the idle time, your decision and labels, whether
   the **Inbox** reviewed it, and a video already made from it with its story's
   title. A recording with several videos says how many (*AI Video Editor: 3
   edits*), and a recording you renamed or moved still shows its videos once
   they are linked (see *Linking older videos* below). Pick one and press
   **Choose this recording**, or press **Browse for another file…** for the
   Windows file picker. When the Raw bin knows no recordings, the file picker
   opens straight away.
2. The video opens on its first step, **Prepare for the AI editor**. Check the
   two tracks. **Your voice** is the track with your microphone, and **Game
   sound** is the track with the game. They are numbered the way VLC numbers
   them (Track 1 is the first).
   - Both boxes start on **Auto**. Auto picks the tracks the way the rest of
     the app does: from the track names, then your **Narration track** setting
     (**Settings > General / Startup**). Under each box the page says what
     Auto picks, for example *Auto: Track 2, narration, from your Narration
     track setting*, and **Using main setting**. When only Prepare can tell
     (it listens for your voice, or takes the one track left with sound as the
     game), it says *Auto: decided during Prepare*.
   - When no track is named or set as the game, Auto never guesses a track
     whose name says music, spotter, engineer, Discord or voice chat.
   - Pick a track to use it for this recording only: the box shows
     **Overridden**, and **Reset to Auto** goes back. A track you picked is
     kept: when you choose the recording again, its box starts on that track.
   - When your Narration track setting names a game track, a track it sets
     as Never narration (it may be music) cannot be picked as the game sound:
     the page says so and refuses to prepare until you choose the game track
     or change the setting.
   - If the video already has versions and the tracks would change, a warning
     appears under the boxes first: versions made on the old tracks can no
     longer be rendered or exported. Press **Prepare for the AI editor** again
     to go ahead.
3. Choose an **AI budget**. Under the box the page says what it changes, from
   what the app really does with it. The closer looks and the checks are for
   the whole video, all its versions together; after that the app refuses
   more unless the agent asks you first.
   - **Light**: a picture of the race every 15 seconds (never more than 216),
     4 closer looks, the agent checks its versions once; the prompt asks for
     Claude Code's *high* effort (Codex: *medium*).
   - **Standard**: every 10 seconds (never more than 432), 10 closer looks, two
     checks; *xhigh* (Codex: *high*).
   - **Thorough**: every 5 seconds (never more than 864), 25 closer looks,
     three checks; *ultracode* (Codex: *xhigh*).

   More pictures and rounds let the agent see more of the race and fix more
   of its versions, but take longer and use more of your AI plan. The box
   shows the budget a video was prepared with; the budget a new video starts
   with is **Settings › AI Video Editor**, and preparing a video again does not
   change it.
4. Draw your **Privacy masks…** first if you have not (see below).
5. Press **Prepare for the AI editor**. A long race takes a while: for a race of
   about an hour, allow 15 to 20 minutes. A banner on the page shows how far it
   has got, and **Open in Queue / Progress** opens the job there; it is listed
   in **History** like any other run. Media Manglers:
   - for a new video, first makes sure which recording this is, by its content.
     When the **Raw bin** has already read the file, this costs nothing. When it
     has not, Prepare starts with one more step, **Confirming which recording
     this is**, which reads the file once (about as long as the reading step
     below), before anything is written. From then on, the video accepts only
     this recording: the AI agent naming another file, even one with the same
     name, is refused with a plain reason;
   - reads the recording once, front to back, for the sound of every track and
     the game picture (if the game picture cannot be read in that pass, the
     sound is read again on its own);
   - writes down what you said with your own Whisper model, graphics card and
     language, and your **Words to spell right**, so your names come out
     spelled your way;
   - leaves out lines Whisper made up, with the same filters as the rest of the
     app: lines another track carries, and lines Whisper wrote while your
     microphone was almost silent, are dropped. Short real reactions are kept:
     a loud burst of up to three words, within 15 seconds of something else you
     said;
   - listens to the game sound for other people's voices (the spotter, race
     control, other drivers on voice chat). A line it is not sure is a voice is
     left out of that list and kept in the project with the reason;
   - finds the **dead time**: a minute or more where nobody is driving (the
     game picture stands still or goes black, the game sound is quiet, or both).
     A replay or a moving menu looks like driving, so dead time there is not
     found;
   - looks through the whole race and takes the pictures the AI editor sees.

   The AI editor reads a digest of all this. Its **Dead time** section lists
   each stretch and what found it, and the AI editor is told to cut dead time
   unless it serves the story. If you have drawn no privacy masks, the video
   warns you under its status line (over its steps and over its player alike),
   and the digest says so too. If the voice or game track it used is silent for
   the whole recording (an older recording whose tracks are laid out
   differently, say), Prepare still uses it and warns you there too, and at the
   top of the digest: check your Narration track setting, or pick the right
   track and prepare again. A Prepare that finishes while you look at another
   video leaves that video on screen and says which video is ready.

   Your voice, the game sound and the camera layout are fixed when you
   prepare. An edit can use only those two tracks, so a music, spotter or
   full-mix track never reaches a video. Preparing again redoes only what
   changed. When nothing changed and both tracks are known without listening
   (picked by you, or given by their names or your Narration track setting),
   it does not read the recording at all. The transcript, for example, is
   written again only after you change your Whisper settings, your words to
   spell right, or the tracks.

Once the video is prepared, its tracks and budget are under its **Video
settings** button (**Your voice**, **Game sound**, **AI budget**), which open
this step again with **← Back to the player**.

## The video's toolbar

Under the video's name are its versions, as tabs, and a row of labelled
buttons. Each opens a small panel of choices under it; click the button again,
or anywhere else, to close it. Nothing is hidden in a menu of its own.

- **Video settings**: **Your voice**, **Game sound**, **AI budget**,
  **Privacy masks…**
- **Prompt**: **Copy prompt for Claude Code**, **Copy prompt for Codex**,
  **See the prompt first**, **Start a fresh edit**
- **Story & review**: **The story**, **The editor's own review**
- **Files**: **This version's files**, **Render a preview**, **Export
  quality**, **Open project folder**, **Open export folder**, **Refresh**. For a
  version with a final as well as a preview, Files also has both play choices,
  so the other one is a click away while one plays.

A choice that cannot be used yet stays in sight, greyed out, and its tooltip
says why (for example *Prepare the recording for the AI editor first*). What a
choice did is said beside the toolbar, for example *Copied. Paste it into
Codex.* **Approve and export…** stays at the top right.

## 2. Hand it to your AI agent

Until your AI agent has made a version, the player's place says *Your AI agent
hasn't made a version yet* and offers the one next step: **Prepare for the AI
editor…** for a recording not prepared yet, or **Copy prompt for Claude Code**
once it is, with a sentence on what happens after. Press **Copy prompt for
Claude Code** (or **Prompt › Copy prompt for Codex**) and paste it into your
agent. The prompt says which model, effort and mode to use.

**See the prompt first** shows the prompt before you copy it, with a short
introduction above it that is not part of the prompt. You can change the words
before you press **Copy this prompt**; your changes are used for that copy
only. **Put back the app's prompt** undoes them.

What to expect: the agent first tells you, in plain words, the story it plans
to tell and whether it will wait for your changes before it cuts. It then makes
version 1, watches it as a viewer would and fixes what it can, saying what it
is doing in plain words. It ends with what the video is now and the next steps
in the app, in the app's own words. Its technical detail goes in a separate
technical report. If something you asked for conflicts with its instructions,
it says so before it cuts.

Every version is made, rendered and exported from the video's own recording:
the file you chose when you made the video. A version that names another file
is refused, even one with the same file name in another folder, and your agent
is told which file to use. An exact copy of the recording (the same content,
checked byte for byte) is accepted, and the version still uses the video's own
recording. If that recording is no longer where the video expects it, put it
back there: the app cannot check that a file somewhere else is the same one.

## 3. Watch and say what to change

- The video's versions are tabs at the top, newest chosen (*v002 · newest*);
  the line beside them names the AI editor that made the chosen one.
- The chosen version's picture fills the player's place, as big as the window
  allows at its own shape, with the play choices on it. A version with a final
  or an export offers **Play the final (full quality)**, with **Play the preview
  (quick, smaller)** beside it; a version with only a preview offers **Play the
  preview**. Under them a line says what the version has, for example *v002 ·
  4:12 · final 1920×1080 · preview 1280×720*.
- Pressing a play choice plays it at once, on the page, in the app's built-in
  player (the same one every feature uses; it goes back to being its own window
  when you leave the page). The line under the player says what is playing, for
  example *Playing the preview of v002 (1280×720, 30 fps): a quick, smaller
  render to judge the edit*, and what the version has: *Preview ✓ · Final — ·
  Export —*.
- **Files › This version's files** lists every video the version has, what each
  is, and whether the app or your AI agent made it (videos the agent made itself
  are recognised and can be played from there); it also says what **Render a
  preview** and **Approve and export…** will reuse or replace.
- The story is the strip of scenes under the player, one block per beat, each
  as wide as its name, so a name is never cut off; when they do not all fit, the
  strip scrolls sideways (the mouse wheel scrolls it too). Click a scene to jump
  there. The pen on a scene (or a right-click on it) puts the scene in your
  notes: a chip *Note on: Pit stop* and the scene's name on a new line, ready
  for your words.
- **Story & review** has **The story** and **The editor's own review**. Each
  opens as a readable page: the short summary, the key changes and any
  concerns first (including anything you may not want public), and **Show the
  whole text** and **Show the technical report** one click away.
- If a version has no video yet, its picture says so with a **Render a
  preview** button (it is also under **Files**). A preview is 1280x720; for a 60
  fps recording it plays at 30 frames per second, half the export's rate.
  Afterwards the page says what changed: the first preview, or the earlier one
  replaced, and how many scenes were rendered or reused.
- Scenes an earlier version already rendered are reused. A version that
  changes only the sound renders no pictures again, so its preview takes
  seconds rather than minutes.
- Each render is in the version's **renders** folder under two names: the
  fixed one (*preview.mp4*) and a readable one, for example
  *race-v003-claude-opus-5.5-preview.mp4*. Both are the same file on disk
  (when the drive cannot do that, the report below says so).
- Each render also writes a report (*render-preview.json* beside it) of what
  really ran: what encoded each scene, whether the graphics card or the
  processor decoded it and why, which masks were applied, the frame rate and
  why, and how much the sound was lowered.
- Write what should change in **What should change?** at the bottom, for
  example *"The opening is too slow."* Then press **Save notes, copy prompt for
  Claude Code** (or **…for Codex**) and paste it into your agent. The scenes
  you added go with the notes and into the prompt. It makes a new version that
  answers your notes; every earlier version is kept.

## 4. Export the one you like

Press **Approve and export…** (top right) on the version you want. Its dialog
says what it does: it makes the finished video on this PC at 1920x1080, at the
recording's own frame rate up to 60 frames per second (a 60 fps recording stays
60; 120 becomes 60 and 144 becomes 48), at the **Export quality** shown in the
dialog; it levels the sound for upload (about −14 LUFS, as YouTube plays it);
it checks the video and puts it in the video's **export** folder, named with
the AI editor's label, for example *race-v003-claude-opus-5.5.mp4*. Nothing is
uploaded. It also says whether there is an export already that it will replace.
A video that fails the check is not exported. **Files › Open export folder**
finds it.

The preview you watch is a quick, smaller render; the export is the full-quality
file. That is why an export looks better than the preview of the same version.

**Export quality** is in the dialog and under **Files** (the tick shows the
choice, and the panel stays open so you can see it move):

- **YouTube (recommended)** suits an upload.
- **Highest quality** makes a file two to three times as big.
- **Smaller file** makes one under half the size, with lighter sound.

It follows **Settings › AI Video Editor** (**Using main setting**). Choose
another quality for one video and it shows **Overridden** for that video only.

A final needs extra disk space while it is made: its scenes are kept without
any loss of quality, which can take several gigabytes for a long edit, and they
are removed once the export is placed. Exporting again renders them again.

## A second, separate edit

To let another AI editor make its own cut of the same race, or simply to start
again, open the video and choose **Prompt › Start a fresh edit**. It
appears under *Your videos* as a separate edit (for example *race-edit-2*), with
no versions yet and a fresh AI budget. It reuses the race's analysis, so it is
ready at once. Copy its own prompt into the other agent. The first edit and its
versions stay as they are, so you can watch both and compare.

## Linking older videos

A video made by the current version knows its recording by its content, so it keeps
working when the recording is renamed or moved, and nothing else can be passed
off as it. A video made by an older version knows its recording only by its path, name,
size and time, and keeps working exactly as it always did until you link it.

While a video is not linked (or its linked recording is no longer where the
video says), the start view says how many, with **Link recordings…** beside it.
It opens one dialog listing each such video once, with the evidence:

- the recording's name, folder, size and length;
- whether the file is still there, and whether its size and time still match;
- whether the Raw bin has read it (then linking reads nothing);
- when the file is no longer there, a file of the same size and time that the
  Raw bin knows, or one beside where it was (a rename);
- whether its sound matches what Prepare measured, when both are known.

A file name alone is never offered. Press **Link this video** for each one the
evidence shows is right; a video you leave keeps working as before. Linking reads
the recording once when the Raw bin has not, then changes only the video's
`project.json`: a copy is kept beside it first as `project.json.before-link`
(putting that copy back undoes the link), and for a recording that moved the old
place is kept, so the versions made before still render. The first preview after
linking renders once again; the analysis is not rebuilt.

## Privacy masks

Press **Privacy masks…** (on Prepare's step, or under a video's **Video settings**) to mark
the parts of your cameras that must always be blurred, such as a phone, a keypad
or the room behind you. Choose the camera and a moment where you are in the
picture, press **Show**, and paint over the private parts (red is blurred).
Press **Save**. The blur is applied before any AI sees a picture and in every
video made afterwards.

- Your masks are always applied. Nothing the AI editor asks for can switch one
  off or replace it.
- The camera layout is fixed when you prepare. A request or an edit that would
  move a masked camera, leave it out or show it through another panel is
  refused.
- Only this window saves a mask or takes an unblurred camera picture; the AI
  editor's commands for those no longer work. The picture you paint on stays
  in the app's temporary folder on your PC and goes when you close the window.
- These guards stop mistakes. An AI agent that changes the project's files by
  hand on purpose could still get round them.

## Where each control is

| Control | Where it is |
|---|---|
| Choose a recording… | **Make a video from a recording** on the start view; also on Prepare's step |
| Your voice, Game sound, AI budget (with Reset to Auto and what Auto picks) | Prepare's step; later **Video settings** |
| Prepare for the AI editor | Prepare's step; **Prepare for the AI editor…** in the player's place of a video not prepared yet |
| Your videos | The start view, as picture cards |
| Refresh | Automatic; **Refresh** beside *Your videos*; **Files** |
| Link recordings… | The start view, under *Your videos*, while a video is not linked to its recording |
| Privacy masks… | Prepare's step; **Video settings** |
| Copy prompt for Claude Code, Copy prompt for Codex, See the prompt first | The second step; **Prompt**; Copy prompt for Claude Code also in the player's place before the first version |
| Start a fresh edit | **Prompt** |
| Open project folder, Open export folder | **Files** |
| Versions | Tabs under the video's name, left of the toolbar |
| The story, The editor's own review | **Story & review** (a readable page each); the story's beats are the strip under the player |
| Play the final (full quality), Play the preview (quick, smaller), Play the preview | On the version's picture; with a final, also under **Files** |
| Write a note about a scene | The pen on each scene of the strip, or a right-click on it |
| Render a preview | **Files**; on the picture of a version with no video yet |
| Approve and export… | Top right of the video |
| Export quality | The **Approve and export…** dialog; **Files** |
| What should change?, Save notes, copy prompt for Claude Code, …for Codex | The notes box at the bottom |

## Settings

**Settings › AI Video Editor** sets where edited videos are kept (a
*race-videos* folder inside the folder you choose, or inside your output
folder) and the AI budget a new video starts with. It also holds the model names
the prompts ask Claude Code and Codex to use. The tools rename their models every
few months, so if your model picker shows a newer name, type it here.

- **Export quality** is the quality every video exports at, unless it chooses
  its own.
- **Quick passes** are the faster Whisper jobs: finding your voice by
  listening, other voices on the game sound, the review kit's transcript and
  the word timings at cut points. **Whisper small (faster)** is much quicker on
  a long race; **Use main setting** uses your own Whisper model. Beside it the
  tab shows **Using main setting** or **Overridden**. Your narration always
  uses your own Whisper model.

Your voice and game-sound tracks are not set here: they follow the track names
and your **Narration track** setting (**Settings > General / Startup**).

[Back to Help](README.md)
