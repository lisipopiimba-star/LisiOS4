#!/usr/bin/env bash
# Установка исправлений в УЖЕ ЗАПУЩЕННУЮ LisiOS (Live-ISO в виртуалке или установленную систему) без пересборки ISO.
# Запускать из терминала внутри LisiOS (Super+Enter) от обычного пользователя:
#     bash live-patch.sh [каталог_проекта]      # по умолчанию - каталог над scripts/
# На Live-ISO изменения живут в ОЗУ и пропадут после перезагрузки - для постоянного эффекта пересоберите ISO.
set -e
SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
A="$SRC/profile/airootfs"
[ -d "$A" ] || { echo "Не найден $A - укажите каталог распакованного проекта"; exit 1; }

echo "1/5 Статическая проверка QML"
python3 -I "$SRC/scripts/check-shell.py" "$A/usr/share/lisios/shell"

echo "2/5 Копирование оболочки и скриптов в систему"
sudo install -d /usr/share/lisios/shell
sudo cp -a "$A/usr/share/lisios/shell/." /usr/share/lisios/shell/
sudo install -m755 "$A/usr/local/bin/lisios-shell" "$A/usr/local/bin/lisios-session" /usr/local/bin/
sudo install -m644 "$A/usr/lib/lisios/settings/settings.py" /usr/lib/lisios/settings/settings.py
sudo cp -a "$A/etc/skel/.config/hypr/." /etc/skel/.config/hypr/
sudo install -d /usr/share/lisios/hypr /usr/lib/lisios/gamemode /usr/share/polkit-1/actions
sudo cp -a "$A/usr/share/lisios/hypr/." /usr/share/lisios/hypr/
# Game Mode: демон, привилегированный помощник (polkit), окно, ярлык
sudo cp -a "$A/usr/lib/lisios/gamemode/." /usr/lib/lisios/gamemode/
sudo chmod 755 /usr/lib/lisios/gamemode/helper.py /usr/lib/lisios/gamemode/run.py
sudo install -m644 "$A/usr/share/polkit-1/actions/org.lisios.gamemode.policy" /usr/share/polkit-1/actions/
sudo install -m755 "$A/usr/local/bin/lisios-gamemode" /usr/local/bin/
sudo install -m644 "$A/usr/share/applications/lisios-gamemode.desktop" /usr/share/applications/

echo "3/5 Конфигурация Hyprland в домашний каталог (старые файлы сохраняются как *.bak)"
mkdir -p ~/.config/hypr ~/.cache/lisios
for f in "$A"/etc/skel/.config/hypr/*; do
  b="$HOME/.config/hypr/$(basename "$f")"
  [ -f "$b" ] && ! cmp -s "$f" "$b" && cp "$b" "$b.bak"
  cp "$f" "$b"
done

echo "4/5 Перезапуск оболочки"
pkill -x quickshell 2>/dev/null || true
sleep 1
if [ -n "$WAYLAND_DISPLAY" ]; then
  lisios-shell --check && { setsid lisios-shell >/dev/null 2>&1 & sleep 1; echo "оболочка запущена"; }
else
  echo "Нет Wayland-сессии в этом терминале - пропускаю запуск"
fi

echo "5/5 Готово. Если менялся формат конфигурации Hyprland (hyprland.conf <-> lisios.lua),"
echo "    выйдите из сессии и войдите снова: hyprctl dispatch exit   (для Hyprland 0.57+: hyprctl dispatch 'hl.dsp.exit()')"
echo "    Журналы: ~/.cache/lisios/{session,shell,hypr-lua}.log"
