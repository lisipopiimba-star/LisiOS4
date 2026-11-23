#!/usr/bin/env python3
"""Графический установщик LisiOS (PyQt6).

Экраны: приветствие -> лицензия -> диск -> пользователь -> драйверы -> установка -> завершение.
Вся работа с диском выполняется отдельным процессом `sudo lisios-install-cli`.
"""
import json
import os
import re
import subprocess
import sys

from PyQt6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSequentialAnimationGroup,
                          Qt, QThread, QTimer, pyqtSignal, QPoint)
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
                             QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QRadioButton, QMessageBox)

LOGO = "/usr/share/lisios/branding/logo.png"
LICENSE = "/usr/share/lisios/LICENSE.txt"
CLI = "lisios-install-cli"
DRY = os.environ.get("LISIOS_DRY_RUN") == "1"

T = {
    "ru": {
        "title": "Установка LisiOS", "next": "Далее", "back": "Назад", "install": "Установить",
        "welcome_h": "Добро пожаловать в LisiOS", "welcome_p": "Этот мастер установит LisiOS на ваш компьютер.\nВыберите язык системы:",
        "try": "Попробовать LisiOS без установки", "skip_install": "Пропустить установку на диск", "skip_confirm": "LisiOS продолжит работать с загрузочной флешки. Внутренние диски не будут изменены. После извлечения USB или выключения live-сессия завершится. Продолжить?", "skip_yes": "Остаться в live-режиме",
        "lic_h": "Лицензионное соглашение", "lic_accept": "Я принимаю условия лицензионного соглашения",
        "disk_h": "Выбор диска", "disk_p": "Выберите диск для установки. Система будет установлена только на него — остальные диски не затрагиваются.",
        "disk_none": "Подходящие диски не найдены", "disk_erase": "Я понимаю, что ВСЕ данные на выбранном диске будут удалены",
        "disk_win": "⚠ На этом диске найден Windows. Он будет УДАЛЁН. Чтобы сохранить Windows, выберите другой диск или вернитесь и закройте установщик.",
        "disk_live": "установочный носитель", "disk_mounted": "используется системой", "disk_small": "слишком мал (нужно от 16 ГБ)",
        "user_h": "Пользователь", "fullname": "Ваше имя", "username": "Имя пользователя (латиница)", "password": "Пароль",
        "password2": "Повторите пароль", "hostname": "Имя компьютера", "timezone": "Часовой пояс",
        "autologin": "Входить автоматически", "err_pw": "Пароли не совпадают или короче 4 символов",
        "err_user": "Имя пользователя: латиница в нижнем регистре, цифры, _ и -",
        "drv_h": "Драйверы и компоненты", "drv_req": "Устанавливаются обязательно",
        "drv_wifi": "Wi-Fi (NetworkManager, прошивки)", "drv_bt": "Bluetooth (BlueZ)", "drv_sys": "Системные компоненты, графика Intel/AMD, звук",
        "drv_opt": "Дополнительно", "drv_wine": "Wine — запуск Windows-приложений (обязательно)", "drv_steam": "Поддержка Steam и игр (без установки клиента Steam)", "drv_nvidia": "Драйвер NVIDIA (проприетарный, нужен интернет)",
        "drv_nvidia_legacy": "Драйвер NVIDIA — ваша видеокарта старая, будет использован открытый драйвер nouveau",
        "drv_print": "Печать (CUPS, нужен интернет)", "drv_codecs": "Мультимедиа-кодеки (нужен интернет)",
        "net_ok": "Интернет: подключён", "net_no": "Интернет: нет подключения (дополнительные драйверы будут пропущены)",
        "wifi_btn": "Настроить Wi-Fi", "detected": "Обнаружено", "mode": "Режим загрузки",
        "inst_h": "Установка LisiOS", "inst_details": "Подробности", "inst_start": "Подготовка…",
        "done_h": "Загрузка завершена!", "done_p": "LisiOS успешно установлена. Нажмите кнопку, чтобы перезагрузить компьютер и войти в систему. Перед загрузкой извлеките установочную флешку.",
        "done_btn": "Перезагрузить и войти", "err_h": "Установка не удалась", "close": "Закрыть",
        "dry_note": "ТЕСТОВЫЙ РЕЖИМ: диск не изменяется",
    },
    "en": {
        "title": "LisiOS Setup", "next": "Next", "back": "Back", "install": "Install",
        "welcome_h": "Welcome to LisiOS", "welcome_p": "This wizard will install LisiOS on your computer.\nChoose the system language:",
        "try": "Try LisiOS without installing", "skip_install": "Skip disk installation", "skip_confirm": "LisiOS will keep running from the USB drive. No internal disk will be changed. Removing the USB drive or shutting down will end this live session. Continue?", "skip_yes": "Stay in live mode",
        "lic_h": "License agreement", "lic_accept": "I accept the terms of the license agreement",
        "disk_h": "Choose a disk", "disk_p": "Select the disk to install to. LisiOS is installed only on it — other disks are not touched.",
        "disk_none": "No suitable disks found", "disk_erase": "I understand that ALL data on the selected disk will be erased",
        "disk_win": "⚠ Windows was found on this disk. It will be ERASED. To keep Windows, pick another disk or close the installer.",
        "disk_live": "installation media", "disk_mounted": "in use by the system", "disk_small": "too small (16 GB minimum)",
        "user_h": "User", "fullname": "Your name", "username": "Username (lowercase latin)", "password": "Password",
        "password2": "Repeat password", "hostname": "Computer name", "timezone": "Time zone",
        "autologin": "Log in automatically", "err_pw": "Passwords differ or are shorter than 4 characters",
        "err_user": "Username: lowercase latin letters, digits, _ and -",
        "drv_h": "Drivers and components", "drv_req": "Always installed",
        "drv_wifi": "Wi-Fi (NetworkManager, firmware)", "drv_bt": "Bluetooth (BlueZ)", "drv_sys": "System components, Intel/AMD graphics, audio",
        "drv_opt": "Optional", "drv_wine": "Wine — run Windows applications (required)", "drv_steam": "Steam and game runtime support (Steam client is not installed)", "drv_nvidia": "NVIDIA driver (proprietary, needs internet)",
        "drv_nvidia_legacy": "NVIDIA driver — your GPU is old, the open nouveau driver will be used",
        "drv_print": "Printing (CUPS, needs internet)", "drv_codecs": "Multimedia codecs (needs internet)",
        "net_ok": "Internet: connected", "net_no": "Internet: not connected (optional drivers will be skipped)",
        "wifi_btn": "Set up Wi-Fi", "detected": "Detected", "mode": "Boot mode",
        "inst_h": "Installing LisiOS", "inst_details": "Details", "inst_start": "Preparing…",
        "done_h": "Download complete!", "done_p": "LisiOS was installed successfully. Press the button to restart and enter the system. Remove the installation USB before booting.",
        "done_btn": "Restart and enter", "err_h": "Installation failed", "close": "Close",
        "dry_note": "TEST MODE: the disk is not modified",
    },
}

