import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
# Иконка общая с основным лаунчером — лежит в assets/ на уровень выше.
ASSETS_DIR = PROJECT_DIR / "assets"
ICO_ICON = ASSETS_DIR / "icon.ico"


def ensure_icon_file():
    if not ICO_ICON.exists():
        raise FileNotFoundError(f"Не найдена иконка: {ICO_ICON}")
    return ICO_ICON


def build_bootstrap():
    icon_path = ensure_icon_file()
    data_arg = f"{ASSETS_DIR}{os.pathsep}assets"

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
        "main.py",
    ]

    print("Сборка bootstrap EXE...")
    print("Команда:", " ".join(command))
    subprocess.run(command, cwd=PROJECT_DIR, check=True)
    print("\nГотово. EndyLauncher.exe (bootstrap) находится в bootstrap/dist/.")
    print(
        "Это тот файл, который скачивает и запускает пользователь. Публикуется "
        "он редко — сам он никогда себя не обновляет, только проверяет и "
        "подтягивает актуальный launcher.exe перед запуском."
    )


if __name__ == "__main__":
    build_bootstrap()
