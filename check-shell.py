#!/usr/bin/env python3
"""Статическая проверка QML-оболочки LisiOS без Qt, Quickshell и Wayland.

Ловит именно ту ошибку, из-за которой оболочка не запускалась ("IpcHandler is not a type"):
тип Quickshell используется в файле, а нужный модуль в нём не импортирован.
Таблица типов составлена по исходникам Quickshell v0.3.2 (src/io, src/core, src/wayland, ...).

Использование:  python3 scripts/check-shell.py [каталог_оболочки]
Код возврата: 0 - ошибок нет, 1 - есть.
"""
import glob
import os
import re
import sys

DEFAULT_DIR = "profile/airootfs/usr/share/lisios/shell"

# тип/синглтон -> модуль, который нужно импортировать
NEEDS = {
    # Quickshell (core)
    "Scope": "Quickshell", "ShellRoot": "Quickshell", "Variants": "Quickshell",
    "PanelWindow": "Quickshell", "SystemClock": "Quickshell", "ScriptModel": "Quickshell",
    "DesktopEntries": "Quickshell", "ExclusionMode": "Quickshell",
    # Quickshell.Io
    "IpcHandler": "Quickshell.Io", "FileView": "Quickshell.Io",
    "Process": "Quickshell.Io", "StdioCollector": "Quickshell.Io",
    # Quickshell.Wayland
    "WlrLayershell": "Quickshell.Wayland", "WlrLayer": "Quickshell.Wayland",
    "WlrKeyboardFocus": "Quickshell.Wayland", "ToplevelManager": "Quickshell.Wayland",
    # остальное
    "Hyprland": "Quickshell.Hyprland",
    "IconImage": "Quickshell.Widgets",
    "NotificationServer": "Quickshell.Services.Notifications",
    "TextField": "QtQuick.Controls", "Slider": "QtQuick.Controls",
}
# «Quickshell.env / Quickshell.screens / Quickshell.execDetached / Quickshell.iconPath» - синглтон из core
NEEDS_SINGLETON_USE = {"Quickshell": "Quickshell"}


def strip(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"(?m)//.*$", "", s)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', s)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    files = sorted(glob.glob(os.path.join(root, "*.qml")))
    if not files:
        print("Нет .qml файлов в", root)
        return 1
    local_types = {os.path.splitext(os.path.basename(f))[0] for f in files}
    errors = 0
    for f in files:
        raw = open(f, encoding="utf-8").read()
        imports = set(re.findall(r"(?m)^\s*import\s+([A-Za-z0-9_.]+)", raw))
        code = strip(raw)
        used = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\s*\{", code))
        used |= set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\.[A-Za-z_]", code))
        for t in sorted(used):
            mod = NEEDS.get(t)
            if mod and t not in local_types and mod not in imports:
                print(f"ОШИБКА {os.path.basename(f)}: тип/синглтон {t} требует «import {mod}»")
                errors += 1
        # ссылки на локальные типы, которых нет в каталоге
        for t in sorted(re.findall(r"(?m)^\s*([A-Z][A-Za-z0-9_]*)\s*\{", code)):
            known = (t in local_types or t in NEEDS or t in {
                "Item", "Rectangle", "Text", "Image", "Row", "Column", "Repeater", "MouseArea",
                "Timer", "Translate", "NumberAnimation", "ColorAnimation", "ScriptAction",
                "SequentialAnimation", "ParallelAnimation", "PauseAnimation", "Behavior", "GridView", "ListView",
                "Component", "Connections", "Gradient", "GradientStop", "Scale", "Rotation"})
            if not known:
                print(f"ПРЕДУПРЕЖДЕНИЕ {os.path.basename(f)}: неизвестный тип {t} (нет такого файла и нет в таблице)")
    if "shell.qml" not in {os.path.basename(f) for f in files}:
        print("ОШИБКА: нет shell.qml")
        errors += 1
    print("Проверено файлов: %d, ошибок: %d" % (len(files), errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
