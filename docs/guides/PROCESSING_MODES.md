# Processing and Privacy Modes

Media Manglers can process media entirely on your computer or use an optional
OpenAI Platform project for specific transcription or translation work. Choose
the mode before selecting sensitive or confidential material.

## Summary

| Mode | What stays local | What may be sent to OpenAI | API key | Choose it when |
| --- | --- | --- | --- | --- |
| **Local** | Source media, transcription, and translation | Nothing | No | The required local tools are installed and media must stay on the computer |
| **AI Private** | Local working files and generated package output | Source audio for transcription and transcript text for requested translation | Yes | Policy permits the selected private OpenAI project to process the material |
| **AI Public** | Source audio and transcription | Requested translation text sent to the explicitly selected shared project | Yes | The material is authorized for that configured shared project |
| **Hybrid** | Source audio and source-language transcription | Transcript text for English translation | Yes | Audio must stay local but OpenAI text translation is permitted |

## Local

Local mode performs transcription and translation on your computer after the
required tools and language packages are installed.

- **Stays local:** source media, extracted audio, transcripts, and translations.
- **Sent to OpenAI:** nothing.
- **API key:** not required.
- **Choose it when:** content must remain local or OpenAI use is unnecessary.

Local transcription uses Whisper. Non-English local translation targets may
also require Argos Translate and the matching language packages. Use
[Dependencies and Setup](../workbench/DEPENDENCIES_SETUP.md) to check readiness.

## AI Private

AI Private uses the explicitly selected private OpenAI project.

- **Stays local:** source files, working files, and generated package output.
- **Sent to OpenAI:** source audio for transcription and transcript text when
  translation is requested.
- **API key:** required for the selected private project.
- **Choose it when:** the applicable policy permits that private project to
  process the source content.

Private is the safer default when an AI workflow is authorized, but it is not
the same as Local mode. Source audio can leave the computer.

## AI Public

AI Public keeps transcription local and uses the explicitly selected
Public/shared OpenAI project only for requested text translation.

- **Stays local:** source audio, extraction, and source-language transcription.
- **Sent to OpenAI:** transcript text needed for the requested translation.
- **API key:** required for the selected Public/shared project.
- **Choose it when:** the content is authorized for that configured shared
  project.

Selecting an environment variable named `PUBLIC` does not make a project safe
for public content. The OpenAI project configuration controls the actual
privacy and sharing behavior.

## Hybrid

Hybrid creates the source-language transcript locally, then sends only text to
OpenAI for English translation.

- **Stays local:** source audio, extraction, and source-language transcription.
- **Sent to OpenAI:** transcript text for English translation.
- **API key:** required for the selected OpenAI project.
- **Choose it when:** audio must remain local and text-only English translation
  is authorized.

The current Hybrid boundary is source language to English. Broader target
languages are not part of the current Hybrid path.

## Confidential and sensitive material

Use **Local** or **AI Private** for confidential material according to the
policy that governs that content. Before using AI Private, confirm that sending
source audio and text to the selected private project is authorized.

Use **AI Public** only for material authorized for the configured shared
project. When in doubt, stop and use Local mode until the correct policy and
project are confirmed.

Project configuration controls privacy behavior. The names
`OPENAI_API_KEY_PRIVATE` and `OPENAI_API_KEY_PUBLIC` help the operator select a
key, but the variable name alone cannot prove how its OpenAI project is
configured.

## Translation behavior

1. Media Manglers creates the original-language transcript first.
2. Translation occurs only when it is requested.
3. If the detected source language already matches the requested target,
   Media Manglers copies the original transcript into the target translation
   folder and skips the OpenAI text-translation call.
4. In AI Private, OpenAI transcription can still occur when that mode requires
   it, even when same-language text translation is skipped.
5. Hybrid keeps audio and source transcription local and currently sends only
   transcript text for English translation.

For app-specific parameters and examples, use the [Video Mangler command-line
guide](VIDEO_MANGLER.txt) or [Audio Mangler command-line
guide](AUDIO_MANGLER.txt). Implementation details belong in the [Technical
Reference](../workbench/TECHNICAL_REFERENCE.md).

## Next steps

- [OpenAI Setup](OPENAI_SETUP.md)
- [Dependencies and Setup](../workbench/DEPENDENCIES_SETUP.md)
- [Settings and Migration](../workbench/SETTINGS_MIGRATION.md)
- [Documentation home](../README.md)
- [Media Manglers README](../../README.md)
