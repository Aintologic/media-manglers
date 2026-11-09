README_FOR_CODEX

This folder contains a Video Mangler review package for:
1_min_test_Video.mp4

What is included:
- raw\                            original source video (only if you chose to keep a copy)
- proxy\review_proxy_1280.mp4     review copy for playback
- frames_0p5s\frame_000001.jpg ...
- audio\audio.mp3                 only when the source has spoken audio
- audio\audio_tracks.json / .csv  detected audio track inventory
- audio\transcript_source_manifest.json all-track extraction/transcript manifest when all tracks are transcribed
- transcript\transcript.srt / .json / .txt
- transcript\tracks\              per-track transcript files when multiple audio tracks are present
- transcript\all_audio_tracks_transcript.md combined all-track transcript handoff when present
- transcript\all_audio_tracks_index.csv and all_audio_tracks_manifest.json all-track transcript index and manifest when present
- translations\<lang>\transcript.srt / .json / .txt when translation was requested
- comments\comments.txt / .json   public comments export when available and requested
- frame_index.csv                 timestamp index for the extracted frames
- frames_panels\                  high-detail 1920x1080 panel crops when an exact 5760x1080 source was detected
- audio\transcript_source.wav      selected single audio source used for transcription in Mixed/Track mode
- audio\transcript_source_metadata.json selected single-stream reuse-guard metadata in Mixed/Track mode
- script_run.log                  processing log, including raw OpenAI error details when available

A good review order:
1. Start with transcript\transcript.txt when audio is present.
2. Watch proxy\review_proxy_1280.mp4 for pacing, sequence, and spoken context.
3. Use frame_index.csv to map timestamps to the extracted frames.
4. Check translations\<lang>\ if you asked for translated text.
5. Check comments\ if public source comments were included for context.
6. Use raw video only if the derived review assets are not enough.

Notes:
- Package status: success
- Selected frame interval: 0.5 seconds
- Frames folder: frames_0p5s
- Raw video present: No
- Audio present in source: Yes
- Processing mode used: Local
- AI project mode: not applicable (Local mode)
- Transcription path used: Local (Whisper transcription)
- Detected source language: en
- Remote audio track selected: not applicable (local source or provider metadata unavailable)
- Translation targets: none
- Translation status: not requested
- Translation path used: none
- Translation notes: none
- Next steps: none
- Comments: not included
- Full Review panel crops: not evaluated
- Panel frames folder: not created
- Panel frame index: not created
- Transcript audio source: not available
- Transcript source metadata: not available
- Transcript source manifest: not available
- All audio tracks transcript: not available
- All audio tracks index: not available
- All audio tracks manifest: not available
