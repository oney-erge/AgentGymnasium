# Portable preview notes

The [Windows preview](https://github.com/oney-erge/AgentGymnasium/releases/tag/preview-windows-2026-10-30)
includes its source commit, wheel, checksums, and `refresh_archive.py`. The script
replaces the application inside the previous Windows runtime archive; it does not
build that runtime from scratch or verify that the application starts.

To reproduce that assembly, download the script and wheel from the release and
the Windows archive from [the earlier preview](https://github.com/oney-erge/AgentGymnasium/releases/tag/preview-0.1.2).
From their directory, run:

```powershell
python refresh_archive.py --base agentgymnasium-windows-x64-portable-unverified.zip `
  --base-sha256 a997d2e979fb6b41c1e36abafc23ab1d29a7d8c7be25db01acc468e524770c4d `
  --wheel agentgymnasium-0.1.2-py3-none-any.whl --output refreshed.zip `
  --root agentgymnasium --commit 63cb58f8aed28b59991fb0554a70c2c30ee644c2
```

The script rejects a mismatched base and checks the wheel members in its output.
The source lock and project metadata must match the base's dependency inputs; the
script does not verify that itself. A complete from-scratch portable-runtime recipe
and clean-machine verification remain outstanding. Preserve prior release tags.
