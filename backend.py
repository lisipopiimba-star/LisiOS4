#!/usr/bin/env python3
"""LisiOS installer backend.

Работает без графики. GUI (gui.py) вызывает его через `lisios-install-cli`.

Принципы безопасности:
  * трогается ТОЛЬКО диск, выбранный пользователем (cfg["disk"]);
  * диск с установочным носителем и диски со смонтированными разделами не принимаются;
  * установка возможна только из live-системы (/run/archiso), иначе отказ;
  * режим dry_run ничего не выполняет, только печатает план.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Callable, Optional

TARGET = "/mnt/lisios"
LIVE_ROOT = "/run/archiso/airootfs"
MIN_DISK_BYTES = 16 * 1024**3
LOCALES = {"ru": "ru_RU.UTF-8", "en": "en_US.UTF-8"}
KEYMAPS = {"ru": ("ru", "cyr-sun16"), "en": ("us", "")}

# Пакеты, без которых система не считается рабочей (проверяются после установки)
MANDATORY_PACKAGES = {
    "wifi": ["networkmanager", "wpa_supplicant", "iw", "wireless-regdb", "linux-firmware"],
    "bluetooth": ["bluez", "bluez-utils"],
    "system": ["base", "linux", "grub", "mkinitcpio", "hyprland", "quickshell",
               "plymouth", "intel-ucode", "amd-ucode", "mesa", "pipewire", "wireplumber", "wine"],
}
OPTIONAL_DRIVERS = {
    "nvidia": {"packages": ["nvidia-open", "nvidia-utils", "nvidia-settings"], "needs_network": True},
    "printing": {"packages": ["cups", "cups-filters", "system-config-printer"], "needs_network": True},
    "codecs": {"packages": ["ffmpeg", "gst-libav", "gst-plugins-good", "gst-plugins-bad", "gst-plugins-ugly"],
               "needs_network": True},
    # Клиент Steam не устанавливается. Только 32-битные графические/аудио runtime-библиотеки.
    "steam_support": {"packages": ["lib32-mesa", "lib32-vulkan-icd-loader", "lib32-libpulse",
                                    "lib32-alsa-plugins", "lib32-openal", "lib32-gcc-libs",
                                    "lib32-libx11", "lib32-libxss", "lib32-libxtst",
                                    "lib32-libxrandr", "lib32-libxinerama", "lib32-libxcursor",
                                    "lib32-libxi", "lib32-libxcomposite", "lib32-libxdamage",
                                    "lib32-libxfixes", "lib32-libxcb", "lib32-libxkbcommon",
                                    "lib32-libdrm"], "needs_network": True},
}

# То, что принадлежит live-системе и не должно попасть на установленный диск
LIVE_ONLY_PATHS = [
    "/etc/systemd/system/pacman-init.service",
    "/etc/systemd/system/etc-pacman.d-gnupg.mount",
    "/etc/systemd/system/choose-mirror.service",
    "/etc/systemd/system/livecd-talk.service",
    "/etc/systemd/system/lisios-live-setup.service",
    "/etc/systemd/system/multi-user.target.wants/pacman-init.service",
    "/etc/systemd/system/multi-user.target.wants/choose-mirror.service",
    "/etc/systemd/system/multi-user.target.wants/livecd-talk.service",
    "/etc/systemd/system/multi-user.target.wants/lisios-live-setup.service",
    "/etc/systemd/system/getty@tty1.service.d",
    "/etc/mkinitcpio.conf.d/archiso.conf",
    "/etc/mkinitcpio.d/linux.preset",
    "/etc/sudoers.d/g_wheel",
    "/etc/sudoers.d/10-lisios",
    "/etc/ssh/ssh_host_*",
    "/root/.automated_script.sh",
    "/root/.zlogin",
    "/usr/local/bin/lisios-live-setup",
]


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- обнаружение

def _lsblk() -> list:
    out = subprocess.check_output(
        ["lsblk", "-J", "-b", "-o",
         "NAME,PATH,SIZE,MODEL,TYPE,RM,TRAN,FSTYPE,PARTTYPE,MOUNTPOINTS,PKNAME,LABEL"],
        text=True)
    return json.loads(out)["blockdevices"]


def live_medium_disk() -> Optional[str]:
    """Путь диска, с которого загружена live-система (его нельзя трогать)."""
    for mnt in ("/run/archiso/bootmnt", "/run/archiso/copytoram"):
        try:
            src = subprocess.check_output(["findmnt", "-n", "-o", "SOURCE", mnt], text=True).strip()
        except Exception:
            continue
        if not src.startswith("/dev/"):
            continue
        try:
            parent = subprocess.check_output(["lsblk", "-no", "PKNAME", src], text=True).strip().splitlines()
        except Exception:
            parent = []
        return "/dev/" + parent[0] if parent and parent[0] else src
    return None


def _mounted(dev: dict) -> bool:
    mps = [m for m in (dev.get("mountpoints") or []) if m]
    if mps:
        return True
    return any(_mounted(c) for c in dev.get("children") or [])


def _has_windows(dev: dict) -> bool:
    for c in dev.get("children") or []:
        fs = (c.get("fstype") or "").lower()
        label = (c.get("label") or "").lower()
        ptype = (c.get("parttype") or "").lower()
        if fs in ("ntfs", "bitlocker") or "windows" in label or ptype in (
                "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "de94bba4-06d1-4d40-a16a-bfd50179d6ac"):
            return True
    return False


def list_disks() -> list:
    """Диски, на которые МОЖНО установить систему."""
    live = live_medium_disk()
    result = []
    for d in _lsblk():
        if d.get("type") != "disk":
            continue
        path = d.get("path") or "/dev/" + d["name"]
        if re.match(r"^/dev/(loop|zram|sr|ram|fd)", path):
            continue
        size = int(d.get("size") or 0)
        entry = {
            "path": path,
            "model": (d.get("model") or "").strip() or "Disk",
            "size": size,
            "transport": d.get("tran") or "",
            "removable": bool(d.get("rm")),
            "partitions": len(d.get("children") or []),
            "has_windows": _has_windows(d),
            "mounted": _mounted(d),
            "is_live_medium": path == live,
            "too_small": size < MIN_DISK_BYTES,
        }
        entry["selectable"] = not (entry["is_live_medium"] or entry["mounted"] or entry["too_small"])
        result.append(entry)
    return result


def _gpu_lines() -> list:
    try:
        out = subprocess.check_output(["lspci", "-mm", "-nn"], text=True)
    except Exception:
        return []
    gpus = []
    for line in out.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) >= 4 and re.search(r"VGA|3D controller|Display controller", parts[1]):
            gpus.append({"vendor": parts[2], "device": parts[3]})
    return gpus


def nvidia_mode(device: str) -> str:
    """'open' - поддерживается nvidia-open (Turing и новее); 'legacy' - оставляем nouveau."""
    if re.search(r"\b(TU1\d\d|GA1\d\d|AD1\d\d|GB\d{3}|GH\d{3})\b", device):
        return "open"
    if re.search(r"RTX|GTX\s*16\d\d|TITAN RTX", device, re.I):
        return "open"
    return "legacy"


def detect_hardware() -> dict:
    gpus = _gpu_lines()
    info = {"gpus": gpus, "intel_gpu": False, "nvidia_gpu": False, "nvidia_mode": None,
            "virtual": False, "uefi": os.path.isdir("/sys/firmware/efi"),
            "wifi": False, "bluetooth": False, "network": False}
    for g in gpus:
        v = g["vendor"].lower()
        if "intel" in v:
            info["intel_gpu"] = True
        if "nvidia" in v:
            info["nvidia_gpu"] = True
            info["nvidia_mode"] = nvidia_mode(g["device"])
    try:
        info["virtual"] = subprocess.run(["systemd-detect-virt", "-q"]).returncode == 0
    except Exception:
        pass
    try:
        rf = subprocess.check_output(["rfkill", "list"], text=True, stderr=subprocess.DEVNULL).lower()
        info["wifi"] = "wireless lan" in rf
        info["bluetooth"] = "bluetooth" in rf
    except Exception:
        pass
    info["network"] = check_network()
    return info


def check_network() -> bool:
    try:
        return subprocess.run(["curl", "-sSf", "-m", "5", "-o", "/dev/null",
                               "https://geo.mirror.pkgbuild.com/"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------- установка

class Installer:
    def __init__(self, cfg: dict, progress: Callable[[int, str, str], None]):
        self.cfg = cfg
        self.progress = progress
        self.dry = bool(cfg.get("dry_run"))
        self.uefi = os.path.isdir("/sys/firmware/efi") if not self.dry else bool(cfg.get("force_uefi", True))
        self.disk = cfg.get("disk", "")
        self.mounted: list = []

    # ---- утилиты
    def log(self, msg: str):
        self.progress(-1, "log", msg)

    def run(self, cmd, *, input: Optional[str] = None, check: bool = True, chroot: bool = False):
        if chroot:
            cmd = ["arch-chroot", TARGET] + list(cmd)
        shown = " ".join(shlex.quote(c) for c in cmd)
        if input is not None and "chpasswd" in shown:
            shown += "   <пароль скрыт>"
        self.log("$ " + shown)
        if self.dry:
            return ""
        p = subprocess.run(cmd, input=input, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.stdout.strip():
            self.log(p.stdout.strip()[-2000:])
        if check and p.returncode != 0:
            raise InstallError(f"Команда завершилась с ошибкой ({p.returncode}): {shown}")
        return p.stdout

    def write(self, path: str, text: str, mode: int = 0o644):
        full = TARGET + path
        self.log(f"запись {path}")
        if self.dry:
            return
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
        os.chmod(full, mode)

    def part(self, n: int) -> str:
        return f"{self.disk}p{n}" if self.disk[-1].isdigit() else f"{self.disk}{n}"

    # ---- проверки
    def validate(self):
        c = self.cfg
        if not re.match(r"^/dev/(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$", self.disk):
            raise InstallError(f"Недопустимый путь диска: {self.disk!r}")
        if not re.match(r"^[a-z_][a-z0-9_-]{0,30}$", c.get("username", "")):
            raise InstallError("Имя пользователя: латиница в нижнем регистре, цифры, _ и -")
        if c.get("username") in ("root", "liveuser"):
            raise InstallError("Это имя пользователя зарезервировано")
        if len(c.get("password", "")) < 4:
            raise InstallError("Пароль слишком короткий (минимум 4 символа)")
        if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62})$", c.get("hostname", "")):
            raise InstallError("Некорректное имя компьютера")
        if c.get("language") not in LOCALES:
            raise InstallError("Неизвестный язык")
        tz = c.get("timezone", "UTC")
        if not re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$", tz):
            raise InstallError("Некорректный часовой пояс")
        if not self.dry:
            if not os.path.isdir("/run/archiso"):
                raise InstallError("Установка возможна только из live-образа LisiOS (защита запущенной системы)")
            if os.geteuid() != 0:
                raise InstallError("Нужны права root")
            if not os.path.isdir("/usr/share/zoneinfo/" + tz):
                if not os.path.isfile("/usr/share/zoneinfo/" + tz):
                    raise InstallError("Часовой пояс не найден")
            allowed = {d["path"]: d for d in list_disks()}
            d = allowed.get(self.disk)
            if d is None:
                raise InstallError("Выбранный диск не найден")
            if d["is_live_medium"]:
                raise InstallError("Это диск, с которого загружена установка - его трогать нельзя")
            if d["mounted"]:
                raise InstallError("На выбранном диске есть смонтированные разделы")
            if d["too_small"]:
                raise InstallError("Диск слишком мал (нужно минимум 16 ГБ)")
            if not self.cfg.get("confirm_erase"):
                raise InstallError("Нет подтверждения стирания диска")

    # ---- этапы
    def partition(self):
        self.progress(2, "partition", "Разметка выбранного диска")
        d = self.disk
        self.run(["wipefs", "-a", d])
        self.run(["sgdisk", "--zap-all", d])
        if self.uefi:
            self.run(["sgdisk", "-n", "1:0:+1GiB", "-t", "1:EF00", "-c", "1:LisiOS-EFI", d])
            self.run(["sgdisk", "-n", "2:0:0", "-t", "2:8300", "-c", "2:LisiOS", d])
        else:
            self.run(["sgdisk", "-n", "1:0:+1MiB", "-t", "1:EF02", "-c", "1:BIOS", d])
            self.run(["sgdisk", "-n", "2:0:0", "-t", "2:8300", "-c", "2:LisiOS", d])
        self.run(["partprobe", d], check=False)
        self.run(["udevadm", "settle"], check=False)
        if not self.dry:
            for _ in range(20):
                if os.path.exists(self.part(2)):
                    break
                time.sleep(0.5)
            else:
                raise InstallError("Разделы не появились после разметки")

    def format_and_mount(self):
        self.progress(8, "format", "Создание файловых систем")
        if self.uefi:
            self.run(["mkfs.fat", "-F32", "-n", "LISIEFI", self.part(1)])
        self.run(["mkfs.ext4", "-F", "-L", "LisiOS", self.part(2)])
        self.run(["mkdir", "-p", TARGET])
        self.run(["mount", self.part(2), TARGET])
        self.mounted.append(TARGET)

    def copy_system(self):
        self.progress(12, "copy", "Копирование системы LisiOS")
        src = LIVE_ROOT + "/"
        excludes = ["/boot/*"]
        if not (os.path.isdir(LIVE_ROOT) and os.listdir(LIVE_ROOT)) and not self.dry:
            src = "/"
            excludes += ["/dev/*", "/proc/*", "/sys/*", "/run/*", "/tmp/*", "/mnt/*", "/media/*",
                         "/lost+found", "/var/cache/pacman/pkg/*", "/home/*", "/var/log/*"]
        cmd = ["rsync", "-aHAXS", "--numeric-ids", "--no-inc-recursive", "--info=progress2"]
        cmd += ["--exclude=" + e for e in excludes] + [src, TARGET + "/"]
        self.log("$ " + " ".join(shlex.quote(c) for c in cmd))
        if self.dry:
            return
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf = b""
        last = -1
        while True:
            chunk = p.stdout.read(256)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for part in parts:
                m = re.search(rb"\s(\d+)%", part)
                if m:
                    pct = int(m.group(1))
                    if pct != last:
                        last = pct
                        self.progress(12 + int(pct * 0.58), "copy", f"Копирование системы: {pct}%")
        if p.wait() not in (0, 24):
            raise InstallError("Не удалось скопировать систему на диск (rsync)")
        # ESP монтируется ПОСЛЕ копирования корня
        if self.uefi:
            self.run(["mkdir", "-p", TARGET + "/boot"])
            self.run(["mount", "-o", "umask=0077", self.part(1), TARGET + "/boot"])
            self.mounted.append(TARGET + "/boot")

    def cleanup_live_traces(self):
        self.progress(71, "cleanup", "Удаление следов live-режима")
        for pattern in LIVE_ONLY_PATHS:
            self.run(["sh", "-c", f"rm -rf {TARGET}{pattern}"], check=False)

    def configure(self):
        c = self.cfg
        lang, loc = c["language"], LOCALES[c["language"]]
        self.progress(73, "configure", "Настройка системы")
        self.run(["sh", "-c", f": > {TARGET}/etc/fstab"]) if not self.dry else None
        out = self.run(["genfstab", "-U", TARGET])
        if not self.dry:
            with open(TARGET + "/etc/fstab", "a") as f:
                f.write(out)
        self.write("/etc/hostname", c["hostname"] + "\n")
        self.write("/etc/hosts", f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {c['hostname']}\n")
        self.write("/etc/locale.gen", "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n")
        self.write("/etc/locale.conf", f"LANG={loc}\n")
        km, font = KEYMAPS[lang]
        self.write("/etc/vconsole.conf", f"KEYMAP={km}\n" + (f"FONT={font}\n" if font else ""))
        self.run(["locale-gen"], chroot=True)
        tz = c.get("timezone", "UTC")
        self.run(["ln", "-sf", f"/usr/share/zoneinfo/{tz}", "/etc/localtime"], chroot=True)
        self.run(["hwclock", "--systohc"], chroot=True, check=False)
        self.run(["sh", "-c", ": > /etc/machine-id"], chroot=True, check=False)

        # пользователь
        self.run(["useradd", "-m", "-G", "wheel,audio,video,input,storage,optical,lp",
                  "-s", "/bin/bash", "-c", c.get("fullname") or c["username"], c["username"]], chroot=True)
        self.run(["chpasswd"], input=f"{c['username']}:{c['password']}\n", chroot=True)
        self.run(["passwd", "-l", "root"], chroot=True)
        self.write("/etc/sudoers.d/10-lisios", "%wheel ALL=(ALL:ALL) ALL\n", 0o440)

        # язык оболочки и анимации по умолчанию
        cfgjson = {"lang": lang, "animation_speed": 1.0, "ai": {"endpoint": "", "model": ""}}
        self.write("/etc/lisios/config.json", json.dumps(cfgjson, indent=2) + "\n")

        # автовход
        if c.get("autologin", True):
            self.write("/etc/systemd/system/getty@tty1.service.d/autologin.conf",
                       "[Service]\nExecStart=\nExecStart=-/sbin/agetty -o '-p -f -- \\\\u' --noclear "
                       f"--autologin {c['username']} %I $TERM\n")

        # сервисы
        for svc in ("NetworkManager", "bluetooth", "systemd-timesyncd", "systemd-resolved"):
            self.run(["systemctl", "enable", svc], chroot=True, check=False)

        # сохраняем Wi-Fi, который пользователь настроил в live-режиме
        if not self.dry and os.path.isdir("/etc/NetworkManager/system-connections"):
            self.run(["sh", "-c",
                      "mkdir -p {t}/etc/NetworkManager/system-connections && "
                      "cp -a /etc/NetworkManager/system-connections/. {t}/etc/NetworkManager/system-connections/"
                      .format(t=TARGET)], check=False)

        # зеркала pacman
        self.write("/etc/pacman.d/mirrorlist",
                   "Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n"
                   "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n")

    def install_drivers(self):
        self.progress(80, "drivers", "Драйверы и компоненты")
        chosen = [k for k, v in (self.cfg.get("drivers") or {}).items() if v and k in OPTIONAL_DRIVERS]
        have_net = check_network() if not self.dry else True
        need_keys = False
        pkgs = []
        for k in chosen:
            if OPTIONAL_DRIVERS[k]["needs_network"] and not have_net:
                self.log(f"Нет сети - драйвер «{k}» пропущен. Установить позже: sudo pacman -S "
                         + " ".join(OPTIONAL_DRIVERS[k]["packages"]))
                continue
            pkgs += OPTIONAL_DRIVERS[k]["packages"]
            need_keys = True
        # обязательное: проверяем, что всё реально установлено
        missing = []
        if not self.dry:
            for group, plist in MANDATORY_PACKAGES.items():
                for p in plist:
                    r = subprocess.run(["arch-chroot", TARGET, "pacman", "-Qq", p],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if r.returncode != 0:
                        missing.append((group, p))
        if missing:
            self.log("Не хватает обязательных пакетов: " + ", ".join(p for _, p in missing))
            if not have_net:
                raise InstallError("Обязательные компоненты отсутствуют, а сети нет: "
                                   + ", ".join(p for _, p in missing))
            pkgs += [p for _, p in missing]
            need_keys = True
        if "steam_support" in chosen:
            # multilib нужен для 32-битных библиотек. Клиент Steam намеренно не добавляется.
            self.run(["sh", "-c", "grep -Fq '[multilib]' /etc/pacman.conf || "
                      "printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >> /etc/pacman.conf"], chroot=True)
        if need_keys:
            self.run(["pacman-key", "--init"], chroot=True, check=False)
            self.run(["pacman-key", "--populate", "archlinux"], chroot=True, check=False)
        if pkgs:
            self.run(["pacman", "-Syu", "--noconfirm", "--needed"] + sorted(set(pkgs)), chroot=True)
        if "nvidia" in chosen and "nvidia-open" in pkgs:
            self.write("/etc/modprobe.d/lisios-nvidia.conf", "options nvidia_drm modeset=1 fbdev=1\n")
        self.nvidia_installed = "nvidia-open" in pkgs

    def initramfs_and_boot(self):
        self.progress(88, "initramfs", "Создание загрузочного образа")
        modules = "MODULES=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)\n" if getattr(self, "nvidia_installed", False) else ""
        self.write("/etc/mkinitcpio.conf.d/lisios.conf",
                   modules + "HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap "
                   "consolefont block filesystems fsck)\n")
        self.write("/etc/mkinitcpio.d/linux.preset",
                   "ALL_config=\"/etc/mkinitcpio.conf\"\nALL_kver=\"/boot/vmlinuz-linux\"\n"
                   "PRESETS=('default' 'fallback')\n"
                   "default_image=\"/boot/initramfs-linux.img\"\n"
                   "fallback_image=\"/boot/initramfs-linux-fallback.img\"\n"
                   "fallback_options=\"-S autodetect\"\n")
        # ядро: в образе оно лежит в /usr/lib/modules/*/vmlinuz
        self.run(["sh", "-c", "set -e; k=$(ls -1 /usr/lib/modules/*/vmlinuz | head -1); "
                  "test -n \"$k\"; install -Dm644 \"$k\" /boot/vmlinuz-linux"], chroot=True)
        self.run(["plymouth-set-default-theme", "lisios"], chroot=True)
        self.run(["mkinitcpio", "-P"], chroot=True)

        self.progress(94, "bootloader", "Установка загрузчика на выбранный диск")
        self.write("/etc/default/grub",
                   'GRUB_DEFAULT=0\nGRUB_TIMEOUT=2\nGRUB_TIMEOUT_STYLE=hidden\n'
                   'GRUB_DISTRIBUTOR="LisiOS"\n'
                   'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 rd.udev.log_level=3"\n'
                   'GRUB_CMDLINE_LINUX=""\nGRUB_DISABLE_OS_PROBER=true\nGRUB_GFXMODE=auto\n'
                   'GRUB_GFXPAYLOAD_LINUX=keep\n')
        if self.uefi:
            # --removable: пишем только в EFI/BOOT на ESP ЭТОГО диска, чужие записи не трогаем
            self.run(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot",
                      "--bootloader-id=LisiOS", "--removable"], chroot=True)
        else:
            self.run(["grub-install", "--target=i386-pc", self.disk], chroot=True)
        self.run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], chroot=True)

    def finalize(self):
        self.progress(98, "finalize", "Завершение")
        self.run(["sync"])
        self.run(["umount", "-R", TARGET], check=False)

    def run_all(self):
        self.validate()
        self.log(f"Режим загрузки: {'UEFI' if self.uefi else 'BIOS'}; диск: {self.disk}"
                 + ("  [DRY-RUN: ничего не выполняется]" if self.dry else ""))
        try:
            self.partition()
            self.format_and_mount()
            self.copy_system()
            self.cleanup_live_traces()
            self.configure()
            self.install_drivers()
            self.initramfs_and_boot()
            self.finalize()
        except Exception:
            # не оставляем диск смонтированным
            if not self.dry:
                subprocess.run(["umount", "-R", TARGET], stderr=subprocess.DEVNULL)
            raise
        self.progress(100, "done", "Установка завершена")


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="lisios-install-cli")
    ap.add_argument("--list-disks", action="store_true", help="JSON со списком доступных дисков")
    ap.add_argument("--hardware", action="store_true", help="JSON с обнаруженным оборудованием")
    ap.add_argument("--config-stdin", action="store_true", help="читать конфигурацию установки из stdin (JSON)")
    ap.add_argument("--dry-run", action="store_true", help="ничего не менять, только показать план")
    ap.add_argument("--disk"), ap.add_argument("--user"), ap.add_argument("--password")
    ap.add_argument("--hostname", default="lisios"), ap.add_argument("--lang", default="ru")
    ap.add_argument("--timezone", default="UTC")
    ap.add_argument("--yes-erase-disk", action="store_true")
    a = ap.parse_args(argv)

    if a.list_disks:
        print(json.dumps(list_disks())); return 0
    if a.hardware:
        print(json.dumps(detect_hardware())); return 0

    if a.config_stdin:
        cfg = json.load(sys.stdin)
    else:
        if not (a.disk and a.user and a.password):
            ap.error("нужны --disk --user --password (или --config-stdin)")
        cfg = {"disk": a.disk, "username": a.user, "password": a.password, "hostname": a.hostname,
               "language": a.lang, "timezone": a.timezone, "confirm_erase": a.yes_erase_disk,
               "drivers": {}, "autologin": True}
    if a.dry_run:
        cfg["dry_run"] = True

    def progress(pct, step, msg):
        print(json.dumps({"percent": pct, "step": step, "message": msg}, ensure_ascii=False), flush=True)

    try:
        Installer(cfg, progress).run_all()
    except InstallError as e:
        progress(-1, "error", str(e)); return 2
    except Exception as e:  # noqa
        progress(-1, "error", f"Непредвиденная ошибка: {e}"); return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
