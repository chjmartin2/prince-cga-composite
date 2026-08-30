# GitHub Publishing Safety

This source repository may be published publicly only while original game
binaries, generated game packages, and other non-distributable local inputs
remain excluded from Git tracking.

The root `.gitignore` excludes:

- original and patched DAT archives;
- DOS executables and launchers;
- generated runtime package directories;
- release ZIPs;
- local editor sidecars and exported images.

Before the first push to any new remote, run:

```powershell
git status --short
git ls-files | Select-String -Pattern '\.(DAT|EXE|COM|ZIP)$'
```

The second command should produce no output. If it does, stop and remove those
files from Git tracking before publishing.

Use GitHub Releases only for files you have separately determined may be
distributed. Do not assume that source publication makes local game inputs or
generated packages appropriate for a public release.
