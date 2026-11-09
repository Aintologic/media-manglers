Media Manglers documentation index
==================================

Media Manglers is a Windows media-review project with two processing apps and
one guided desktop interface.

Choose a tool
-------------

Video Mangler Workbench
  The recommended desktop app. Four features on one engine: Find my bug
  reports, Package any video for AI, Watch the raw bin, and the AI Video
  Editor.

Video Mangler
  The command-line and automation path for video review, transcripts, frames,
  proxy media, evidence packages, and archive catalogs.

Audio Mangler
  The command-line and automation path for transcript-first audio review.

Download
--------

Releases (the first public release is coming soon):
  https://github.com/Aintologic/media-manglers/releases

Most users should download VideoManglerWorkbench-vX.Y.Z.zip. Extract the
complete ZIP and keep its executable, engine, Help, and runtime files together.

Documentation
-------------

Project documentation home:
  ../README.md

Workbench Help:
  ../workbench/README.md

Workbench Getting Started:
  ../workbench/GETTING_STARTED.md

Every feature in one guide:
  ../workbench/FEATURE_GUIDE.md

Processing and Privacy Modes:
  PROCESSING_MODES.md

OpenAI Setup:
  OPENAI_SETUP.md

Video Mangler command-line guide:
  VIDEO_MANGLER.txt

Audio Mangler command-line guide:
  AUDIO_MANGLER.txt

Current release notes:
  ../release-notes/RELEASE_NOTES_v0.11.0.txt

The per-app guides contain the complete parameters, examples, output details,
and validation commands. Processing/privacy and OpenAI setup are maintained in
their focused pages instead of being repeated here.

Safety
------

Original local media is read-only. New files are written under the output
folder selected for the run. OpenAI is optional, and Local mode requires no
OpenAI API key.

Use GitHub Issues for bugs, usability problems, and feature requests:
  https://github.com/Aintologic/media-manglers/issues

Do not post credentials, private recordings, client information, or
confidential output.

License
-------

Repository code: GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
Third-party notices: ../../THIRD_PARTY_NOTICES.txt
