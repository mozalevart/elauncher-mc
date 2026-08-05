"""
EndyLauncher — bootstrap.

Это маленький, стабильный exe, который пользователь скачивает и запускает
напрямую (ярлык на рабочем столе и т.п.). Сам он почти никогда не меняется —
вся "тяжёлая" логика игры (Minecraft/core/моды/конфиги/запуск) живёт в
отдельном launcher.exe, который bootstrap проверяет и при необходимости
обновляет ПЕРЕД запуском.

Почему так, а не самообновление изнутри самого лаунчера (как было раньше):
когда программа пытается заменить сама себя, пока работает — приходится
городить cmd.exe-скрипты, ждать исчезновения PID, обходить блокировку файла
и т.д. Это была основная причина всех прошлых багов (зависания, битые
загрузки, бесконечный цикл обновлений). Здесь же в момент, когда bootstrap
качает и кладёт на место новый launcher.exe, тот попросту ещё не запущен —
никаких трюков не нужно, обычная замена файла.
"""

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import requests

# ---------- НАСТРОЙКИ ----------
APP_NAME = "EndyLauncher"
MANIFEST_URL = "https://raw.githubusercontent.com/mozalevart/client-em/refs/heads/main/manifest.json"
CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / ".endylauncher"
BIN_DIR = CONFIG_DIR / "bin"
LAUNCHER_EXE = BIN_DIR / "launcher.exe"
VERSION_FILE = BIN_DIR / "launcher-version.txt"
MIN_VALID_EXE_SIZE_MB = 15
REQUEST_TIMEOUT = 20
# ------------------------------


def get_resource_path(relative_path):
    """Путь к своим ресурсам (иконке) — что при обычном запуске, что из
    собранного PyInstaller onefile exe."""
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return str(Path(base_path) / relative_path)
    return str(Path(__file__).resolve().parent / relative_path)


def parse_version(version):
    version = str(version or "").strip().lstrip("v")
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts) if parts else (0,)


def is_newer_version(remote_version, local_version):
    return parse_version(remote_version) > parse_version(local_version)


def read_local_version():
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def write_local_version(version):
    try:
        VERSION_FILE.write_text(version, encoding="utf-8")
    except Exception:
        pass


def looks_like_valid_windows_exe(path, min_size_mb=MIN_VALID_EXE_SIZE_MB):
    """Грубая, но надёжная проверка "это не мусор": сигнатура PE-файла и
    разумный минимальный размер. Готовая сборка launcher.exe весит десятки
    мегабайт — заметно меньший файл почти наверняка означает оборванную
    закачку или битую сборку, и подсовывать его вместо рабочей версии нельзя."""
    try:
        if path.stat().st_size < min_size_mb * 1024 * 1024:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except Exception:
        return False


class BootstrapApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("380x150")
        self.root.resizable(False, False)
        self.root.configure(bg="#120E1C")

        try:
            icon_path = get_resource_path("assets/icon.ico")
            if Path(icon_path).exists():
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        # Окно по центру экрана
        self.root.update_idletasks()
        w, h = 380, 150
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(
            self.root, text=APP_NAME, font=("Segoe UI", 16, "bold"),
            fg="#F3EFFB", bg="#120E1C",
        ).pack(pady=(20, 6))

        self.status_var = tk.StringVar(value="Подготовка...")
        tk.Label(
            self.root, textvariable=self.status_var, font=("Segoe UI", 10),
            fg="#B9AED6", bg="#120E1C",
        ).pack(pady=(0, 12))

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Endy.Horizontal.TProgressbar",
            troughcolor="#251F40", background="#D9B24C", bordercolor="#120E1C",
            lightcolor="#D9B24C", darkcolor="#D9B24C",
        )
        self.progress = ttk.Progressbar(
            self.root, style="Endy.Horizontal.TProgressbar",
            length=320, mode="indeterminate",
        )
        self.progress.pack(pady=4)
        self.progress.start(12)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.closing = False

        # Вся сетевая работа — в фоновом потоке, чтобы окно не подвисало.
        threading.Thread(target=self.run, daemon=True).start()
        self.root.mainloop()

    def on_close_requested(self):
        # Пользователь закрыл окно вручную — просто выходим, ничего не ломая.
        self.closing = True
        os._exit(0)

    def set_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def set_progress_determinate(self, fraction):
        def _apply():
            if str(self.progress["mode"]) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=1.0)
            self.progress["value"] = fraction
        self.root.after(0, _apply)

    def fatal_error(self, message):
        def _show():
            messagebox.showerror(APP_NAME, message)
            os._exit(1)
        self.root.after(0, _show)

    def launch_and_exit(self):
        def _do():
            try:
                subprocess.Popen([str(LAUNCHER_EXE)], cwd=str(BIN_DIR))
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Не удалось запустить лаунчер: {e}")
                os._exit(1)
            os._exit(0)
        self.root.after(0, _do)

    # ---- Основная логика ----
    def run(self):
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        local_version = read_local_version()
        has_local_exe = LAUNCHER_EXE.exists()

        self.set_status("Проверка обновлений...")
        manifest = None
        try:
            response = requests.get(MANIFEST_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                manifest = data
        except Exception:
            manifest = None

        if manifest is None:
            # Нет сети / манифест недоступен. Если локальная копия уже есть —
            # не блокируем игрока, просто запускаем то, что есть.
            if has_local_exe:
                self.set_status("Нет соединения, запускаю текущую версию...")
                self.launch_and_exit()
            else:
                self.fatal_error(
                    "Не удалось подключиться к серверу обновлений, а локальной "
                    "копии лаунчера ещё нет. Проверьте интернет-соединение и "
                    "попробуйте снова."
                )
            return

        remote_version = str(manifest.get("version") or "").strip()
        download_url = str(manifest.get("download_url") or "").strip()

        needs_update = (
            not has_local_exe
            or not local_version
            or (remote_version and is_newer_version(remote_version, local_version))
        )

        if not needs_update:
            self.set_status("Актуальная версия, запускаю...")
            self.launch_and_exit()
            return

        if not download_url:
            # В манифесте нет ссылки — работать не с чем. Если есть локальная
            # копия — запускаем её, иначе явная ошибка.
            if has_local_exe:
                self.set_status("Манифест неполный, запускаю текущую версию...")
                self.launch_and_exit()
            else:
                self.fatal_error("В манифесте обновлений нет ссылки для скачивания.")
            return

        self.set_status(f"Загрузка версии {remote_version or ''}...")
        tmp_path = BIN_DIR / "launcher.exe.download"
        try:
            response = requests.get(download_url, stream=True, timeout=120)
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.set_progress_determinate(downloaded / total)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if has_local_exe:
                self.set_status("Не удалось скачать обновление, запускаю текущую версию...")
                self.launch_and_exit()
            else:
                self.fatal_error(
                    "Не удалось скачать лаунчер. Проверьте интернет-соединение "
                    "и попробуйте снова."
                )
            return

        if not looks_like_valid_windows_exe(tmp_path):
            tmp_path.unlink(missing_ok=True)
            if has_local_exe:
                self.set_status("Загруженный файл повреждён, запускаю текущую версию...")
                self.launch_and_exit()
            else:
                self.fatal_error(
                    "Загруженный файл лаунчера повреждён или неполный. "
                    "Попробуйте запустить EndyLauncher ещё раз."
                )
            return

        # Файл рабочий — можно спокойно заменить: launcher.exe в этот момент
        # гарантированно не запущен (мы его ещё не открывали).
        self.set_status("Установка обновления...")
        try:
            if LAUNCHER_EXE.exists():
                backup_path = BIN_DIR / "launcher.exe.bak"
                try:
                    if backup_path.exists():
                        backup_path.unlink()
                    LAUNCHER_EXE.replace(backup_path)
                except Exception:
                    pass
            tmp_path.replace(LAUNCHER_EXE)
            if remote_version:
                write_local_version(remote_version)
        except Exception as e:
            if has_local_exe:
                self.set_status("Не удалось установить обновление, запускаю текущую версию...")
                self.launch_and_exit()
            else:
                self.fatal_error(f"Не удалось установить лаунчер: {e}")
            return

        self.set_status("Готово, запускаю...")
        self.launch_and_exit()


if __name__ == "__main__":
    BootstrapApp()