QSS = """
* { font-family: 'Inter', 'Noto Sans', sans-serif; color: #f2f2f7; font-size: 15px; }
QWidget#root { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #090706, stop:1 #1b1008); }
QFrame#card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); border-radius: 22px; }
QLabel#h1 { font-size: 30px; font-weight: 700; }
QLabel#muted { color: #a1a1b5; }
QLabel#warn { color: #ffb4a8; }
QLabel#err { color: #ff8a80; }
QPushButton { background: rgba(255,255,255,0.10); border: none; border-radius: 12px; padding: 10px 22px; }
QPushButton:hover { background: rgba(255,255,255,0.18); }
QPushButton:disabled { color: #6b6b80; background: rgba(255,255,255,0.04); }
QPushButton#primary { background: #f07812; font-weight: 600; }
QPushButton#primary:hover { background: #ff922e; }
QPushButton#primary:disabled { background: #573019; color: #8a86a3; }
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QListWidget {
  background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 8px; }
QListWidget::item { padding: 10px; border-radius: 8px; }
QListWidget::item:selected { background: rgba(240,120,18,0.42); }
QListWidget::item:disabled { color: #6b6b80; }
QProgressBar { background: rgba(255,255,255,0.10); border: none; border-radius: 8px; height: 16px; text-align: center; }
QProgressBar::chunk { background: #f07812; border-radius: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px; }
"""


