import customtkinter as ctk
import minecraft_launcher_lib
import subprocess
import threading
import os
import json
import sys
import socket
import requests
import shutil
import zipfile
import re
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, Toplevel, Label, IntVar, StringVar

# Set a default timeout for all requests used by this launcher and by minecraft_launcher_lib.
# This prevents hanging downloads when a server stalls or a connection drops.
DEFAULT_REQUEST_TIMEOUT = 30
_original_requests_get = requests.get
_original_session_request = requests.sessions.Session.request

def _requests_get_with_timeout(url, *args, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT)
    return _original_requests_get(url, *args, **kwargs)


def _session_request_with_timeout(self, method, url, *args, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT)
    return _original_session_request(self, method, url, *args, **kwargs)

requests.get = _requests_get_with_timeout
requests.sessions.Session.request = _session_request_with_timeout

# Дополнительный "предохранитель": глобальный таймаут на сокеты. Без него
# requests/urllib3 (в том числе внутри minecraft_launcher_lib, где мы не можем
# подставить свой timeout) может ждать ответ сервера бесконечно.
socket.setdefaulttimeout(60)

# ---------- НАСТРОЙКИ ----------
APP_NAME = "EndyLauncher"
MANIFEST_URL = "https://raw.githubusercontent.com/mozalevart/client-em/refs/heads/main/manifest.json"
SERVERS_URL = "https://github.com/mozalevart/client-em/raw/refs/heads/main/servers.dat"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), ".endylauncher")
CONFIG_PATH = os.path.join(CONFIG_DIR, "launcher-config.json")
DEFAULT_GAME_DIR = os.path.join(CONFIG_DIR, "game")
# Лог теперь всегда хранится в папке .endylauncher, а не в папке запуска игры,
# и перезаписывается заново при каждом старте лаунчера.
LOG_PATH = os.path.join(CONFIG_DIR, "launcher-log.txt")
# ------------------------------

# ---------- ЦВЕТОВАЯ СХЕМА: тёмная магия + техно-акценты ----------
BG = "#050816"
BG_PANEL = "#0A1228"
BG_CARD = "#111C33"
BG_CARD_ALT = "#16243F"
BORDER = "#2E3C5A"
TEXT = "#F7F3FF"
TEXT_MUTED = "#9AA8C7"
VIOLET = "#9B5CFF"
VIOLET_HOVER = "#7C3AED"
VIOLET_SOFT = "#23153E"
GOLD = "#F6C96B"
GOLD_HOVER = "#E0A83A"
GOLD_TEXT = "#231400"
DANGER = "#FF6B6B"
DANGER_HOVER = "#E85454"
SUCCESS = "#56E8B2"
FONT_FAMILY = "Segoe UI"
# ------------------------------

# Ссылки не должны попадать в видимый лог — только общие фразы.
_URL_PATTERN = re.compile(r"https?://\S+")

def strip_urls(text):
    return _URL_PATTERN.sub("[ссылка скрыта]", str(text))

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def make_panel(parent, **kwargs):
    kwargs.setdefault("corner_radius", 20)
    kwargs.setdefault("fg_color", BG_CARD)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", BORDER)
    return ctk.CTkFrame(parent, **kwargs)


def make_glow_button(parent, text, command, *, fg_color, hover_color, text_color, width=None, height=46):
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        width=width,
        fg_color=fg_color,
        hover_color=hover_color,
        text_color=text_color,
        corner_radius=16,
        font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
    )

# ---- Вспомогательная функция для получения общего ОЗУ ----
def get_total_ram_gb():
    try:
        import psutil
        total_bytes = psutil.virtual_memory().total
        return round(total_bytes / (1024 ** 3))
    except ImportError:
        pass

    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            memoryStatus = MEMORYSTATUSEX()
            memoryStatus.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memoryStatus)):
                total_bytes = memoryStatus.ullTotalPhys
                return round(total_bytes / (1024 ** 3))
        except:
            pass

    elif platform.system() == "Linux":
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = int(line.split()[1])
                        return round(total_kb / (1024 * 1024))
        except:
            pass

    print("⚠️ Не удалось определить объём ОЗУ. Используется значение по умолчанию 8 ГБ.")
    return 8

