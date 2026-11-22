#!/bin/bash
set -euo pipefail
rootfs_name=$1
version=3.24.4
file="alpine-minirootfs-$version-aarch64.tar.gz"
sha=4b14c18f7e90a063b61462ea1462a5732c154bf6adad594974fe6487cd98a8de
mkdir -p /work/rootfs-cache
cd /work/rootfs-cache
if [[ ! -f "$file" ]]; then
  curl -fL --retry 3 "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/$file" -o "$file.part"
  mv "$file.part" "$file"
fi
echo "$sha  $file" | sha256sum -c -
root=$(mktemp -d /work/rootfs.XXXXXX)
trap 'rm -rf "$root"' EXIT
tar -xzf "$file" -C "$root"
cp /etc/resolv.conf "$root/etc/resolv.conf"
chroot "$root" /sbin/apk add --no-cache alpine-base bash python3 iproute2 procps util-linux util-linux-misc openssh
install -m 755 /lab/scripts/guest-init.sh "$root/sbin/lab-init"
install -d -m 700 "$root/root/.ssh"
install -m 600 /artifacts/ssh/id_ed25519.pub "$root/root/.ssh/authorized_keys"
cat > "$root/etc/ssh/sshd_config" <<'CONFIG'
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
Subsystem sftp internal-sftp
CONFIG
printf 'nameserver 10.0.2.3\n' > "$root/etc/resolv.conf"
mkdir -p "$root/sys" "$root/proc" "$root/dev" "$root/run" "$root/mnt/src"
truncate -s 2G "/artifacts/$rootfs_name.new"
mkfs.ext4 -q -F -L linux-lab -d "$root" "/artifacts/$rootfs_name.new"
mv "/artifacts/$rootfs_name.new" "/artifacts/$rootfs_name"
