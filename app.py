"""Окно LisiOS Game Mode (PyQt6)."""
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

import core
import games

TR = {
    "ru": {"title": "LisiOS Game Mode", "on": "Game Mode включён", "off": "Game Mode выключен",
           "auto": "Включать автоматически при запуске выбранной игры", "sel": "Приоритетные игры (до %d)",
           "search": "Поиск установленных игр…", "add": "Добавить в список", "manual": "Указать файл вручную…",
           "remove": "Убрать из списка", "cpu": "Загрузка CPU", "gcpu": "CPU игровых процессов",
           "off_s": "Режим выключен: система работает как обычно.",
           "wait_s": "Включён. Ждём запуска выбранной игры; пока ничего не меняется.",
           "act_s": "Игра запущена: её процессам повышен приоритет. Фоновые приложения работают как обычно.",
           "thr_s": "Игра запущена, CPU занят: фоновым приложениям мягко снижен приоритет (они не закрыты).",
           "priv_s": "Игра найдена, но нет прав на смену приоритета (polkit). Ничего не изменено.",
           "run": "запущена", "idle": "не запущена", "limit": "Можно выбрать не больше трёх игр.",
           "generic": "Слишком общее имя файла - так можно задеть чужие процессы. Укажите конкретный файл игры.",
           "dup": "Эта игра уже в списке.", "none": "Ничего не найдено", "name": "Название игры",
           "restore": "Вернуть исходные приоритеты"},
    "en": {"title": "LisiOS Game Mode", "on": "Game Mode is on", "off": "Game Mode is off",
           "auto": "Turn on automatically when a selected game starts", "sel": "Priority games (up to %d)",
           "search": "Search installed games…", "add": "Add to list", "manual": "Choose file manually…",
           "remove": "Remove from list", "cpu": "CPU load", "gcpu": "CPU used by games",
           "off_s": "Off: the system runs as usual.",
           "wait_s": "On. Waiting for a selected game to start; nothing is changed yet.",
           "act_s": "Game running: its processes got a higher priority. Background apps run as usual.",
           "thr_s": "Game running and CPU is busy: background apps got a softly lowered priority (none are closed).",
           "priv_s": "Game found, but no permission to change priorities (polkit). Nothing was changed.",
           "run": "running", "idle": "not running", "limit": "You can select up to three games.",
           "generic": "File name is too generic and could affect other processes. Pick the game's own file.",
           "dup": "Already in the list.", "none": "Nothing found", "name": "Game name",
           "restore": "Restore original priorities"},
}
CSS = """
QWidget { background:#0a0a0a; color:#f2f2f2; font-size:14px; }
QLabel#h { font-size:22px; font-weight:700; }
QLabel#st { color:#bdbdbd; }
QPushButton { background:#1a1a1a; border:1px solid #2e2e2e; border-radius:12px; padding:9px 14px; }
QPushButton:hover { border-color:#ff5a00; }
QPushButton:disabled { color:#666; }
QPushButton#big { font-size:18px; font-weight:700; padding:18px; border-radius:20px; }
QPushButton#big:checked { background:#ff5a00; color:#0a0a0a; border-color:#ff5a00; }
QLineEdit, QListWidget { background:#141414; border:1px solid #2e2e2e; border-radius:12px; padding:6px; }
QListWidget::item { padding:7px; border-radius:8px; }
QListWidget::item:selected { background:#ff5a00; color:#0a0a0a; }
QProgressBar { background:#141414; border:none; border-radius:6px; height:12px; text-align:center; color:#f2f2f2; }
QProgressBar::chunk { background:#ff5a00; border-radius:6px; }
QCheckBox::indicator { width:18px; height:18px; border-radius:5px; border:1px solid #555; background:#141414; }
QCheckBox::indicator:checked { background:#ff5a00; border-color:#ff5a00; }
"""


