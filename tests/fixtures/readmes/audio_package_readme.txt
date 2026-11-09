README_FOR_CODEX

This folder contains an Audio Mangler review package for:
1_min_test_Video.mp4

What is included:
- raw\                            original source audio (only if you chose to keep a copy)
- audio\review_audio.mp3          clean listening copy for review
- transcript\transcript_original.srt / .json / .txt
- translations\<lang>\transcript.srt / .json / .txt when translation was requested
- comments\comments.txt / .json   public comments export when available and requested
- segment_index.csv               timestamp index for the original transcript
- script_run.log                  processing log, including raw OpenAI error details when available

A good review order:
1. Start with transcript\transcript_original.txt for the quick read.
2. Use transcript\transcript_original.srt or segment_index.csv when you need timestamps.
3. Open translations\<lang>\ only if you asked for translated text.
4. Use audio\review_audio.mp3 when tone, pronunciation, or emphasis matters.
5. Check comments\ if public source comments were included for extra context.

Notes:
- Package status: success
- Processing mode used: Local
- AI project mode: not applicable (Local mode)
- Transcription path used: Local (Whisper transcription)
- Detected source language: en
- Translation targets: none
- Translation status: not requested
- Translation path used: none
- Translation notes: none
- Next steps: none
- Comments: not included
- Raw audio present: No
