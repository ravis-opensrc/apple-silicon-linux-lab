# Source this file from ~/.zshrc or ~/.bashrc (zero hardcoded paths).
if [ -n "${BASH_VERSION:-}" ]; then
  _LINUX_LAB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
elif [ -n "${ZSH_VERSION:-}" ]; then
  _LINUX_LAB_DIR=$(cd "$(dirname "${(%):-%x}")" && pwd)
else
  _LINUX_LAB_DIR=$(pwd)
fi
alias setup-linux-lab="$_LINUX_LAB_DIR/bin/setup-linux-lab"
alias build-linux="$_LINUX_LAB_DIR/bin/build-linux"
alias launch-linux="$_LINUX_LAB_DIR/bin/launch-linux"
unset _LINUX_LAB_DIR
