# This checkout

Location: `D:/AgentWorkspace/agentrelay`.

The verified development environment is `.runtime/Scripts/python.exe` (Python 3.12.14). The machine's Python 3.14 launcher could run standard-library tests but failed during `venv` bootstrap; that failed attempt is preserved in ignored `.venv/`. No global Python installation was changed.

The demonstration preview for this session uses port **8788**, database `.agentrelay/demo.sqlite`. Its logs are `.agentrelay/preview.out.log` and `.agentrelay/preview.err.log`. Normal CLI default is port 8787.

Start a real empty project in another terminal:

```powershell
.runtime\Scripts\python.exe -X utf8 -m agentrelay serve --port 8789
```

Example local MCP host entry (configure explicitly in your selected client; this repository does not modify client settings):

```json
{
  "mcpServers": {
    "agentrelay": {
      "command": "D:/AgentWorkspace/agentrelay/.runtime/Scripts/python.exe",
      "args": ["-X", "utf8", "-m", "agentrelay", "mcp", "--db", "D:/AgentWorkspace/agentrelay/.agentrelay/workspace.sqlite", "--actor", "agent:worker-01"],
      "cwd": "D:/AgentWorkspace/agentrelay"
    }
  }
}
```

Use `demo.sqlite` only for intentional tests. Give reviewer connections another actor identity. A client without a `cwd` option should use the installed `agentrelay.exe` entry point. The skill is packaged under `skills/agentrelay-work/`; install it in your client's skill directory when choosing to enable the workflow.

Validation in this Windows sandbox required permission for loopback networking and local MCP subprocesses. The test failures inside the network-restricted sandbox were environment failures; the same tests ran against real sockets/processes outside it. Network permission for downloading the SDK was used only to install in `.runtime` with cache under `.cache/uv`.
