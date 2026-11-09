# OpenAI Setup

OpenAI is optional. Use this guide only when you intentionally choose AI
Private, AI Public, or Hybrid processing.

## Before you begin

- A ChatGPT subscription and OpenAI API billing are separate products.
- API use requires billing or credits on the OpenAI Platform project tied to
  the selected key.
- Local mode needs no OpenAI API key.
- Read [Processing and Privacy Modes](PROCESSING_MODES.md) before choosing a
  project for sensitive material.

## Create a project and key

1. Sign in to the [OpenAI Platform](https://platform.openai.com/).
2. Create or select a dedicated project for Media Manglers.
3. Open the [API Keys page](https://platform.openai.com/api-keys).
4. For normal personal use, create a user-owned key and choose **Owned by
   you** when that choice is shown.
5. Choose a **Restricted** key rather than unrestricted access.
6. Grant request permission for Chat Completions because Media Manglers uses
   it for OpenAI text translation.
7. For AI Private, also grant request permission for audio transcription.
8. Leave unrelated permissions disabled unless another approved workflow
   requires them.

Read-only permission is not sufficient because transcription and translation
send requests. Service accounts are intended mainly for shared automation or
other non-personal identities, not an ordinary desktop setup.

If you intentionally use both privacy paths, create separate projects and keys:

- a Private project for approved private processing;
- a Public/shared project only for content authorized for that project.

Project settings control privacy behavior. Naming a variable `PRIVATE` or
`PUBLIC` does not change the OpenAI project's configuration.

## Windows setup

### Use the one-time prompt

For an individual run, paste the key only when Media Manglers asks for it. The
key is used for that run and should not be written into a script or document.

### Set a key for the current PowerShell session

Private project:

```powershell
$env:OPENAI_API_KEY_PRIVATE="<your-private-project-key>"
```

Public/shared project:

```powershell
$env:OPENAI_API_KEY_PUBLIC="<your-shared-project-key>"
```

The legacy `OPENAI_API_KEY` name remains a Private fallback for older setups,
but new configurations should use the explicit Private or Public name.

### Set a persistent user environment variable

Private project example:

```powershell
[System.Environment]::SetEnvironmentVariable(
    "OPENAI_API_KEY_PRIVATE",
    "<your-private-project-key>",
    "User"
)
```

After setting a persistent user variable, close and reopen PowerShell before
running Media Manglers. Existing PowerShell sessions do not automatically see
the new value.

## Safety

- Never hardcode a key in either Media Manglers script.
- Never commit a key, settings export containing a key, or key screenshot.
- Keep each key limited to the project and permissions it needs.
- Private is the safer AI default, but confirm that the selected project's
  policy permits the content.
- Public requires explicit project selection and content authorized for that
  shared project.
- Rotate a key immediately if it may have been exposed.

## Common errors

### Authentication failed

Confirm that the correct environment variable contains an active key for the
selected project. Reopen PowerShell after a persistent-variable change.

### Missing permission

Edit the restricted key and grant request permission for text translation. AI
Private also needs audio-transcription request permission.

### Quota or billing error

Check API Platform billing, available credits, project limits, and the complete
error message. ChatGPT subscription billing does not fund API requests.

### Model unavailable

The selected project must be allowed to use a model supported by Media
Manglers. Choose another configured project or use Local mode; do not broaden
key permissions without understanding why.

### Network or timeout error

Check the internet connection, firewall or proxy policy, and OpenAI service
status. Retry only after the external cause is understood.

## Official OpenAI references

- [API Keys](https://platform.openai.com/api-keys)
- [Managing projects in the API Platform](https://help.openai.com/en/articles/9186755-managing-your-work-in-the-api-platform-with-projects)
- [Assign API key permissions](https://help.openai.com/en/articles/8867743-assign-api-key-permissions)
- [ChatGPT and API billing are separate](https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform)
- [API key safety](https://help.openai.com/en/articles/5112595-best-practices-for-api)

## Next steps

- [Processing and Privacy Modes](PROCESSING_MODES.md)
- [Documentation home](../README.md)
- [Media Manglers README](../../README.md)
