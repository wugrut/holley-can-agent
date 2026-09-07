"""
build_portable.py — Automated packaging script for EFI Intelligence Copilot.

Compiles a standalone, offline Windows distribution containing efi_copilot.exe,
all batch launchers, configuration, field guides, web assets, and creates
a single portable ZIP archive ready for transfer to a tuning laptop.
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 charmap errors
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import PyInstaller.__main__

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
TARGET_DIR = DIST_DIR / "efi-intelligence-copilot"
ZIP_OUTPUT = DIST_DIR / "efi-intelligence-copilot-portable.zip"


def build():
    print("\n" + "=" * 76)
    print("  BUILDING STANDALONE PORTABLE EFI INTELLIGENCE COPILOT")
    print("=" * 76)

    # 1. Clean previous dist, build artifacts, and bytecode caches
    if TARGET_DIR.exists():
        print(f"Cleaning previous target at: {TARGET_DIR}")
        shutil.rmtree(TARGET_DIR, ignore_errors=True)
    if ZIP_OUTPUT.exists():
        os.remove(ZIP_OUTPUT)
    build_dir = BASE_DIR / "build"
    if build_dir.exists():
        print(f"Cleaning build cache at: {build_dir}")
        shutil.rmtree(build_dir, ignore_errors=True)
    for spec_file in BASE_DIR.glob("*.spec"):
        try:
            spec_file.unlink(missing_ok=True)
        except Exception:
            pass
    for pycache_dir in BASE_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir, ignore_errors=True)
        except Exception:
            pass

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Configure PyInstaller Arguments
    entry_script = str(BASE_DIR / "portable_entry.py")
    static_data = f"{BASE_DIR / 'holley_can' / 'static'};holley_can/static"
    fixtures_data = f"{BASE_DIR / 'data' / 'fixtures'};data/fixtures"
    csv_data = f"{BASE_DIR / 'holley_can_channels.csv'};."

    pyinstaller_args = [
        entry_script,
        "--name=efi_copilot",
        "--onedir",
        "--noconfirm",
        "--clean",
        f"--distpath={DIST_DIR}",
        f"--workpath={BASE_DIR / 'build'}",
        f"--add-data={static_data}",
        f"--add-data={fixtures_data}",
        f"--add-data={csv_data}",
        # CAN Backends
        "--hidden-import=app.hardware.holley_usbcan",
        "--hidden-import=can.interfaces.pcan",
        "--hidden-import=can.interfaces.slcan",
        "--hidden-import=can.interfaces.virtual",
        "--hidden-import=serial",
        "--hidden-import=serial.tools.list_ports",
        # FastAPI & Uvicorn
        "--hidden-import=uvicorn",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=fastapi",
        "--hidden-import=websockets",
        "--hidden-import=pydantic",
        "--hidden-import=yaml",
        "--hidden-import=sqlite3",
        "--hidden-import=numpy",
    ]

    print("\n[1/4] Running PyInstaller Compiler...")
    PyInstaller.__main__.run(pyinstaller_args)

    # The onedir output is in DIST_DIR / "efi_copilot"
    compiled_folder = DIST_DIR / "efi_copilot"
    if compiled_folder.exists() and compiled_folder != TARGET_DIR:
        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        compiled_folder.rename(TARGET_DIR)

    print(f"   [OK] Standalone executable compiled into: {TARGET_DIR}")

    # 3. Copy Launchers, Config, and Documentation into Target Distribution
    print("\n[2/4] Assembling Portable Distribution Bundle...")

    # Copy Launchers
    launchers_dir = BASE_DIR / "launchers"
    for bat_file in launchers_dir.glob("*.bat"):
        dest = TARGET_DIR / bat_file.name
        shutil.copy2(bat_file, dest)
        print(f"   + Included Launcher: {bat_file.name}")

    # Copy config.portable.yaml as config.yaml
    shutil.copy2(BASE_DIR / "config.portable.yaml", TARGET_DIR / "config.yaml")
    print("   + Included Configuration: config.yaml")

    # Copy Field Guide & Hardware Documentation
    shutil.copy2(BASE_DIR / "FIELD_GUIDE.md", TARGET_DIR / "FIELD_GUIDE.md")
    print("   + Included Field Guide: FIELD_GUIDE.md")
    (TARGET_DIR / "docs").mkdir(exist_ok=True)
    shutil.copy2(BASE_DIR / "docs" / "HOLLEY_USB_CAN_INTERFACE.md", TARGET_DIR / "docs" / "HOLLEY_USB_CAN_INTERFACE.md")
    print("   + Included Hardware Interface Doc: docs/HOLLEY_USB_CAN_INTERFACE.md")

    # Create empty runtime directories
    (TARGET_DIR / "data").mkdir(exist_ok=True)
    (TARGET_DIR / "reports").mkdir(exist_ok=True)
    print("   + Initialized data/ and reports/ directories")

    # 4. Create Portable ZIP Archive
    print(f"\n[3/4] Creating Compressed Portable Archive: {ZIP_OUTPUT.name}...")
    file_count = 0
    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(TARGET_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(DIST_DIR)
                zipf.write(full_path, arcname=str(rel_path))
                file_count += 1

    zip_mb = ZIP_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"   [OK] Portable ZIP created ({zip_mb:.1f} MB, {file_count} files)")

    # 5. Summary & Verification
    print("\n" + "=" * 76)
    print("  PORTABLE TUNING LAPTOP BUNDLE READY!")
    print("=" * 76)
    print(f"  Distribution Folder:  {TARGET_DIR}")
    print(f"  Flash Drive Archive:  {ZIP_OUTPUT}")
    print(f"  Archive Size:         {zip_mb:.1f} MB")
    print("\n  Launchers Included:")
    for bat in sorted(TARGET_DIR.glob("*.bat")):
        print(f"    - {bat.name}")
    print("\n  Transfer to Tuning Laptop:")
    print("    Copy 'efi-intelligence-copilot-portable.zip' to USB stick, extract,")
    print("    and run '1_RUN_SIMULATOR_DEMO.bat' or '4_PREFLIGHT_HARDWARE_CHECK.bat'.")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    build()