def human(n):
    return f"{n / 1024**3:.0f} GB" if n < 1024**4 else f"{n / 1024**4:.1f} TB"


class Worker(QThread):
    progress = pyqtSignal(int, str, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        cmd = ["sudo", "-n", CLI, "--config-stdin"]
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            p.stdin.write(json.dumps(self.cfg))
            p.stdin.close()
            err = None
            for line in p.stdout:
                line = line.strip()
                try:
                    ev = json.loads(line)
                except ValueError:
                    self.progress.emit(-1, "log", line)
                    continue
                if ev["step"] == "error":
                    err = ev["message"]
                self.progress.emit(ev["percent"], ev["step"], ev["message"])
            rc = p.wait()
            if rc == 0:
                self.finished_ok.emit()
            else:
                self.failed.emit(err or f"код {rc}")
        except Exception as e:  # noqa
            self.failed.emit(str(e))


class Installer(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.lang = "ru"
        self.state = {"disk": None, "hw": {}}
        self.disks = []
        self.setWindowTitle("LisiOS Installer")
        self.setStyleSheet(QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        head = QHBoxLayout()
        self.logo = QLabel()
        pm = QPixmap(LOGO)
        if not pm.isNull():
            self.logo.setPixmap(pm.scaledToHeight(44, Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo.setText("LisiOS")
        self.title = QLabel()
        self.title.setObjectName("muted")
        head.addWidget(self.logo)
        head.addSpacing(12)
        head.addWidget(self.title)
        head.addStretch()
        self.dry_label = QLabel()
        self.dry_label.setObjectName("warn")
        head.addWidget(self.dry_label)
        outer.addLayout(head)

        mid = QHBoxLayout()
        mid.addStretch()
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(820)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(36, 32, 36, 28)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.btn_back = QPushButton()
        self.btn_next = QPushButton()
        self.btn_next.setObjectName("primary")
        self.btn_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.btn_next.clicked.connect(self.on_next)
        nav.addWidget(self.btn_back)
        nav.addStretch()
        nav.addWidget(self.btn_next)
        cl.addLayout(nav)
        mid.addWidget(self.card)
        mid.addStretch()
        outer.addLayout(mid, 1)

        self.build_pages()
        self.fx = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(self.fx)
        self.fx.setOpacity(1.0)
        self.retranslate()
        self.go(0, animate=False)
        QTimer.singleShot(200, self.load_hw)

    # ------------------------------------------------------------ вспомогательное
    def tr(self, k):
        return T[self.lang][k]

    def make_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        return w, l

    def label(self, name, obj=None, wrap=True):
        lb = QLabel()
        lb.setWordWrap(wrap)
        if obj:
            lb.setObjectName(obj)
        self.texts.append((lb, name))
        return lb

    def build_pages(self):
        self.texts = []  # (widget, key) - обновляются при смене языка

        # 0 приветствие
        p, l = self.make_page()
        l.addStretch()
        l.addWidget(self.label("welcome_h", "h1"))
        l.addWidget(self.label("welcome_p", "muted"))
        self.rb_ru, self.rb_en = QRadioButton("Русский"), QRadioButton("English")
        self.rb_ru.setChecked(True)
        self.rb_ru.toggled.connect(lambda on: on and self.set_lang("ru"))
        self.rb_en.toggled.connect(lambda on: on and self.set_lang("en"))
        l.addWidget(self.rb_ru)
        l.addWidget(self.rb_en)
        l.addStretch()
        self.btn_try = QPushButton()
        self.btn_try.clicked.connect(self.close)
        self.texts.append((self.btn_try, "try"))
        l.addWidget(self.btn_try, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(p)

        # 1 лицензия
        p, l = self.make_page()
        l.addWidget(self.label("lic_h", "h1"))
        self.lic = QTextEdit()
        self.lic.setReadOnly(True)
        try:
            self.lic.setPlainText(open(LICENSE, encoding="utf-8").read())
        except OSError:
            self.lic.setPlainText("LisiOS license text is missing.")
        l.addWidget(self.lic, 1)
        self.cb_lic = QCheckBox()
        self.cb_lic.toggled.connect(self.update_nav)
        self.texts.append((self.cb_lic, "lic_accept"))
        l.addWidget(self.cb_lic)
        self.stack.addWidget(p)

        # 2 диск
        p, l = self.make_page()
        l.addWidget(self.label("disk_h", "h1"))
        l.addWidget(self.label("disk_p", "muted"))
        self.disk_list = QListWidget()
        self.disk_list.currentRowChanged.connect(self.on_disk)
        l.addWidget(self.disk_list, 1)
        self.btn_skip_install = QPushButton()
        self.texts.append((self.btn_skip_install, "skip_install"))
        self.btn_skip_install.clicked.connect(self.skip_disk_install)
        l.addWidget(self.btn_skip_install, 0, Qt.AlignmentFlag.AlignLeft)
        self.disk_warn = self.label("disk_win", "warn")
        self.disk_warn.hide()
        l.addWidget(self.disk_warn)
        self.cb_erase = QCheckBox()
        self.cb_erase.toggled.connect(self.update_nav)
        self.texts.append((self.cb_erase, "disk_erase"))
        l.addWidget(self.cb_erase)
        self.stack.addWidget(p)

        # 3 пользователь
        p, l = self.make_page()
        l.addWidget(self.label("user_h", "h1"))
        self.ed = {}
        for key in ("fullname", "username", "password", "password2", "hostname"):
            l.addWidget(self.label(key, "muted"))
            e = QLineEdit()
            if key.startswith("password"):
                e.setEchoMode(QLineEdit.EchoMode.Password)
            if key == "hostname":
                e.setText("lisios")
            e.textChanged.connect(self.update_nav)
            self.ed[key] = e
            l.addWidget(e)
        self.ed["fullname"].textEdited.connect(self.autofill_username)
        l.addWidget(self.label("timezone", "muted"))
        self.tz = QComboBox()
        self.tz.setEditable(True)
        self.tz.addItems(self.timezones())
        l.addWidget(self.tz)
        self.cb_auto = QCheckBox()
        self.cb_auto.setChecked(True)
        self.texts.append((self.cb_auto, "autologin"))
        l.addWidget(self.cb_auto)
        self.user_err = self.label("err_pw", "err")
        self.user_err.hide()
        l.addWidget(self.user_err)
        l.addStretch()
        self.stack.addWidget(p)

        # 4 драйверы
        p, l = self.make_page()
        l.addWidget(self.label("drv_h", "h1"))
        self.hw_label = QLabel()
        self.hw_label.setObjectName("muted")
        self.hw_label.setWordWrap(True)
        l.addWidget(self.hw_label)
        l.addWidget(self.label("drv_req", "muted"))
        for k in ("drv_wifi", "drv_bt", "drv_sys", "drv_wine"):
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setEnabled(False)
            self.texts.append((cb, k))
            l.addWidget(cb)
        l.addWidget(self.label("drv_opt", "muted"))
        self.cb_nvidia, self.cb_print, self.cb_codecs, self.cb_steam = QCheckBox(), QCheckBox(), QCheckBox(), QCheckBox()
        self.texts += [(self.cb_print, "drv_print"), (self.cb_codecs, "drv_codecs"), (self.cb_steam, "drv_steam")]
        for cb in (self.cb_nvidia, self.cb_print, self.cb_codecs, self.cb_steam):
            l.addWidget(cb)
        self.net_label = QLabel()
        l.addWidget(self.net_label)
        self.btn_wifi = QPushButton()
        self.btn_wifi.clicked.connect(lambda: subprocess.Popen(["kitty", "-e", "nmtui"]))
        self.texts.append((self.btn_wifi, "wifi_btn"))
        l.addWidget(self.btn_wifi, 0, Qt.AlignmentFlag.AlignLeft)
        l.addStretch()
        self.stack.addWidget(p)

        # 5 установка
        p, l = self.make_page()
        l.addStretch()
        l.addWidget(self.label("inst_h", "h1"))
        self.status = QLabel()
        self.status.setObjectName("muted")
        l.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        l.addWidget(self.bar)
        self.btn_det = QPushButton()
        self.btn_det.setCheckable(True)
        self.texts.append((self.btn_det, "inst_details"))
        l.addWidget(self.btn_det, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.hide()
        self.btn_det.toggled.connect(self.log.setVisible)
        l.addWidget(self.log, 1)
        l.addStretch()
        self.stack.addWidget(p)

        # 6 завершение
        p, l = self.make_page()
        l.addStretch()
        self.done_h = self.label("done_h", "h1")
        l.addWidget(self.done_h)
        self.done_p = self.label("done_p", "muted")
        l.addWidget(self.done_p)
        self.err_text = QLabel()
        self.err_text.setObjectName("err")
        self.err_text.setWordWrap(True)
        l.addWidget(self.err_text)
        l.addStretch()
        self.stack.addWidget(p)

    @staticmethod
    def timezones():
        try:
            out = subprocess.check_output(["timedatectl", "list-timezones"], text=True).split()
            if out:
                return out
        except Exception:
            pass
        return ["UTC", "Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk",
                "Asia/Novosibirsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Vladivostok", "Europe/Kyiv",
                "Europe/Minsk", "Asia/Almaty", "Europe/Berlin", "Europe/London", "America/New_York"]

    # ------------------------------------------------------------ язык
    def set_lang(self, lang):
        self.lang = lang
        self.retranslate()

    def retranslate(self):
        for w, k in self.texts:
            if isinstance(w, QLabel):
                w.setText(self.tr(k))
            else:
                w.setText(self.tr(k))
        self.title.setText(self.tr("title"))
        self.dry_label.setText(self.tr("dry_note") if DRY else "")
        self.status.setText(self.status.text() or self.tr("inst_start"))
        if self.tz.currentText() in ("", "UTC") or not hasattr(self, "_tz_set"):
            self.tz.setCurrentText("Europe/Moscow" if self.lang == "ru" else "UTC")
            self._tz_set = True
        self.refresh_disks()
        self.refresh_hw_text()
        self.update_nav()

    # ------------------------------------------------------------ навигация
    def go(self, idx, animate=True):
        idx = max(0, min(idx, self.stack.count() - 1))
        if idx == 4:
            self.load_hw()
        if idx == 2:
            self.refresh_disks(reload=True)
        if not animate:
            self.stack.setCurrentIndex(idx)
            self.update_nav()
            return
        a = QPropertyAnimation(self.fx, b"opacity", self)
        a.setDuration(160)
        a.setStartValue(1.0)
        a.setEndValue(0.0)

        def swap():
            self.stack.setCurrentIndex(idx)
            self.update_nav()
            b = QPropertyAnimation(self.fx, b"opacity", self)
            b.setDuration(260)
            b.setStartValue(0.0)
            b.setEndValue(1.0)
            b.setEasingCurve(QEasingCurve.Type.OutCubic)
            b.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            self._b = b

        a.finished.connect(swap)
        a.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._a = a

    def update_nav(self):
        i = self.stack.currentIndex()
        self.btn_back.setText(self.tr("back"))
        self.btn_back.setVisible(i in (1, 2, 3, 4))
        self.btn_next.setVisible(i not in (5, 6))
        self.btn_next.setText(self.tr("install") if i == 4 else self.tr("next"))
        ok = True
        if i == 1:
            ok = self.cb_lic.isChecked()
        elif i == 2:
            ok = bool(self.state["disk"]) and self.cb_erase.isChecked()
        elif i == 3:
            ok = self.user_valid()
        self.btn_next.setEnabled(ok)
        if i == 6:
            self.btn_next.setVisible(False)

    def on_next(self):
        i = self.stack.currentIndex()
        if i == 4:
            self.start_install()
        else:
            self.go(i + 1)

    # ------------------------------------------------------------ диски
    def refresh_disks(self, reload=False):
        if reload or not self.disks:
            try:
                self.disks = json.loads(subprocess.check_output([CLI, "--list-disks"], text=True))
            except Exception:
                self.disks = []
        keep = self.state["disk"]
        self.disk_list.blockSignals(True)
        self.disk_list.clear()
        if not self.disks:
            it = QListWidgetItem(self.tr("disk_none"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.disk_list.addItem(it)
        for d in self.disks:
            txt = f"{d['model']} — {human(d['size'])} — {d['path']}"
            reasons = []
            if d["is_live_medium"]:
                reasons.append(self.tr("disk_live"))
            if d["mounted"] and not d["is_live_medium"]:
                reasons.append(self.tr("disk_mounted"))
            if d["too_small"]:
                reasons.append(self.tr("disk_small"))
            if reasons:
                txt += "  [" + ", ".join(reasons) + "]"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, d["path"])
            if not d["selectable"]:
                it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.disk_list.addItem(it)
            if keep == d["path"] and d["selectable"]:
                self.disk_list.setCurrentItem(it)
        self.disk_list.blockSignals(False)

    def on_disk(self, row):
        it = self.disk_list.item(row)
        path = it.data(Qt.ItemDataRole.UserRole) if it else None
        self.state["disk"] = path
        d = next((x for x in self.disks if x["path"] == path), None)
        self.disk_warn.setVisible(bool(d and d["has_windows"]))
        self.cb_erase.setChecked(False)
        self.update_nav()

    def skip_disk_install(self):
        """Закрывает только мастер установки; live-сессия с USB остаётся активной."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("LisiOS Live")
        box.setText(self.tr("skip_confirm"))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(self.tr("skip_yes"))
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.close()

    # ------------------------------------------------------------ пользователь
    def autofill_username(self, text):
        if self._user_edited():
            return
        slug = re.sub(r"[^a-z0-9_-]", "", text.lower().split(" ")[0]) if text else ""
        self.ed["username"].blockSignals(True)
        self.ed["username"].setText(slug)
        self.ed["username"].blockSignals(False)
        self.update_nav()

    def _user_edited(self):
        return False

    def user_valid(self):
        u = self.ed["username"].text()
        pw, pw2 = self.ed["password"].text(), self.ed["password2"].text()
        host = self.ed["hostname"].text()
        user_ok = bool(re.match(r"^[a-z_][a-z0-9_-]{0,30}$", u)) and u not in ("root", "liveuser")
        pw_ok = len(pw) >= 4 and pw == pw2
        host_ok = bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$", host))
        self.user_err.setVisible(False)
        if self.stack.currentIndex() == 3 and (u or pw or pw2):
            if not user_ok and u:
                self.user_err.setText(self.tr("err_user"))
                self.user_err.setVisible(True)
            elif pw2 and not pw_ok:
                self.user_err.setText(self.tr("err_pw"))
                self.user_err.setVisible(True)
        return user_ok and pw_ok and host_ok

    # ------------------------------------------------------------ оборудование
    def load_hw(self):
        try:
            self.state["hw"] = json.loads(subprocess.check_output([CLI, "--hardware"], text=True))
        except Exception:
            self.state["hw"] = {}
        hw = self.state["hw"]
        if hw.get("nvidia_gpu"):
            if hw.get("nvidia_mode") == "open":
                self.cb_nvidia.setEnabled(True)
                self.cb_nvidia.setChecked(True)
                self.cb_nvidia.setText(self.tr("drv_nvidia"))
            else:
                self.cb_nvidia.setEnabled(False)
                self.cb_nvidia.setChecked(False)
                self.cb_nvidia.setText(self.tr("drv_nvidia_legacy"))
            self.cb_nvidia.show()
        else:
            self.cb_nvidia.hide()
            self.cb_nvidia.setChecked(False)
        self.refresh_hw_text()

    def refresh_hw_text(self):
        hw = self.state.get("hw") or {}
        gpus = ", ".join(f"{g['vendor']} {g['device']}" for g in hw.get("gpus", [])) or "—"
        mode = "UEFI" if hw.get("uefi") else "BIOS"
        self.hw_label.setText(f"{self.tr('detected')}: {gpus}\n{self.tr('mode')}: {mode}")
        self.net_label.setText(self.tr("net_ok") if hw.get("network") else self.tr("net_no"))
        if self.cb_nvidia.isVisible() or hw.get("nvidia_gpu"):
            if hw.get("nvidia_mode") == "open":
                self.cb_nvidia.setText(self.tr("drv_nvidia"))
            elif hw.get("nvidia_gpu"):
                self.cb_nvidia.setText(self.tr("drv_nvidia_legacy"))

    # ------------------------------------------------------------ установка
    def start_install(self):
        cfg = {
            "disk": self.state["disk"], "confirm_erase": self.cb_erase.isChecked(),
            "language": self.lang, "timezone": self.tz.currentText(),
            "hostname": self.ed["hostname"].text(), "username": self.ed["username"].text(),
            "fullname": self.ed["fullname"].text(), "password": self.ed["password"].text(),
            "autologin": self.cb_auto.isChecked(),
            "drivers": {"nvidia": self.cb_nvidia.isChecked(), "printing": self.cb_print.isChecked(),
                        "codecs": self.cb_codecs.isChecked(), "steam_support": self.cb_steam.isChecked()},
            "dry_run": DRY,
        }
        self.go(5)
        self.worker = Worker(cfg)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_done)
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_progress(self, pct, step, msg):
        if pct >= 0:
            self.bar.setValue(pct)
            self.status.setText(msg)
        self.log.appendPlainText(msg)

    def on_done(self):
        self.bar.setValue(100)
        self.err_text.setText("")
        self.done_h.setText(self.tr("done_h"))
        self.done_p.setText(self.tr("done_p"))
        self.show_finish_button()
        self.go(6)

    def on_fail(self, msg):
        self.done_h.setText(self.tr("err_h"))
        self.done_p.setText("")
        self.err_text.setText(msg)
        b = QPushButton(self.tr("close"))
        b.clicked.connect(self.close)
        self.stack.widget(6).layout().addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.go(6)

    def show_finish_button(self):
        b = QPushButton(self.tr("done_btn"))
        b.setObjectName("primary")
        b.clicked.connect(self.play_exit_animation)
        self.stack.widget(6).layout().addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)

    # чёрный экран -> логотип появляется -> улетает вверх -> перезагрузка в установленную систему
    def play_exit_animation(self):
        ov = QWidget(self)
        ov.setStyleSheet("background:black;")
        ov.setGeometry(self.rect())
        ov.show()
        lg = QLabel(ov)
        lg.setStyleSheet("background:transparent;")
        pm = QPixmap(LOGO)
        if pm.isNull():
            lg.setText("LisiOS")
            lg.setStyleSheet("background:transparent;color:white;font-size:64px;font-weight:700;")
            lg.adjustSize()
        else:
            lg.setPixmap(pm.scaledToHeight(max(120, self.height() // 5), Qt.TransformationMode.SmoothTransformation))
            lg.adjustSize()
        lg.show()
        x = (ov.width() - lg.width()) // 2
        y = (ov.height() - lg.height()) // 2
        lg.move(x, y)
        eff = QGraphicsOpacityEffect(lg)
        lg.setGraphicsEffect(eff)
        eff.setOpacity(0.0)

        fade_in = QPropertyAnimation(eff, b"opacity")
        fade_in.setDuration(900)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutCubic)
        up = QPropertyAnimation(lg, b"pos")
        up.setDuration(1000)
        up.setStartValue(QPoint(x, y))
        up.setEndValue(QPoint(x, -lg.height() - 40))
        up.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out = QPropertyAnimation(eff, b"opacity")
        fade_out.setDuration(1000)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fly = QParallelAnimationGroup()
        fly.addAnimation(up)
        fly.addAnimation(fade_out)
        seq = QSequentialAnimationGroup(self)
        seq.addAnimation(fade_in)
        seq.addPause(600)
        seq.addAnimation(fly)
        seq.finished.connect(self.reboot)
        seq.start()
        self._seq = seq

    def reboot(self):
        if DRY:
            self.close()
            return
        subprocess.Popen(["sudo", "-n", "systemctl", "reboot"])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.stack.currentIndex() in (0,):
            self.close()


def main():
    app = QApplication(sys.argv)
    w = Installer()
    w.showFullScreen()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
