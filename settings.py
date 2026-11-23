#!/usr/bin/env python3
"""Системные настройки LisiOS: язык, скорость анимаций, обои, загрузочный логотип, адрес Lisi AI."""
import json
import os
import shutil
import subprocess
import sys

from PyQt6.QtWidgets import (QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSlider, QVBoxLayout, QWidget, QComboBox, QMessageBox)
from PyQt6.QtCore import Qt

HOME = os.path.expanduser("~")
USER_CFG = os.path.join(HOME, ".config/lisios/config.json")
SYS_CFG = "/etc/lisios/config.json"
ANIM_CONF = os.path.join(HOME, ".config/hypr/lisios-animations.conf")  # Hyprland до 0.57
ANIM_LUA = os.path.join(HOME, ".config/hypr/lisios-animations.lua")    # Hyprland 0.57+ (hyprland.conf там не читается)
WALL_DIR = os.path.join(HOME, ".config/lisios/wallpapers")

# базовые скорости Hyprland (в десятых долях секунды; меньше = быстрее)
BASE = [("windowsIn", 5, "pop, popin 80%"), ("windowsOut", 4, "smooth, popin 80%"), ("windowsMove", 4, "smooth"),
        ("fade", 5, "smooth"), ("border", 8, "smooth"), ("workspaces", 6, "smooth, slide"),
        ("specialWorkspace", 5, "smooth, slidevert")]

TR = {
    "ru": {"title": "Системные настройки", "lang": "Язык", "speed": "Скорость анимаций", "wall": "Обои рабочего стола",
           "boot": "Загрузочный логотип", "choose": "Выбрать…", "ai": "Адрес API Lisi AI", "save": "Применить",
           "saved": "Настройки применены. Язык приложений изменится после повторного входа.",
           "boot_ok": "Загрузочный логотип заменён.", "boot_err": "Не удалось заменить логотип"},
    "en": {"title": "System Settings", "lang": "Language", "speed": "Animation speed", "wall": "Desktop wallpaper",
           "boot": "Boot logo", "choose": "Choose…", "ai": "Lisi AI API address", "save": "Apply",
           "saved": "Settings applied. App language changes after you log in again.",
           "boot_ok": "Boot logo replaced.", "boot_err": "Could not replace the logo"},
}


def load():
    cfg = {}
    for p in (SYS_CFG, USER_CFG):
        try:
            cfg.update(json.load(open(p)))
        except (OSError, ValueError):
            pass
    return cfg


def write_animations(mult):
    lines = ["# Создано «Системными настройками». Скорость x%.2f" % mult, "animations {", "    enabled = true",
             "    bezier = smooth, 0.22, 1.0, 0.36, 1.0", "    bezier = pop, 0.34, 1.35, 0.64, 1.0"]
    for name, base, rest in BASE:
        lines.append("    animation = %s, 1, %.2f, %s" % (name, max(0.5, base / mult), rest))
    lines.append("}")
    os.makedirs(os.path.dirname(ANIM_CONF), exist_ok=True)
    open(ANIM_CONF, "w").write("\n".join(lines) + "\n")
    write_animations_lua(mult)


def write_animations_lua(mult):
    """То же самое в формате Lua для Hyprland 0.57+ (hl.curve / hl.animation)."""
    out = ["-- Создано «Системными настройками». Скорость x%.2f" % mult,
           'hl.curve("smooth", { type = "bezier", points = { {0.22, 1.0}, {0.36, 1.0} } })',
           'hl.curve("pop",    { type = "bezier", points = { {0.34, 1.35}, {0.64, 1.0} } })']
    for name, base, rest in BASE:
        parts = [p.strip() for p in rest.split(",", 1)]
        bez = parts[0]
        style = parts[1] if len(parts) > 1 else ""
        line = 'hl.animation({ leaf = "%s", enabled = true, speed = %.2f, bezier = "%s"' % (name, max(0.5, base / mult), bez)
        if style:
            line += ', style = "%s"' % style
        out.append(line + " })")
    open(ANIM_LUA, "w").write("\n".join(out) + "\n")


