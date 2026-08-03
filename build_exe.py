import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PROJECT_DIR / "assets"
ICO_ICON = ASSETS_DIR / "icon.ico"


def ensure_icon_file():
    if not ICO_ICON.exists():
        raise FileNotFoundError(f"Не найдена иконка: {ICO_ICON}")
    return ICO_ICON


def build_exe():
    icon_path = ensure_icon_file()
    data_arg = f"{ASSETS_DIR}{os.pathsep}assets"

    # Чистим прошлую сборку. Помимо прочего, это помогает не путать себя:
    # если exe с тем же именем уже был на диске, Windows Explorer иногда
    # продолжает показывать иконку из своего кэша, даже когда в самом файле
    # она уже другая.
    dist_dir = PROJECT_DIR / "dist"
    build_dir = PROJECT_DIR / "build"
    for old_dir in (dist_dir, build_dir):
        if old_dir.exists():
            shutil.rmtree(old_dir)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "EndyLauncher",
        "--icon",
        str(icon_path),
        "--add-data",
        data_arg,
        "launcher_gui.py",
    ]

    print("Сборка EXE...")
    print("Команда:", " ".join(command))
    subprocess.run(command, cwd=PROJECT_DIR, check=True)
    print("\nГотово. EXE находится в папке dist/.")
    print(
        "Если в Проводнике иконка всё ещё не появилась — это Windows показывает "
        "закэшированную старую иконку, а не саму сборку. Помогает: "
        "'ie4uinit.exe -ClearIconCache' в командной строке, либо перезапуск "
        "explorer.exe, либо просто перезагрузка."
    )


if __name__ == "__main__":
    build_exe()