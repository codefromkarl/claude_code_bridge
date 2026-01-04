CRITICAL: ALWAYS use run_in_background=true - NO EXCEPTIONS

$ARGUMENTS

## Execution (MANDATORY)

Bash(gask "$ARGUMENTS", run_in_background=true)

## After Execution

Tell user "Gemini processing..." then IMMEDIATELY END your turn.
DO NOT wait for result. DO NOT continue working.

## Wrong vs Right

WRONG: Bash(gask "question")
RIGHT: Bash(gask "question", run_in_background=true)

## Parameters

- `--timeout SECONDS` optional (default 3600)
- `--output FILE` optional: write reply to FILE
