CRITICAL: ALWAYS use run_in_background=true - NO EXCEPTIONS

$ARGUMENTS

## Execution (MANDATORY)

Bash(oask "$ARGUMENTS", run_in_background=true)

## After Execution

Tell user "OpenCode processing..." then IMMEDIATELY END your turn.
DO NOT wait for result. DO NOT continue working.

## Wrong vs Right

WRONG: Bash(oask "question")
RIGHT: Bash(oask "question", run_in_background=true)

## Parameters

- `--timeout SECONDS` optional (default 3600)
- `--output FILE` optional: write reply to FILE