class Settings(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = load()
        self.lang = self.cfg.get("lang", "ru")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.l_lang, self.l_speed, self.l_wall, self.l_boot, self.l_ai = (QLabel() for _ in range(5))
        self.cb = QComboBox()
        self.cb.addItem("Русский", "ru")
        self.cb.addItem("English", "en")
        self.cb.setCurrentIndex(0 if self.lang == "ru" else 1)
        self.cb.currentIndexChanged.connect(self.on_lang)
        form.addRow(self.l_lang, self.cb)

        self.sl = QSlider(Qt.Orientation.Horizontal)
        self.sl.setRange(5, 30)  # 0.5x .. 3.0x
        self.sl.setValue(int(float(self.cfg.get("animation_speed", 1.0)) * 10))
        self.sv = QLabel()
        self.sl.valueChanged.connect(lambda v: self.sv.setText("x%.1f" % (v / 10)))
        self.sv.setText("x%.1f" % (self.sl.value() / 10))
        row = QHBoxLayout()
        row.addWidget(self.sl)
        row.addWidget(self.sv)
        form.addRow(self.l_speed, row)

        self.wall = QLineEdit(self.cfg.get("wallpaper", ""))
        self.b_wall = QPushButton()
        self.b_wall.clicked.connect(self.pick_wall)
        r = QHBoxLayout()
        r.addWidget(self.wall)
        r.addWidget(self.b_wall)
        form.addRow(self.l_wall, r)

        self.b_boot = QPushButton()
        self.b_boot.clicked.connect(self.pick_boot)
        form.addRow(self.l_boot, self.b_boot)

        self.ai = QLineEdit((self.cfg.get("ai") or {}).get("endpoint", ""))
        self.ai.setPlaceholderText("https://…")
        form.addRow(self.l_ai, self.ai)

        self.b_save = QPushButton()
        self.b_save.clicked.connect(self.save)
        lay.addWidget(self.b_save)
        self.retranslate()

    def t(self, k):
        return TR[self.lang][k]

    def retranslate(self):
        self.setWindowTitle(self.t("title"))
        self.l_lang.setText(self.t("lang"))
        self.l_speed.setText(self.t("speed"))
        self.l_wall.setText(self.t("wall"))
        self.l_boot.setText(self.t("boot"))
        self.l_ai.setText(self.t("ai"))
        self.b_wall.setText(self.t("choose"))
        self.b_boot.setText(self.t("choose"))
        self.b_save.setText(self.t("save"))

    def on_lang(self):
        self.lang = self.cb.currentData()
        self.retranslate()

    def pick_wall(self):
        f, _ = QFileDialog.getOpenFileName(self, self.t("wall"), HOME, "Images (*.png *.jpg *.jpeg *.webp)")
        if f:
            os.makedirs(WALL_DIR, exist_ok=True)
            dst = os.path.join(WALL_DIR, os.path.basename(f))
            shutil.copy(f, dst)  # копия, чтобы обои не пропали при удалении исходника
            self.wall.setText(dst)

    def pick_boot(self):
        f, _ = QFileDialog.getOpenFileName(self, self.t("boot"), HOME, "PNG (*.png)")
        if not f:
            return
        r = subprocess.run(["pkexec", "/usr/local/bin/lisios-set-boot-image", f], capture_output=True, text=True)
        if r.returncode == 0:
            QMessageBox.information(self, self.t("title"), self.t("boot_ok"))
        else:
            QMessageBox.warning(self, self.t("title"), self.t("boot_err") + ":\n" + (r.stderr or r.stdout))

    def save(self):
        user = {}
        try:
            user = json.load(open(USER_CFG))
        except (OSError, ValueError):
            pass
        mult = self.sl.value() / 10
        user.update({"lang": self.lang, "animation_speed": mult, "wallpaper": self.wall.text(),
                     "ai": {"endpoint": self.ai.text().strip(), "model": (self.cfg.get("ai") or {}).get("model", "")}})
        os.makedirs(os.path.dirname(USER_CFG), exist_ok=True)
        json.dump(user, open(USER_CFG, "w"), indent=2, ensure_ascii=False)
        write_animations(mult)
        subprocess.run(["hyprctl", "reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        QMessageBox.information(self, self.t("title"), self.t("saved"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Settings()
    w.show()
    sys.exit(app.exec())
