#!/bin/bash
# Run only on a new, dedicated Ubuntu 24.04 VM, as root.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run as root on the dedicated judge VM.' >&2
    exit 1
fi
if [ "$(dpkg --print-architecture)" != amd64 ]; then
    echo 'This setup targets Ubuntu 24.04 amd64.' >&2
    exit 1
fi
if [ -e /srv/judge-root ] || [ -e /var/lib/judge-sandbox.img ]; then
    echo 'Existing runtime or disk image found; refusing to overwrite it.' >&2
    exit 1
fi
if getent passwd | awk -F: '$3 >= 60000 && $3 < 60100 { found=1 } END { exit !found }'; then
    echo 'Sandbox UID range 60000-60099 is already in use.' >&2
    exit 1
fi
apt-get update
apt-get install -y build-essential git libcap-dev libseccomp-dev libsystemd-dev \
    pkg-config asciidoc xsltproc docbook-xsl debootstrap quota e2fsprogs \
    python3.12-venv
useradd --system --create-home --shell /usr/sbin/nologin contest-judge
install -d -o contest-judge -g contest-judge -m 0700 /var/lib/university-judge
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
git clone --branch v2.7 --depth 1 https://github.com/ioi/isolate.git "$build_dir/isolate"
make -C "$build_dir/isolate" -j2
make -C "$build_dir/isolate" install
cat > /usr/local/etc/isolate <<'CONFIG'
box_root = /var/local/lib/isolate
lock_root = /run/isolate/locks
cg_root = auto:/run/isolate/cgroup
first_uid = 60000
first_gid = 60000
num_boxes = 100
syscall_flags = 31
CONFIG
chmod 0644 /usr/local/etc/isolate

# A dedicated quota-enabled filesystem bounds total sandbox disk usage.
fallocate -l 2G /var/lib/judge-sandbox.img
chmod 0600 /var/lib/judge-sandbox.img
mkfs.ext4 -F -O quota /var/lib/judge-sandbox.img
install -d -m 0755 /var/local/lib/isolate
printf '%s\n' '/var/lib/judge-sandbox.img /var/local/lib/isolate ext4 loop,usrquota 0 0' >> /etc/fstab
mount /var/local/lib/isolate

# This runtime contains compilers and libraries, never application files/secrets.
debootstrap --variant=minbase --include=g++,python3 noble /srv/judge-root \
    http://archive.ubuntu.com/ubuntu
# Only these four harmless devices are exposed by the sandbox.
rm -rf /srv/judge-root/dev
install -d -m 0755 /srv/judge-root/dev
mknod -m 0666 /srv/judge-root/dev/null c 1 3
mknod -m 0666 /srv/judge-root/dev/zero c 1 5
mknod -m 0666 /srv/judge-root/dev/random c 1 8
mknod -m 0666 /srv/judge-root/dev/urandom c 1 9
chown -R root:root /srv/judge-root
find /srv/judge-root -type f -exec chmod go-w,u-s,g-s {} +
find /srv/judge-root -type d -exec chmod go-w {} +
swapoff -a
# Persist swap disablement in the VM configuration before rebooting.
sysctl -w fs.protected_hardlinks=1
systemctl daemon-reload
systemctl enable --now isolate.service
/usr/local/bin/isolate --check-config
/usr/local/bin/isolate-check-environment
printf '%s\n' 'Install the project and worker environment; run the isolation tests before enabling the worker.'
