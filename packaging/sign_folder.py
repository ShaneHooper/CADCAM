"""Sign a built G-SEND CADCAM folder so Windows Smart App Control lets it run.

Smart App Control has no "Run anyway": it blocks any exe *or DLL* without a trusted
signature. A PyInstaller folder loads hundreds of binaries (OpenCascade, VTK, Qt, numpy...),
so every .exe/.dll/.pyd that isn't already validly signed gets signed here, not just
"G-SEND CADCAM.exe". Files that already carry a valid signature (Python, Qt, Microsoft runtime
DLLs) are left alone.

Uses the same config format as G-SEND.IO's utilities/sign_build.py, so the Azure Trusted
Signing setup on Shane's home laptop works unchanged:

    signing.local.json   (repo root, gitignored; or set GSEND_SIGNING_CONFIG to its path)
    {
      "signtool": "C:\\path\\to\\signtool.exe",          // optional
      "args": ["sign", "/fd", "SHA256", "/tr", "http://timestamp.acs.microsoft.com",
               "/td", "SHA256", "/dlib", "C:\\...\\Azure.CodeSigning.Dlib.dll",
               "/dmdf", "C:\\...\\metadata.json"]
    }

Usage (Windows):
    python packaging\\sign_folder.py "dist\\G-SEND CADCAM"            # sign what needs it, then verify all
    python packaging\\sign_folder.py "dist\\G-SEND CADCAM" --check    # just report what is unsigned
    python packaging\\sign_folder.py "dist\\G-SEND CADCAM" --list unsigned.txt   # write the list (CI)

Exit 0 only when every binary in the folder ends up with a Valid signature.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTS = (".exe", ".dll", ".pyd")
SDK_BIN = r"C:\Program Files (x86)\Windows Kits\10\bin"
BATCH = 40          # files per signtool call (keeps the command line short)


def binaries(folder):
    out = []
    for dirpath, _, files in os.walk(folder):
        out += [os.path.join(dirpath, f) for f in files if f.lower().endswith(EXTS)]
    return sorted(out)


def signature_status(paths):
    """{path: status} from Get-AuthenticodeSignature ("Valid", "NotSigned", ...)."""
    status = {}
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        listing = os.path.join(os.environ.get("TEMP", "."), "gsend_cadcam_sig_list.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.write("\n".join(chunk))
        ps = ("Get-Content -LiteralPath '%s' | ForEach-Object { $s = Get-AuthenticodeSignature -LiteralPath $_; "
              "\"$($s.Status)`t$_\" }" % listing)
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            if "\t" in line:
                st, path = line.split("\t", 1)
                status[path.strip()] = st.strip()
    return status


def load_config():
    path = os.environ.get("GSEND_SIGNING_CONFIG") or os.path.join(ROOT, "signing.local.json")
    if not os.path.isfile(path):
        sys.exit(f"No signing config at {path}. Copy the signing.local.json from the G-SEND.IO repo "
                 "on the laptop that has Azure Trusted Signing set up, or set GSEND_SIGNING_CONFIG.")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg.get("args"), list) or not cfg["args"]:
        sys.exit(f"{path} has no 'args' list")
    return cfg


def find_signtool(cfg):
    if cfg.get("signtool"):
        return cfg["signtool"]
    found = sorted(glob.glob(os.path.join(SDK_BIN, "*", "x64", "signtool.exe")))
    if not found:
        sys.exit("signtool.exe not found: install the Windows SDK or set \"signtool\" in the config")
    return found[-1]


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    folder, check_only = argv[1], "--check" in argv[2:]
    if "--list" in argv[2:]:
        # write the unsigned binaries, one path per line (for azure/artifact-signing-action's
        # files-catalog), then exit 0: CI signs exactly these, nothing already valid
        out = argv[argv.index("--list") + 1]
        files = binaries(folder)
        status = signature_status(files)
        todo = [f for f in files if status.get(f) != "Valid"]
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(os.path.abspath(f) for f in todo) + ("\n" if todo else ""))
        print(f"{len(files)} binaries, {len(todo)} unsigned -> {out}")
        return 0
    files = binaries(folder)
    status = signature_status(files)
    todo = [f for f in files if status.get(f) != "Valid"]
    print(f"{len(files)} binaries, {len(files) - len(todo)} already signed, {len(todo)} need signing")
    if check_only:
        for f in todo:
            print("  UNSIGNED", os.path.relpath(f, folder), status.get(f, "?"))
        return 0 if not todo else 1
    if todo:
        cfg = load_config()
        tool = find_signtool(cfg)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            print(f"signing {i + 1}-{i + len(chunk)} of {len(todo)}")
            subprocess.run([tool, *cfg["args"], *chunk], check=True)
    status = signature_status(files)
    bad = [f for f in files if status.get(f) != "Valid"]
    for f in bad:
        print("  NOT VALID", os.path.relpath(f, folder), status.get(f, "?"))
    print("ALL SIGNED" if not bad else f"{len(bad)} binaries still not validly signed")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
