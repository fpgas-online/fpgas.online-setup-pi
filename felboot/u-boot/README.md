# Vendored U-Boot images for FEL boot

`orangepi_pc_plus/u-boot-sunxi-with-spl.bin` is copied unmodified from Debian's
`u-boot-sunxi_2025.01-3+deb13u1_armhf.deb` (`usr/lib/u-boot/orangepi_pc_plus/`),
GPL-2.0-or-later, <https://deb.debian.org/debian/pool/main/u/u-boot/>.
Raspbian does not ship `u-boot-sunxi`, so the image is vendored here.

* sha256 of the `.bin`: `9f10a3532457b71006053028b013e7c73f86f55788872c8fba40ba1aa45f53cb` (559488 bytes)
* sha256 of the `.deb`: `c34a1e756612a10ba3fa2abe4bdc6c0dd685cc472628879b0fe153251073c36a`

It runs on the fpgas.online Orange Pi PC boards (same H3 + 1 GB DRAM as the PC Plus;
the extra eMMC/wifi nodes are harmless). It only has to bring the board to U-Boot's
distro-boot, which then DHCP+PXE-boots the real kernel from the netboot server.

Refresh: download the newer `.deb`, `dpkg-deb -x`, copy the file, update the hashes.
