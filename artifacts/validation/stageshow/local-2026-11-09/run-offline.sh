#!/bin/sh
set -eu
cd /home/maroun.guest/validation/runtime
exec env -i HOME=/home/maroun.guest PATH=/home/maroun.guest/validation/node-v22.22.3-linux-arm64/bin:/usr/bin:/bin CHROME_PATH=/home/maroun.guest/validation/browsers/chromium-1140/chrome-linux/chrome PLAYWRIGHT_BROWSERS_PATH=/home/maroun.guest/validation/browsers FONTCONFIG_FILE=/home/maroun.guest/validation/fontconfig.xml LD_LIBRARY_PATH=/home/maroun.guest/validation/sysroot/usr/lib/aarch64-linux-gnu:/home/maroun.guest/validation/sysroot/lib/aarch64-linux-gnu python3 ../offline-exec.py "$@"
