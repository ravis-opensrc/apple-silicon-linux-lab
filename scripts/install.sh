#!/bin/bash
set -euo pipefail
lab_dir=$(cd "$(dirname "$0")/.." && pwd)
bin_dir=${LINUX_LAB_BIN_DIR:-$HOME/.local/bin}
mkdir -p "$bin_dir"

for cmd in setup-linux-lab build-linux launch-linux; do
  cat > "$bin_dir/$cmd" <<WRAP
#!/bin/bash
exec "$lab_dir/bin/$cmd" "\$@"
WRAP
  chmod 755 "$bin_dir/$cmd"
done

if [[ ! -f "$lab_dir/config.yaml" ]]; then
  cp "$lab_dir/config.yaml.example" "$lab_dir/config.yaml"
  echo "Created $lab_dir/config.yaml from config.yaml.example (edit source.path before building)."
fi

echo "Installed wrappers in $bin_dir: setup-linux-lab, build-linux, launch-linux"
echo "Ensure $bin_dir is in your PATH."