class Win(QWidget):
    def __init__(self):
        super().__init__()
        self.conf = core.load_conf()
        try:
            self.lang = __import__("json").load(open(os.path.expanduser("~/.config/lisios/config.json"))).get("lang", "ru")
        except (OSError, ValueError):
            self.lang = "ru"
        if self.lang not in TR:
            self.lang = "ru"
        self.found = []
        self.cpu = core.Cpu()
        self.setMinimumSize(560, 700)
        self.setStyleSheet(CSS)
        L = QVBoxLayout(self)
        L.setSpacing(12)
        self.h = QLabel(objectName="h")
        L.addWidget(self.h)
        self.big = QPushButton(objectName="big")
        self.big.setCheckable(True)
        self.big.clicked.connect(self.toggle)
        L.addWidget(self.big)
        self.st = QLabel(objectName="st")
        self.st.setWordWrap(True)
        L.addWidget(self.st)
        self.auto = QCheckBox()
        self.auto.toggled.connect(self.set_auto)
        L.addWidget(self.auto)
        self.l_cpu, self.b_cpu = QLabel(), QProgressBar()
        self.l_g, self.b_g = QLabel(), QProgressBar()
        for w in (self.l_cpu, self.b_cpu, self.l_g, self.b_g):
            L.addWidget(w)
        self.l_sel = QLabel()
        L.addWidget(self.l_sel)
        self.sel = QListWidget()
        self.sel.setMaximumHeight(130)
        L.addWidget(self.sel)
        self.b_rm = QPushButton()
        self.b_rm.clicked.connect(self.remove)
        L.addWidget(self.b_rm)
        self.q = QLineEdit()
        self.q.textChanged.connect(self.filter)
        L.addWidget(self.q)
        self.res = QListWidget()
        L.addWidget(self.res, 1)
        row = QHBoxLayout()
        self.b_add, self.b_man, self.b_rst = QPushButton(), QPushButton(), QPushButton()
        self.b_add.clicked.connect(self.add_found)
        self.b_man.clicked.connect(self.add_manual)
        self.b_rst.clicked.connect(self.restore)
        for b in (self.b_add, self.b_man):
            row.addWidget(b)
        L.addLayout(row)
        L.addWidget(self.b_rst)
        self.retr()
        self.found = games.installed(self.lang)
        self.filter()
        self.refresh_conf()
        core.ensure_daemon()
        self.t = QTimer(self)
        self.t.timeout.connect(self.tick)
        self.t.start(1000)
        self.tick()

    def tr(self, k):
        return TR[self.lang][k]

    def retr(self):
        self.setWindowTitle(self.tr("title"))
        self.h.setText(self.tr("title"))
        self.auto.setText(self.tr("auto"))
        self.l_cpu.setText(self.tr("cpu"))
        self.l_g.setText(self.tr("gcpu"))
        self.l_sel.setText(self.tr("sel") % core.MAX_GAMES)
        self.q.setPlaceholderText(self.tr("search"))
        self.b_rm.setText(self.tr("remove"))
        self.b_add.setText(self.tr("add"))
        self.b_man.setText(self.tr("manual"))
        self.b_rst.setText(self.tr("restore"))

    def save(self):
        core.save_conf(self.conf)
        core.ensure_daemon()

    def toggle(self):
        self.conf["enabled"] = self.big.isChecked()
        self.save()
        self.tick()

    def set_auto(self, v):
        self.conf["auto"] = v
        self.save()

    def refresh_conf(self):
        self.big.setChecked(self.conf["enabled"])
        self.auto.blockSignals(True)
        self.auto.setChecked(self.conf["auto"])
        self.auto.blockSignals(False)
        self.update_list({})

    def update_list(self, running):
        cur = self.sel.currentRow()
        self.sel.clear()
        for g in self.conf["games"]:
            on = running.get(g["name"])
            it = QListWidgetItem("%s  %s  %s" % ("●" if on else "○", g["name"], "- " + self.tr("run") if on else ""))
            it.setData(Qt.ItemDataRole.UserRole, g["name"])
            self.sel.addItem(it)
        if 0 <= cur < self.sel.count():
            self.sel.setCurrentRow(cur)
        full = len(self.conf["games"]) >= core.MAX_GAMES
        self.b_add.setEnabled(not full)
        self.b_man.setEnabled(not full)

    def filter(self):
        t = self.q.text().lower()
        self.res.clear()
        for g in self.found:
            if t in g["name"].lower():
                it = QListWidgetItem(g["name"])
                it.setData(Qt.ItemDataRole.UserRole, g)
                self.res.addItem(it)
        if self.res.count() == 0:
            self.res.addItem(self.tr("none"))

    def _add(self, g):
        err = core.add_game(self.conf, g)
        if err:
            QMessageBox.warning(self, self.tr("title"), self.tr(err))
            return
        self.save()
        self.update_list({})

    def add_found(self):
        it = self.res.currentItem()
        g = it.data(Qt.ItemDataRole.UserRole) if it else None
        if isinstance(g, dict):
            self._add(dict(g))

    def add_manual(self):
        f, _ = QFileDialog.getOpenFileName(self, self.tr("manual"), os.path.expanduser("~"))
        if not f:
            return
        name, ok = QInputDialog.getText(self, self.tr("title"), self.tr("name"), text=os.path.basename(f))
        if ok and name.strip():
            self._add({"name": name.strip(), "exec": f, "match": []})

    def remove(self):
        it = self.sel.currentItem()
        if it:
            n = it.data(Qt.ItemDataRole.UserRole)
            self.conf["games"] = [g for g in self.conf["games"] if g["name"] != n]
            self.save()
            self.update_list({})

    def restore(self):
        self.conf["enabled"] = False
        self.big.setChecked(False)
        core.save_conf(self.conf)
        core.helper("restore")

    def tick(self):
        st = core.read_status()
        state = st.get("state", "off")
        disk = core.load_conf()           # кнопку в Control Center могли нажать отдельно
        if disk["enabled"] != self.conf["enabled"] or disk["auto"] != self.conf["auto"]:
            self.conf["enabled"], self.conf["auto"] = disk["enabled"], disk["auto"]
            self.refresh_conf()
        enabled = self.conf["enabled"]
        self.big.setText(self.tr("on") if enabled else self.tr("off"))
        msg = {"off": "off_s", "waiting": "wait_s", "active": "act_s", "throttling": "thr_s",
               "no_privilege": "priv_s"}.get(state, "off_s")
        if not enabled and self.conf["auto"] and state in ("waiting", "off"):
            msg = "wait_s"
        self.st.setText(self.tr(msg))
        run = {g["name"]: g.get("running") for g in st.get("games", [])}
        self.update_list(run)
        procs = core.scan()
        allp = set().union(*core.game_pids(self.conf["games"], procs).values()) if self.conf["games"] else set()
        load, gcpu = self.cpu.update(procs, allp)
        self.b_cpu.setValue(int(load))
        self.b_cpu.setFormat("%d %%" % int(load))
        self.b_g.setValue(int(gcpu))
        self.b_g.setFormat("%d %%" % int(gcpu))


def main():
    app = QApplication(sys.argv)
    w = Win()
    w.show()
    return app.exec()
