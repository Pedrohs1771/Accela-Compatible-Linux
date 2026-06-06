# Windows Testing Without Local Windows

Local Linux is used for implementation, unit tests and regression checks.
Windows packaging is performed on GitHub Actions `windows-latest`.

Validation layers:

- Linux regression unit tests.
- Windows unit tests with fake Steam fixtures.
- Windows `compileall` on `windows-latest`.
- PyInstaller build on `windows-latest`.
- `LumaDoctor.exe --self-test` smoke after packaging.

This gives high confidence for an RC. It does not replace manual testing on
real Windows 10/11 machines with Steam installed.
