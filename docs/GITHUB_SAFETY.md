# Private GitHub Setup

This repository must remain private while it contains work derived from a
locally owned copy of DOS Prince of Persia.

The root `.gitignore` excludes:

- original and patched DAT archives;
- DOS executables and launchers;
- generated runtime package directories;
- release ZIPs;
- local editor sidecars and exported images.

Before every first push, run:

```powershell
git status --short
git ls-files | Select-String -Pattern '\.(DAT|EXE|COM|ZIP)$'
```

The second command should produce no output. If it does, stop and remove those
files from Git tracking before publishing.

Use GitHub Releases only for files you have separately determined may be
distributed. Do not assume that because a file can be pushed to a private
repository it is appropriate for a public release.

