Use `opend` to fetch latest reply from OpenCode storage.

WARNING: Only use when user EXPLICITLY requests. Do NOT use proactively after oask.

Trigger conditions (ALL must match):
- User EXPLICITLY mentions opend/Opend
- Or user asks to "view opencode reply" / "show opencode response"

Execution:
- `opend` - fetch latest reply: `Bash(opend)`

Output: stdout = reply text, exit code 0 = success, 2 = no reply

