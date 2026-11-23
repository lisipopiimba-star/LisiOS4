#!/usr/bin/env bash
# LisiOS: сборка ISO внутри контейнера archlinux (или на настоящем Arch от root).
#
#   /src  - исходники проекта (только чтение)
#   /out  - сюда кладётся готовый ISO
#
# Запускается через build.sh / build-windows.ps1 / GitHub Actions.
set -euo pipefail

SRC="${SRC:-/src}"
OUT="${OUT:-/out}"
WORK="${WORK:-/work}"
PROFILE="$WORK/profile"
LOCALREPO="$WORK/localrepo"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[ОШИБКА] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "нужен root (в Docker это так по умолчанию)"
[ -d "$SRC/profile" ] || die "не найден $SRC/profile - проект смонтирован неверно"

# ---------------------------------------------------------------- 1. рабочая копия
log "Копирую проект в рабочий каталог (Linux-файловая система, LF-окончания строк)"
rm -rf "$WORK"; mkdir -p "$WORK" "$OUT"
cp -a "$SRC/." "$WORK/src"
# Windows может превратить LF в CRLF - это ломает скрипты. Чиним в копии.
find "$WORK/src" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.qml' -o -name '*.conf' -o -name '*.lua' \
  -o -name '*.service' -o -name '*.plymouth' -o -name '*.script' -o -name '*.json' \
  -o -name '*.desktop' -o -name '*.ini' -o -name '*.rules' -o -name '*.policy' \
  -o -name 'packages*' -o -name 'lisios-*' -o -name '.bash_profile' -o -name '.bashrc' -o -name 'hostname' \
  -o -name 'issue' -o -name 'motd' -o -name 'os-release' -o -name 'locale.*' -o -name 'sudoers*' \
  -o -path '*/usr/local/bin/*' \) -exec sed -i 's/\r$//' {} +

# ---------------------------------------------------------------- 2. archiso
log "Устанавливаю archiso и инструменты сборки"
pacman-key --init >/dev/null 2>&1 || true
pacman-key --populate archlinux >/dev/null 2>&1 || true
# В некоторых контейнерах песочница загрузки pacman (Landlock) не работает - тогда отключаем её
DISABLE_SANDBOX=0
if ! pacman -Sy --noconfirm >/dev/null 2>"$WORK/pacman-err.txt"; then
  if grep -qiE 'landlock|sandbox|seccomp|restricting filesystem' "$WORK/pacman-err.txt"; then
    warn "песочница pacman недоступна - отключаю DisableSandbox"
    sed -i '/^\[options\]/a DisableSandbox' /etc/pacman.conf
    DISABLE_SANDBOX=1
  else
    cat "$WORK/pacman-err.txt"; die "не удалось обновить базу пакетов pacman"
  fi
fi
pacman -Syu --noconfirm --needed archiso git base-devel sudo binutils fakeroot >/dev/null
[ -d /usr/share/archiso/configs/releng ] || die "не найден профиль releng в archiso"

log "Беру за основу официальный профиль releng (загрузчики BIOS/UEFI уже настроены)"
cp -a /usr/share/archiso/configs/releng "$PROFILE"
[ "$DISABLE_SANDBOX" = 1 ] && sed -i '/^\[options\]/a DisableSandbox' "$PROFILE/pacman.conf"

# ---------------------------------------------------------------- 3. пакеты
log "Проверяю наличие всех пакетов в репозиториях"
pacman -Sy >/dev/null
read_list() { sed -e 's/#.*//' -e 's/[[:space:]]*$//' "$1" | grep -v '^$' || true; }

REQUIRED=(); OPTIONAL=(); MISSING_REQ=(); AUR_NEEDED=()
mapfile -t REQUIRED < <(read_list "$WORK/src/packages.required")
mapfile -t OPTIONAL < <(read_list "$WORK/src/packages.optional")

for p in "${REQUIRED[@]}"; do
  if ! pacman -Si "$p" >/dev/null 2>&1; then
    if [ "$p" = quickshell ]; then AUR_NEEDED+=("$p"); else MISSING_REQ+=("$p"); fi
  fi