# ---- Класс тултипа ----
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind('<Enter>', self.show_tip)
        widget.bind('<Leave>', self.hide_tip)

    def show_tip(self, event):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert") if hasattr(self.widget, "bbox") else (0, 0, 0, 0)
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = Label(self.tip_window, text=self.text, justify='left',
                      background="#2b2b2b", foreground="#f2f2f2", relief='solid', borderwidth=1,
                      padx=8, pady=4, font=(FONT_FAMILY, 10, "normal"))
        label.pack()

    def hide_tip(self, event):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

# ---- Окно настроек (модальное) ----
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, launcher):
        super().__init__(parent)
        self.launcher = launcher
        self.parent = parent
        self.title(f"{APP_NAME} — Настройки")
        self.geometry("470x540")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        self.transient(parent)
        self.grab_set()

        self.max_ram = launcher.max_ram_gb
        self.ram_var = IntVar(value=int(launcher.ram_var.get()))
        self.dir_var = StringVar(value=launcher.dir_var.get())

        header = make_panel(self, height=110)
        header.configure(fg_color=BG_CARD_ALT)
        header.pack(padx=22, pady=(20, 14), fill="x")
        ctk.CTkLabel(
            header,
            text="⚙ Настройки лаунчера",
            font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            header,
            text="Настройте память, папку установки и базовые параметры запуска",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_MUTED,
            wraplength=400,
        ).pack(anchor="w", padx=18, pady=(0, 16))

        frame_ram = make_panel(self)
        frame_ram.pack(pady=8, padx=22, fill="x")
        header_ram = ctk.CTkFrame(frame_ram, fg_color="transparent")
        header_ram.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            header_ram,
            text="Выделяемая память",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")
        self.ram_value_label = ctk.CTkLabel(
            header_ram,
            text=f"{int(self.ram_var.get())} ГБ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=GOLD,
        )
        self.ram_value_label.pack(side="right")

        self.ram_slider = ctk.CTkSlider(
            frame_ram,
            from_=1,
            to=self.max_ram,
            number_of_steps=max(1, self.max_ram - 1),
            variable=self.ram_var,
            command=self.update_ram_label,
            progress_color=VIOLET,
            button_color=GOLD,
            button_hover_color=GOLD_HOVER,
            height=10,
        )
        self.ram_slider.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(
            frame_ram,
            text=f"Максимум: {self.max_ram} ГБ (75% от общего ОЗУ)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
        ).pack(padx=16, pady=(0, 14), anchor="w")

        frame_dir = make_panel(self)
        frame_dir.pack(pady=8, padx=22, fill="x")
        ctk.CTkLabel(
            frame_dir,
            text="Папка с игрой",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=16, pady=(14, 6))
        entry_row = ctk.CTkFrame(frame_dir, fg_color="transparent")
        entry_row.pack(padx=16, pady=(0, 14), fill="x")
        ctk.CTkEntry(entry_row, textvariable=self.dir_var, fg_color=BG_PANEL, border_color=BORDER, height=38).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            entry_row,
            text="Обзор",
            width=82,
            height=38,
            command=self.browse_dir,
            fg_color=VIOLET,
            hover_color=VIOLET_HOVER,
        ).pack(side="right")

        frame_danger = make_panel(self, fg_color=BG_CARD_ALT)
        frame_danger.pack(pady=8, padx=22, fill="x")
        btn_reinstall = ctk.CTkButton(
            frame_danger,
            text="🗑  Переустановить игру",
            command=self.reinstall,
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            height=40,
        )
        btn_reinstall.pack(pady=14, padx=16, fill="x")
        ToolTip(btn_reinstall, "Удаляет все файлы игры (моды, ядро, конфиги)\nи переустанавливает заново при следующем запуске.")

        ctk.CTkButton(
            self,
            text="Сохранить настройки",
            command=self.save_settings,
            height=44,
            fg_color=GOLD,
            hover_color=GOLD_HOVER,
            text_color=GOLD_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            corner_radius=12,
        ).pack(pady=(14, 20), padx=22, fill="x")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def update_ram_label(self, value):
        # round() вместо int() — иначе плавающая точка (например 3.999999)
        # обрезалась бы вниз и подпись "отставала" бы от реального положения ползунка.
        snapped = int(round(float(value)))
        snapped = max(1, min(self.max_ram, snapped))

        # Явно доводим сам слайдер до целого шага, чтобы движение
        # воспринималось прерывисто (по 1 ГБ), а не как плавная анимация.
        if snapped != self.ram_var.get():
            self.ram_var.set(snapped)
        self.ram_slider.set(snapped)

        self.ram_value_label.configure(text=f"{snapped} ГБ")
        self.update_idletasks()

    def browse_dir(self):
        dir_selected = filedialog.askdirectory(title="Выберите папку для установки игры")
        if dir_selected:
            self.dir_var.set(dir_selected)

    def reinstall(self):
        if messagebox.askyesno("Переустановка", "Вы уверены, что хотите удалить все файлы игры и переустановить их заново?\n"
                                                "Это удалит моды, ядро и конфиги (но сохранит ваши настройки лаунчера)."):
            directory = self.launcher.dir_var.get()
            for folder in ["versions", "mods", "config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks"]:
                folder_path = os.path.join(directory, folder)
                if os.path.exists(folder_path):
                    shutil.rmtree(folder_path)
                    self.launcher.log(f"Удалена папка: {folder}")
            for ver_file in ["minecraft_version.txt", "core_version.txt", "mods_version.txt", "config_version.txt"]:
                ver_path = os.path.join(directory, ver_file)
                if os.path.exists(ver_path):
                    os.remove(ver_path)
                    self.launcher.log(f"Удалён файл версии: {ver_file}")
            self.launcher.log("Переустановка завершена. При следующем запуске игра будет переустановлена.")
            messagebox.showinfo("Переустановка", "Все файлы игры удалены. Нажмите 'Играть' для полной переустановки.")

    def save_settings(self):
        self.launcher.ram_var.set(int(self.ram_var.get()))
        self.launcher.dir_var.set(self.dir_var.get())
        self.launcher.save_config()
        self.on_close()

    def on_close(self):
        self.grab_release()
        self.parent.settings_window = None
        self.destroy()

