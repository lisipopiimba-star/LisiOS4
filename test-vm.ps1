# Проверка ISO в QEMU на Windows (winget install SoftwareFreedomConservancy.QEMU).
# Виртуальный диск - файл, реальные диски и Windows не затрагиваются.
param([Parameter(Mandatory=$true)][string]$Iso)
$q = "C:\Program Files\qemu"
$disk = "$env:TEMP\lisios-test.qcow2"
if (-not (Test-Path $disk)) { & "$q\qemu-img.exe" create -f qcow2 $disk 40G }
& "$q\qemu-system-x86_64.exe" -m 4096 -smp 4 -accel whpx -cdrom $Iso -boot d `
  -drive file=$disk,if=virtio -vga std -device qemu-xhci -device usb-tablet -nic user,model=virtio-net-pci
