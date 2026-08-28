#!/bin/bash
# Unit test for fpgas-felboot.sh: a stub sunxi-fel records its argv.
# Run: bash felboot/test_felboot.sh   (scratch dir under the repo's tmp/, removed on exit)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
scratch_root="$here/../tmp"
mkdir -p "$scratch_root"
scratch=$(mktemp -d "$scratch_root/felboot-test.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin"
cat > "$scratch/bin/sunxi-fel" <<'STUB'
#!/bin/bash
echo "$@" >> "$FELBOOT_TEST_LOG"
[ "${FELBOOT_TEST_FAIL:-0}" = "1" ] && exit 1
exit 0
STUB
chmod +x "$scratch/bin/sunxi-fel"
export FELBOOT_TEST_LOG="$scratch/log" PATH="$scratch/bin:$PATH" FPGAS_FELBOOT_IMAGE="$scratch/uboot.bin" FPGAS_FELBOOT_RETRY_SLEEP=0
: > "$scratch/uboot.bin"

# 1. bus/dev from a kernel device name like 1-1.2.2 -> sunxi-fel --dev 001:012
printf '12\n' > "$scratch/devnum"; printf '1\n' > "$scratch/busnum"
FPGAS_FELBOOT_SYSFS="$scratch" "$here/fpgas-felboot.sh" 1-1.2.2
grep -qx -- "--dev 001:012 uboot $scratch/uboot.bin" "$scratch/log" || { echo "FAIL: argv was: $(cat "$scratch/log")"; exit 1; }

# 2. retries three times then fails
: > "$scratch/log"
if FELBOOT_TEST_FAIL=1 FPGAS_FELBOOT_SYSFS="$scratch" "$here/fpgas-felboot.sh" 1-1.2.2; then echo "FAIL: expected non-zero exit"; exit 1; fi
[ "$(wc -l < "$scratch/log")" = 3 ] || { echo "FAIL: expected 3 attempts, got $(wc -l < "$scratch/log")"; exit 1; }
echo "PASS"
