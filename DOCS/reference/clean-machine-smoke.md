# Clean-machine smoke test (Windows)

This is the reproducible check for the claim that SE installs on a **clean
Windows image** — no Python, Node, OpenCode or package manager assumed. Run it in
a disposable Windows Sandbox or VM, never on a working machine.

The script is [`SE-INSTALLER/scripts/smoke-clean-machine.ps1`](../../SE-INSTALLER/scripts/smoke-clean-machine.ps1).

## Modes

| Mode | What it does | Use |
|---|---|---|
| `DryRun` (default) | Creates the isolated installer venv, installs `se-installer`, runs `bootstrap.ps1 install --recommended --dry-run`, then `se validate`, `se doctor` and `se install --dry-run`. It does not install Python, Node, OpenCode or MCP packages. | CI and a quick local regression check |
| `Install` | Does the real `bootstrap.ps1 install --recommended`, then checks `node`, `npx`, `opencode` and that `context7`/`filesystem` were written to `opencode.jsonc`. | Disposable Sandbox/VM only |

Both modes write a JSON report (`se.smoke/1`) and exit non-zero if a check fails.
Use `-ReportPath` to choose the file.

## Windows Sandbox

Windows Sandbox is the fastest way to get a clean image. Enable it once from an
administrator PowerShell (requires Windows 10/11 Pro/Enterprise and a reboot):

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All
```

Create a **disposable copy** of the repository (the real install writes
`opencode.jsonc` and creates `SE-INSTALLER\.venv`), then map that copy and run the
script when the sandbox logs in. Save this as `se-smoke.wsb` and replace the host
path:

```xml
<Configuration>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\src\SYSTEM-ENGINEERING-smoke</HostFolder>
      <SandboxFolder>C:\SE</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -ExecutionPolicy Bypass -NoProfile -File C:\SE\SE-INSTALLER\scripts\smoke-clean-machine.ps1 -Mode Install -ReportPath C:\SE\smoke-report.json</Command>
  </LogonCommand>
</Configuration>
```

Double-click the `.wsb`. The Sandbox is discarded when it closes; the report is
written into the mapped copy if you want to inspect it from the host. Do not map
a checkout you care about, because the real install changes it.

If the image has no network, the real install cannot download Python/Node/OpenCode
or the `npx` packages. The `DryRun` mode still needs network for `pip install -e`;
on an offline image, pre-populate the pip cache or test in a networked Sandbox.

## Hyper-V / VMware

1. Create a Windows 10/11 VM with a checkpoint and network access.
2. Copy or clone the repository into the VM.
3. Open PowerShell as the normal user (not administrator) and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\SE-INSTALLER\scripts\smoke-clean-machine.ps1 -Mode Install
   ```

4. Inspect `SMOKE: PASS` and the JSON report, then revert the checkpoint.

The script does not require elevation: Python, Node and OpenCode are installed per
user. A machine-wide package manager install may still prompt, which is why the
check belongs in a disposable image.

## Expected result

`DryRun`:

```text
[PASS] bootstrap install --recommended --dry-run
[PASS] se validate
[PASS] se doctor
[PASS] se install --dry-run
[SKIP] real install and MCP registration
SMOKE: PASS (5 checks)
```

`Install` additionally reports:

```text
[PASS] bootstrap install --recommended (real)
[PASS] node --version
[PASS] npx --version
[PASS] opencode --version
[PASS] MCP registration
[PASS] se doctor after install
```

`se doctor` currently reports `PASS=20 WARN=1 FAIL=0` because of the
self-containment guidance token check; the WARN is expected and not a smoke
failure. The script only fails on a non-zero exit code.

## CI

The `windows-latest` CI job runs `-Mode DryRun` on every pull request. That job
does not validate the real downloads, installers or runtime; it catches bootstrap
script regressions and keeps the documented path executable. The real end-to-end
check is the disposable Sandbox/VM run above.

## Cleanup

For a local (non-Sandbox) run, remove the generated installer state and undo the
host-specific config change:

```powershell
Remove-Item -Recurse -Force SE-INSTALLER\.venv
git checkout -- opencode.jsonc
```

Do this only in the disposable copy; never discard unrelated local changes.