# ---- Основной класс лаунчера ----
class Launcher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("560x760")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        self.config = self.load_config()
        self.settings_window = None

        default_dir = self.config.get("directory", DEFAULT_GAME_DIR)
        self.dir_var = ctk.StringVar(value=default_dir)
        self.nickname_var = ctk.StringVar(value=self.config.get("nickname", ""))
        self.password_var = ctk.StringVar(value=self.config.get("password", ""))
        self.log_file_path = LOG_PATH

        # Лог перезаписывается заново при каждом запуске лаунчера.
        try:
            with open(self.log_file_path, "w", encoding="utf-8") as f:
                f.write(f"=== {APP_NAME} — сессия от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            pass

        total_ram = get_total_ram_gb()
        self.max_ram_gb = max(1, int(total_ram * 0.75))
        if self.max_ram_gb < 1:
            self.max_ram_gb = 1

        half_ram = int(total_ram * 0.5)
        default_ram = max(2, half_ram)
        if default_ram > self.max_ram_gb:
            default_ram = self.max_ram_gb

        saved_ram = self.config.get("ram", default_ram)
        if saved_ram > self.max_ram_gb:
            saved_ram = self.max_ram_gb
        self.ram_var = ctk.IntVar(value=saved_ram)

        self.create_widgets()
        Path(self.dir_var.get()).mkdir(parents=True, exist_ok=True)

        self.launch_thread = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log(f"Обнаружено ОЗУ: {total_ram} ГБ")
        self.log(f"Выделено памяти: {self.ram_var.get()} ГБ (максимум {self.max_ram_gb} ГБ)")

    def create_widgets(self):
        hero_wrapper = ctk.CTkFrame(
            self,
            fg_color="transparent",
            corner_radius=24,
            border_width=2,
            border_color="#4A2A7A",
        )
        hero_wrapper.pack(padx=24, pady=(24, 16), fill="x")

        hero = make_panel(hero_wrapper, height=150)
        hero.configure(fg_color=BG_CARD_ALT, border_color="#B987FF")
        hero.pack(padx=2, pady=2, fill="x")

        hero_top = ctk.CTkFrame(hero, fg_color="transparent")
        hero_top.pack(fill="x", padx=20, pady=(16, 6))
        ctk.CTkLabel(
            hero_top,
            text="Endy",
            font=ctk.CTkFont(family=FONT_FAMILY, size=30, weight="bold"),
            text_color=VIOLET,
        ).pack(side="left")
        ctk.CTkLabel(
            hero_top,
            text="Launcher",
            font=ctk.CTkFont(family=FONT_FAMILY, size=30, weight="bold"),
            text_color=GOLD,
        ).pack(side="left", padx=(4, 0))

        badge = ctk.CTkFrame(hero_top, fg_color=VIOLET_SOFT, corner_radius=999, border_width=1, border_color="#F2D27A")
        badge.pack(side="right")
        ctk.CTkLabel(
            badge,
            text="⚡ Быстрый старт",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=GOLD,
            padx=10,
            pady=4,
        ).pack()

        ctk.CTkFrame(hero, height=2, fg_color=GOLD, corner_radius=999).pack(fill="x", padx=20, pady=(2, 6))
        ctk.CTkFrame(hero, height=1, fg_color=VIOLET, corner_radius=999).pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(
            hero,
            text="Лаунчер для запуска и обновления сборки с минимальными лишними действиями.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=500,
        ).pack(anchor="w", padx=20, pady=(0, 18))

        card = make_panel(self)
        card.pack(padx=24, fill="x")

        ctk.CTkLabel(card, text="Никнейм", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkEntry(card, textvariable=self.nickname_var, height=38, fg_color=BG_PANEL, border_color=BORDER).pack(padx=20, fill="x")

        ctk.CTkLabel(card, text="Пароль", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(14, 6))
        ctk.CTkEntry(card, textvariable=self.password_var, show="*", height=38, fg_color=BG_PANEL, border_color=BORDER).pack(padx=20, fill="x")

        ctk.CTkLabel(
            card,
            text=("Пароль проверяется только при входе на сервер. Играете здесь впервые — "
                  "просто придумайте любой пароль и запомните его: в следующий раз вводите тот же, "
                  "чтобы никто другой не смог зайти под вашим ником."),
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=480,
        ).pack(anchor="w", padx=20, pady=(8, 0))

        ctk.CTkLabel(card, text="Папка с игрой", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(14, 6))
        frame_dir = ctk.CTkFrame(card, fg_color="transparent")
        frame_dir.pack(pady=(0, 18), padx=20, fill="x")
        ctk.CTkEntry(frame_dir, textvariable=self.dir_var, height=38, fg_color=BG_PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            frame_dir,
            text="Обзор",
            width=82,
            height=38,
            command=self.choose_directory,
            fg_color=VIOLET,
            hover_color=VIOLET_HOVER,
        ).pack(side="right", padx=(10, 0))

        self.progress = ctk.CTkProgressBar(self, width=480, height=8, progress_color=GOLD, bg_color=BG_PANEL, corner_radius=999)
        self.progress.pack(pady=(18, 6), padx=24)
        self.progress.set(0)

        frame_buttons = ctk.CTkFrame(self, fg_color="transparent")
        frame_buttons.pack(pady=12, fill="x", padx=24)
        self.launch_btn = make_glow_button(
            frame_buttons,
            "ИГРАТЬ",
            self.on_launch,
            fg_color=GOLD,
            hover_color=GOLD_HOVER,
            text_color=GOLD_TEXT,
            width=185,
        )
        self.launch_btn.pack(side="left")
        ctk.CTkButton(
            frame_buttons,
            text="Настройки",
            command=self.open_settings,
            height=46,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            width=145,
            fg_color=VIOLET,
            hover_color=VIOLET_HOVER,
            corner_radius=16,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            self,
            height=52,
            state="normal",
            corner_radius=16,
            fg_color=BG_PANEL,
            border_color=BORDER,
            border_width=1,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT,
        )
        self.log_box.pack(pady=(10, 18), padx=24, fill="x")
        self.log_box.insert("end", "Ожидание запуска...")
        self.log_box.configure(state="disabled")

    def log(self, message):
        # Ссылки не должны попадать в видимый лог — заменяем их на общую фразу.
        safe_message = strip_urls(message)
        timestamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {safe_message}"
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", safe_message)
        self.log_box.configure(state="disabled")
        self.update_idletasks()
        print(timestamped)
        sys.stdout.flush()
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(timestamped + "\n")
        except Exception:
            pass

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_config(self):
        config = {
            "nickname": self.nickname_var.get(),
            "password": self.password_var.get(),
            "directory": self.dir_var.get(),
            "ram": self.ram_var.get()
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        self.log("Настройки сохранены.")

        password = self.password_var.get().strip()
        password_file = os.path.join(self.dir_var.get(), ".nl_password")
        if password:
            with open(password_file, "w", encoding="utf-8") as f:
                f.write(password)
            self.log("Пароль сохранён.")
        else:
            if os.path.exists(password_file):
                os.remove(password_file)

    def choose_directory(self):
        dir_selected = filedialog.askdirectory(title="Выберите папку для установки игры")
        if dir_selected:
            self.dir_var.set(dir_selected)
            Path(dir_selected).mkdir(parents=True, exist_ok=True)
            self.log(f"Выбрана папка: {dir_selected}")
            self.save_config()

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.focus()
            self.settings_window.grab_set()
        else:
            self.settings_window = SettingsWindow(self, self)

    def on_launch(self):
        nickname = self.nickname_var.get().strip()
        if not nickname:
            messagebox.showerror("Ошибка", "Введите никнейм!")
            return

        password = self.password_var.get().strip()
        if not password:
            messagebox.showerror("Ошибка", "Введите пароль! Если играете впервые — просто придумайте любой и запомните его.")
            return

        directory = self.dir_var.get().strip()
        if not directory:
            messagebox.showerror("Ошибка", "Выберите папку для игры!")
            return

        Path(directory).mkdir(parents=True, exist_ok=True)
        self.save_config()

        self.launch_btn.configure(state="disabled", text="ЗАПУСК...")
        self.progress.set(0)
        self.log("Подготовка запуска...")

        thread = threading.Thread(target=self.launch_game, args=(nickname, directory))
        thread.daemon = True
        self.launch_thread = thread
        thread.start()

    def on_close(self):
        if self.launch_thread is not None and self.launch_thread.is_alive():
            self.log("Закрытие лаунчера во время установки. Принудительный выход...")
            os._exit(0)
        self.destroy()

    # ---- Вспомогательные методы (остаются без изменений) ----
    def check_java_version(self):
        try:
            output = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT, text=True)
            match = re.search(r'version "(\d+)\.', output)
            if match:
                major = int(match.group(1))
                return major >= 21
            return False
        except:
            return False

    def get_manifest(self):
        self.log("Загрузка манифеста...")
        try:
            resp = requests.get(MANIFEST_URL, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"Ошибка загрузки манифеста: {e}")
            raise Exception("Не удалось загрузить манифест. Проверьте интернет-соединение.")

    def clean_component(self, directory, component_type, mc_version=None):
        if component_type == "minecraft":
            versions_dir = os.path.join(directory, "versions")
            if os.path.exists(versions_dir):
                self.log("Удаление папки versions (для обновления Minecraft)...")
                shutil.rmtree(versions_dir)

        elif component_type == "core":
            if mc_version is None:
                mc_version = "1.21.1"
            versions_dir = os.path.join(directory, "versions")
            if os.path.exists(versions_dir):
                for folder in os.listdir(versions_dir):
                    if folder.startswith(f"{mc_version}-neoforge") or folder.startswith("neoforge-"):
                        folder_path = os.path.join(versions_dir, folder)
                        self.log(f"Удаление старой версии NeoForge: {folder}")
                        shutil.rmtree(folder_path)

        elif component_type == "mods":
            mods_dir = os.path.join(directory, "mods")
            if os.path.exists(mods_dir):
                self.log("Удаление старых модов...")
                shutil.rmtree(mods_dir)

        elif component_type == "config":
            pass

    def download_and_extract_archive(self, url, target_dir, temp_name, component_label="файл"):
        zip_path = os.path.join(target_dir, temp_name)
        self.log(f"Скачивание: {component_label}...")
        try:
            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            percent = downloaded / total_size
                            self.progress.set(percent)
                            self.update_idletasks()
            self.progress.set(1.0)
            self.log("Скачивание завершено. Распаковка...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            os.remove(zip_path)
            self.progress.set(0)
            self.log("Распаковка завершена.")
        except Exception as e:
            self.log(f"Ошибка при скачивании/распаковке {component_label}: {e}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            raise

    def download_servers(self, directory):
        servers_path = os.path.join(directory, "servers.dat")
        self.log("Обновление списка серверов...")
        try:
            response = requests.get(SERVERS_URL, stream=True, timeout=30)
            response.raise_for_status()
            with open(servers_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            self.log("Список серверов обновлён.")
        except Exception as e:
            self.log(f"Не удалось обновить список серверов: {e}")

    def write_default_language(self, directory):
        """Создаёт options.txt с русским языком, но только если файла ещё нет —
        то есть это самая первая установка игры и настройки клиента ещё не тронуты.
        Если файл уже существует, ничего не трогаем, чтобы не сбрасывать выбор игрока."""
        options_path = os.path.join(directory, "options.txt")
        if not os.path.exists(options_path):
            try:
                with open(options_path, "w", encoding="utf-8") as f:
                    f.write("lang:ru_ru\n")
                self.log("Установлен язык по умолчанию: русский")
            except Exception as e:
                self.log(f"Не удалось создать options.txt: {e}")

    def launch_game(self, nickname, directory):
        try:
            java_path = os.path.join(directory, "java-runtime-delta", "bin", "java.exe")

            self.download_servers(directory)

            manifest = self.get_manifest()
            components = manifest.get("components", {})

            mc_version = components.get("minecraft", {}).get("version", "1.21.1")
            self.log(f"Версия Minecraft: {mc_version}")

            # Minecraft
            mc_version_file = os.path.join(directory, "minecraft_version.txt")
            current_mc = None
            if os.path.exists(mc_version_file):
                with open(mc_version_file, "r") as f:
                    current_mc = f.read().strip()
            if current_mc != mc_version:
                self.log(f"Обновление Minecraft с {current_mc} до {mc_version}")
                self.clean_component(directory, "minecraft")
                minecraft_launcher_lib.install.install_minecraft_version(mc_version, directory)
                with open(mc_version_file, "w") as f:
                    f.write(mc_version)
                self.log(f"Minecraft {mc_version} установлен.")
            else:
                self.log("Minecraft актуален.")

            # Core
            if "core" in components:
                comp = components["core"]
                version = comp.get("version")
                url = comp.get("url")
                clean = comp.get("clean", True)
                if version and url:
                    core_version_file = os.path.join(directory, "core_version.txt")
                    current_core = None
                    if os.path.exists(core_version_file):
                        with open(core_version_file, "r") as f:
                            current_core = f.read().strip()
                    if current_core != version:
                        self.log(f"Обновление ядра с {current_core} до {version}")
                        if clean:
                            self.clean_component(directory, "core", mc_version)
                        self.download_and_extract_archive(url, directory, "core_temp.zip", "core")
                        with open(core_version_file, "w") as f:
                            f.write(version)
                        self.log("Ядро установлено.")
                    else:
                        self.log("Ядро актуально.")

            # Русский язык по умолчанию при первой установке
            self.write_default_language(directory)

            # Моды
            if "mods" in components:
                comp = components["mods"]
                version = comp.get("version")
                url = comp.get("url")
                clean = comp.get("clean", True)
                if version and url:
                    mods_version_file = os.path.join(directory, "mods_version.txt")
                    current_mods = None
                    if os.path.exists(mods_version_file):
                        with open(mods_version_file, "r") as f:
                            current_mods = f.read().strip()
                    if current_mods != version:
                        self.log(f"Обновление модов с {current_mods} до {version}")
                        if clean:
                            self.clean_component(directory, "mods")
                        self.download_and_extract_archive(url, directory, "mods_temp.zip", "mods")
                        with open(mods_version_file, "w") as f:
                            f.write(version)
                        self.log("Моды установлены.")
                    else:
                        self.log("Моды актуальны.")

            # Конфиги
            if "config" in components:
                comp = components["config"]
                version = comp.get("version")
                url = comp.get("url")
                if version and url:
                    config_version_file = os.path.join(directory, "config_version.txt")
                    current_config = None
                    if os.path.exists(config_version_file):
                        with open(config_version_file, "r") as f:
                            current_config = f.read().strip()
                    if current_config != version:
                        self.log(f"Обновление конфигов с {current_config} до {version}")
                        self.download_and_extract_archive(url, directory, "config_temp.zip", "config")
                        with open(config_version_file, "w") as f:
                            f.write(version)
                        self.log("Конфиги обновлены.")
                    else:
                        self.log("Конфиги актуальны.")

            # Поиск NeoForge
            versions_dir = os.path.join(directory, "versions")
            neoforge_id = None
            if os.path.exists(versions_dir):
                for folder in os.listdir(versions_dir):
                    if folder.startswith(f"neoforge-") or folder.startswith(f"{mc_version}-neoforge"):
                        neoforge_id = folder
                        break
            if not neoforge_id:
                raise Exception("Не найдена версия NeoForge в папке versions")

            # Проверка Java — теперь ПОСЛЕ установки core, когда java-runtime-delta
            # уже должна быть на месте (раньше проверка шла до скачивания core.zip,
            # поэтому всегда падала на первой установке)
            if not os.path.exists(java_path):
                if not self.check_java_version():
                    msg = ("Не найдена встроенная Java и системная Java версии 21+.\n"
                           "Убедитесь, что core.zip содержит папку java-runtime-delta, "
                           "либо установите Java 21 вручную.")
                    self.log(f"ОШИБКА: {msg}")
                    messagebox.showerror("Ошибка", msg)
                    return
                self.log("Встроенная Java не найдена, будет использована системная Java.")

            # Запуск
            self.log(f"Запуск Minecraft (версия {neoforge_id})...")
            options = minecraft_launcher_lib.utils.generate_test_options()
            options["username"] = nickname
            ram_gb = int(self.ram_var.get())
            options["jvmArguments"] = [f"-Xmx{ram_gb}G", f"-Xms{max(1, ram_gb // 2)}G"]
            self.log(f"JVM-аргументы: -Xmx{ram_gb}G -Xms{max(1, ram_gb // 2)}G")

            # Автоподключение к серверу при входе (QuickPlay, MC 1.20.2+)
            server_info = manifest.get("server")
            if server_info and server_info.get("ip"):
                server_ip = server_info["ip"]
                server_port = server_info.get("port", 25565)
                options["quickPlayMultiplayer"] = f"{server_ip}:{server_port}"
                options["server"] = server_ip
                options["port"] = str(server_port)
                self.log("Автоподключение к серверу настроено.")
            else:
                self.log("Автоподключение к серверу не настроено (нет данных в манифесте).")

            minecraft_command = minecraft_launcher_lib.command.get_minecraft_command(
                neoforge_id, directory, options
            )

            args_file = os.path.join(directory, "temp_args.txt")
            with open(args_file, "w", encoding="utf-8") as f:
                f.write(" ".join(minecraft_command[1:]))

            if os.path.exists(java_path):
                cmd = [java_path, f"@{args_file}"]
            else:
                cmd = ["java", f"@{args_file}"]

            self.log("Запуск игры...")
            subprocess.Popen(cmd, cwd=directory, shell=True)
            self.log("Игра запущена! Можете закрыть лаунчер.")

        except Exception as e:
            self.log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
            messagebox.showerror("Ошибка", str(e))
        finally:
            self.launch_btn.configure(state="normal", text="ИГРАТЬ")
            self.progress.set(0)

if __name__ == "__main__":
    app = Launcher()
    app.mainloop()