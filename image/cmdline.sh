# The kernel command line, 01-boot-layer.md §6, verbatim — and in exactly one place, so
# the GRUB menu and live-build's own bootappend cannot drift apart.
#
#   quiet loglevel=3   boot messages do not compete for the panel
#   panic=0            a kernel panic HALTS with the message visible, rather than
#                      rebooting it away
#   nopersistence      belt and braces: live-boot is already amnesic without it
#   nohibernate        a closed lid must not write RAM holding a seed to disk
#   init_on_free=1     §5's RAM wipe; a steady-state allocator cost, not a shutdown pass
#   random.trust_cpu=off
#                      §8: withdraws RDSEED/RDRAND's readiness credit. RDSEED is still
#                      mixed into every extraction; it just never decides readiness alone
#   vt.global_cursor_default=0
#                      no blinking cursor behind the appliance
#
# There is no `noswap` kernel parameter. §4 says so explicitly; do not cargo-cult one in.
AOBS_CMDLINE="boot=live quiet loglevel=3 panic=0 nopersistence nohibernate init_on_free=1 random.trust_cpu=off vt.global_cursor_default=0"

# §7: toram is the default entry, so the user can pull the stick once booted and yanking
# it cannot kill a session mid-signature.
AOBS_CMDLINE_TORAM="${AOBS_CMDLINE} toram"
