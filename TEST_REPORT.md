# TEST REPORT

- Date: 2026-05-29T16:34:03-03:00
- Host: Linux 7.0.10-arch1-1 #1 SMP PREEMPT_DYNAMIC Sat, 23 May 2026 14:21:20 +0000 x86_64 GNU/Linux
- Python: Python 3.14.5

## Checks
- bash -n: install.sh, dev-install.sh, publish-update.sh, AppRun, run.sh
- python compileall: app/ACCELA/squashfs-root/bin/src
- fresh venv install: requirements.txt
- desktop-file-validate: accela.desktop (when tool is available)
- JSON validation: release/latest.json
- shellcheck: skipped (not installed)
- compileall: passed
- fresh venv: passed
- desktop file: passed
- release/latest.json: valid
