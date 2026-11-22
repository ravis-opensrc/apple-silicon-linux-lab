#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /run /sys/kernel/debug /sys/kernel/tracing /sys/fs/cgroup /mnt/src
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /run
mount -t debugfs debugfs /sys/kernel/debug
mount -t tracefs tracefs /sys/kernel/tracing
mount -t cgroup2 none /sys/fs/cgroup 2>/dev/null || true
mount -t 9p -o trans=virtio,version=9p2000.L,ro linuxsrc /mnt/src 2>/dev/null || true

guest_host="linux-lab"
smoke_paths=""
for param in $(cat /proc/cmdline); do
  case "$param" in
    lab.hostname=*) guest_host=${param#lab.hostname=} ;;
    lab.smoke_paths=*) smoke_paths=${param#lab.smoke_paths=} ;;
  esac
done
hostname "$guest_host"

ip link set lo up
ip link set eth0 up 2>/dev/null && udhcpc -i eth0 -q -b >/run/udhcpc.log 2>&1 &
ssh-keygen -A >/run/ssh-keygen.log 2>&1
/usr/sbin/sshd -E /run/sshd.log
echo
echo "LINUX_LAB_BOOTED $(uname -r)"
echo 'Root console; exit the shell to power off. QEMU: Ctrl-a x to quit.'
if grep -q 'lab.smoke=1' /proc/cmdline; then
  status=0
  test -d /sys/fs/cgroup || status=1
  test -d /mnt/src/kernel || status=1
  test -f /proc/config.gz || status=1
  if [ -n "$smoke_paths" ]; then
    OLD_IFS=$IFS
    IFS=,
    for p in $smoke_paths; do
      [ -z "$p" ] && continue
      test -e "$p" || status=1
    done
    IFS=$OLD_IFS
  fi
  if dmesg | grep -Eq '(^|\])[[:space:]]*not ok [0-9]'; then status=1; fi
  echo "LINUX_LAB_SMOKE_STATUS=$status"
  sync
  poweroff -f
fi
while :; do
  setsid -c /bin/sh < /dev/ttyAMA0 > /dev/ttyAMA0 2>&1
  sync
  poweroff -f
  sleep 1
done
