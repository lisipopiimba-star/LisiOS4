#!/usr/bin/env bash
# Проверка ISO в виртуальной машине QEMU (Linux). Реальные диски НЕ трогаются: диск - файл-образ.
#   scripts/test-vm.sh out/lisios-*.iso [--bios]
set -euo pipefail
ISO="${1:?укажите путь к ISO}"; MODE="${2:-uefi}"
DISK="${DISK:-/tmp/lisios-test.qcow2}"
[ -f "$DISK" ] || qemu-img create -f qcow2 "$DISK" 40G
ARGS=(-m 4096 -smp 4 -cdrom "$ISO" -boot d -drive file="$DISK",if=virtio
      -device virtio-vga-gl -display gtk,gl=on -device qemu-xhci -device usb-tablet
      -nic user,model=virtio-net-pci)
[ -w /dev/kvm ] && ARGS+=(-enable-kvm -cpu host)
if [ "$MODE" != "--bios" ]; then
  OVMF=$(ls /usr/share/OVMF/OVMF_CODE*.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd /usr/share/edk2/ovmf/OVMF_CODE.fd 2>/dev/null | head -1 || true)
  [ -n "$OVMF" ] && ARGS+=(-drive if=pflash,format=raw,readonly=on,file="$OVMF")
fi
exec qemu-system-x86_64 "${ARGS[@]}"