done
[ ${#MISSING_REQ[@]} -eq 0 ] || die "обязательные пакеты не найдены в репозиториях Arch: ${MISSING_REQ[*]}"

FINAL_OPTIONAL=()
for p in "${OPTIONAL[@]}"; do
  if pacman -Si "$p" >/dev/null 2>&1; then FINAL_OPTIONAL+=("$p"); else warn "необязательный пакет '$p' не найден - пропускаю"; fi
done

# quickshell обычно есть в extra; если нет - соберём из AUR
if [ ${#AUR_NEEDED[@]} -gt 0 ]; then
  log "Пакеты ${AUR_NEEDED[*]} не найдены в репозиториях - собираю из AUR"
  useradd -m builder 2>/dev/null || true
  echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder
  mkdir -p "$LOCALREPO"; chown builder "$LOCALREPO"
  for p in "${AUR_NEEDED[@]}"; do
    sudo -u builder bash -c "cd ~ && rm -rf '$p' && git clone --depth 1 https://aur.archlinux.org/$p.git && cd '$p' && makepkg -s --noconfirm --needed && cp ./*.pkg.tar.* '$LOCALREPO/'"
  done
  ( cd "$LOCALREPO" && repo-add lisios-local.db.tar.gz ./*.pkg.tar.* >/dev/null )
  # локальный репозиторий для mkarchiso (внутри профиля) и для контейнера
  for conf in /etc/pacman.conf "$PROFILE/pacman.conf"; do
    grep -q '^\[lisios-local\]' "$conf" || sed -i "0,/^\[core\]/s||[lisios-local]\nSigLevel = Optional TrustAll\nServer = file://$LOCALREPO\n\n[core]|" "$conf"
  done
  pacman -Sy >/dev/null
fi

# итоговый список: пакеты releng + наши (без дублей)
{ read_list "$PROFILE/packages.x86_64"; printf '%s\n' "${REQUIRED[@]}" "${FINAL_OPTIONAL[@]}"; } | sort -u > "$WORK/packages.final"
cp "$WORK/packages.final" "$PROFILE/packages.x86_64"
log "В образ войдёт пакетов: $(wc -l < "$PROFILE/packages.x86_64")"

# ---------------------------------------------------------------- 4. надстройка airootfs
log "Накладываю файлы LisiOS поверх профиля"
A="$PROFILE/airootfs"

# Убираем сетевую часть releng (networkd/iwd) - у нас NetworkManager
rm -rf "$A/etc/systemd/network" || true
for l in systemd-networkd.service systemd-networkd-wait-online.service iwd.service \
         sshd.service livecd-talk.service choose-mirror.service; do
  rm -f "$A/etc/systemd/system/multi-user.target.wants/$l" "$A/etc/systemd/system/$l"
done
rm -f "$A/etc/sudoers.d/g_wheel" "$A/root/.automated_script.sh" "$A/root/.zlogin"
rm -f "$A/etc/systemd/system/getty@tty1.service.d/autologin.conf"

cp -a "$WORK/src/profile/airootfs/." "$A/"

# Логотип и обои: берём пользовательские, иначе - заглушки
mkdir -p "$A/usr/share/lisios/branding" "$A/usr/share/lisios/wallpapers"
if [ -f "$WORK/src/assets/logo/logo.png" ]; then
  cp "$WORK/src/assets/logo/logo.png" "$A/usr/share/lisios/branding/logo.png"; echo "    логотип: пользовательский"
else
  cp "$WORK/src/assets/logo/logo.placeholder.png" "$A/usr/share/lisios/branding/logo.png"
  warn "assets/logo/logo.png не найден - используется ЗАГЛУШКА. Положите свой логотип в assets/logo/logo.png"
fi
cp -a "$WORK/src/assets/wallpapers/." "$A/usr/share/lisios/wallpapers/"
# Plymouth-тема использует тот же логотип
mkdir -p "$A/usr/share/plymouth/themes/lisios"
cp "$A/usr/share/lisios/branding/logo.png" "$A/usr/share/plymouth/themes/lisios/logo.png"

# Зеркала для pacman внутри live-системы и установленной системы
mkdir -p "$A/etc/pacman.d"
cat > "$A/etc/pacman.d/mirrorlist" <<'EOF'
Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch
Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch
Server = https://mirrors.kernel.org/archlinux/$repo/os/$arch
EOF

# Включаем сервисы (симлинки создаём здесь, чтобы не зависеть от Windows/git)
W="$A/etc/systemd/system/multi-user.target.wants"; mkdir -p "$W" "$A/etc/systemd/system/bluetooth.target.wants"
ln -sf /usr/lib/systemd/system/NetworkManager.service "$W/NetworkManager.service"
ln -sf /usr/lib/systemd/system/bluetooth.service "$W/bluetooth.service"
ln -sf /usr/lib/systemd/system/systemd-timesyncd.service "$W/systemd-timesyncd.service"
ln -sf /etc/systemd/system/lisios-live-setup.service "$W/lisios-live-setup.service"
ln -sf /usr/lib/systemd/system/NetworkManager-dispatcher.service "$A/etc/systemd/system/dbus-org.freedesktop.nm-dispatcher.service"
mkdir -p "$A/etc/systemd/system/network-online.target.wants"
ln -sf /usr/lib/systemd/system/NetworkManager-wait-online.service "$A/etc/systemd/system/network-online.target.wants/NetworkManager-wait-online.service"

# Права на файлы (profiledef.sh)
PERMS=$(cat <<'EOF'
  ["/usr/local/bin/lisios-session"]="0:0:755"
  ["/usr/local/bin/lisios-installer"]="0:0:755"
  ["/usr/local/bin/lisios-install-cli"]="0:0:755"
  ["/usr/local/bin/lisios-settings"]="0:0:755"
  ["/usr/local/bin/lisios-set-boot-image"]="0:0:755"
  ["/usr/local/bin/lisios-live-setup"]="0:0:755"
  ["/usr/local/bin/lisios-shell"]="0:0:755"
  ["/usr/local/bin/lisios-gamemode"]="0:0:755"
  ["/usr/lib/lisios/gamemode/helper.py"]="0:0:755"
  ["/usr/lib/lisios/gamemode/run.py"]="0:0:755"
  ["/etc/sudoers.d/10-lisios"]="0:0:440"
EOF
)
python3 - "$PROFILE/profiledef.sh" "$PERMS" <<'PY'
import re, sys
path, perms = sys.argv[1], sys.argv[2]
s = open(path).read()
s = s.replace("file_permissions=(", "file_permissions=(\n" + perms, 1)
def setvar(name, value):
    global s
    s = re.sub(r'(?m)^' + name + r'=.*$', lambda m: name + '=' + value, s)
setvar("iso_name", '"lisios"')
setvar("iso_label", '"LISIOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"')
setvar("iso_publisher", '"LisiOS"')
setvar("iso_application", '"LisiOS Live/Installer"')
open(path, "w").write(s)
PY

# Фирменное имя в меню загрузчиков
grep -rIl 'Arch Linux' "$PROFILE/syslinux" "$PROFILE/grub" "$PROFILE/efiboot" 2>/dev/null | xargs -r sed -i 's/Arch Linux install medium/LisiOS Live\/Installer/g; s/Arch Linux/LisiOS/g'
echo "lisios" > "$A/etc/hostname"

# ---------------------------------------------------------------- 5. сборка
log "Собираю ISO (это займёт 10-30 минут)"
mkdir -p "$WORK/tmp"
log "Проверяю QML-оболочку (импорты Quickshell)"
python3 "$WORK/src/scripts/check-shell.py" "$A/usr/share/lisios/shell" || die "QML-оболочка не прошла проверку - см. сообщения выше"
for p in hyprland quickshell; do pacman -Si "$p" 2>/dev/null | grep -m1 '^Version' | sed "s/^/$p /"; done

mkarchiso -v -w "$WORK/tmp" -o "$OUT" "$PROFILE"

ISO=$(ls -1t "$OUT"/*.iso | head -1)
[ -s "$ISO" ] || die "ISO не создан"
( cd "$OUT" && sha256sum "$(basename "$ISO")" > "$(basename "$ISO").sha256" )
chmod 644 "$OUT"/* || true
log "ГОТОВО: $ISO ($(du -h "$ISO" | cut -f1))"
