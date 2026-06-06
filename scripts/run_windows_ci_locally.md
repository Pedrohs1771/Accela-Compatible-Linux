# Running Windows CI Locally

You cannot produce the final Windows PyInstaller artifact from Linux reliably.
Use GitHub Actions:

```bash
git push origin release/windows-v1.1.0-rc
gh workflow run windows-rc.yml --ref release/windows-v1.1.0-rc
gh run list --workflow windows-rc.yml
gh run download <run-id>
```

Optional Linux-only checks:

```bash
PYTHONPATH=app/LumaTools/squashfs-root/bin/src python -m unittest discover -s tests -v
python -m compileall app/LumaTools/squashfs-root/bin/src tests tools
python tools/build_windows.py --skip-pyinstaller
```
