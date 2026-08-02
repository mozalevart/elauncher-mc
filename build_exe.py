import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PROJECT_DIR / "assets"
PNG_ICON = ASSETS_DIR / "icon.png"
ICO_ICON = ASSETS_DIR / "icon.ico"


def _has_multi_size_ico(path):
    try:
        data = path.read_bytes()
    except Exception:
        return False
    if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
        return False
    count = int.from_bytes(data[4:6], "little")
    return count >= 2


def ensure_icon_file():
    if not PNG_ICON.exists():
        raise FileNotFoundError(f"Не найдена иконка: {PNG_ICON}")

    preferred_candidates = [
        ASSETS_DIR / "default.ico",
        ASSETS_DIR / "append_bmp_no_sizes.ico",
        ASSETS_DIR / "append_bmp.ico",
        ASSETS_DIR / "append.ico",
        ASSETS_DIR / "sizes_only.ico",
    ]
    for candidate in preferred_candidates:
        if candidate.exists() and _has_multi_size_ico(candidate):
            shutil.copy2(candidate, ICO_ICON)
            print(f"Использую готовый ICO-файл: {candidate.name}")
            return ICO_ICON

    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow не установлен. Установите его командой: "
            "python -m pip install pillow"
        ) from exc

    source = Image.open(PNG_ICON).convert("RGBA")
    width, height = source.size

    if width != height:
        size = max(width, height)
        padded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = ((size - width) // 2, (size - height) // 2)
        padded.paste(source, offset)
        source = padded

    if source.width < 512 or source.height < 512:
        print(
            f"⚠️  Исходная иконка {PNG_ICON.name} имеет размер "
            f"{source.width}x{source.height}. Для чёткой иконки в Проводнике, "
            "панели задач и заголовке окна нужен квадратный PNG минимум 512x512 "
            "(лучше 1024x1024) — иначе крупные варианты будут получены растяжением "
            "и всё равно останутся размытыми."
        )

    # ВАЖНО: не указываем bitmap_format="bmp" — Windows ожидает, что иконки
    # размером от 256x256 хранятся в ICO как PNG-сжатые записи. Если насильно
    # закодировать их как BMP, крупные записи получаются повреждёнными:
    # Проводник (запрашивает крупную иконку) не может их прочитать и показывает
    # иконку по умолчанию, а панель задач/заголовок окна используют только
    # мелкие рабочие записи — отсюда и "мыльная" картинка. Отдаём выбор формата
    # для каждого размера самому Pillow — так оно расставляет PNG/BMP правильно.
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (96, 96), (128, 128), (256, 256), (512, 512)]
    resized = [source.resize(size, Image.Resampling.LANCZOS) for size in sizes]

    # Перегенерируем .ico при каждой сборке — иначе, если старый файл уже
    # существовал (в том числе битый), скрипт бы бесконечно переиспользовал
    # именно его и никогда не подхватил бы исправление.
    if ICO_ICON.exists():
        ICO_ICON.unlink()

    resized[0].save(
        ICO_ICON,
        format="ICO",
        append_images=resized[1:],
        sizes=sizes,
    )

    try:
        from PIL import Image, ImageSequence
        with Image.open(ICO_ICON) as img:
            frame_sizes = [frame.size for frame in ImageSequence.Iterator(img)]
            print(f"Иконка пересобрана: {ICO_ICON} ({len(sizes)} размеров, фактических кадров: {len(frame_sizes)})")
            if len(frame_sizes) <= 1:
                print("⚠️ ICO-файл содержит только один кадр. Это часто приводит к плохому качеству иконки в Windows.")
    except Exception as exc:
        print(f"⚠️ Не удалось проверить структуру ICO-файла: {exc}")

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
            import shutil
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