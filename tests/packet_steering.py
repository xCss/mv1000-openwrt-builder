#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "files/etc/uci-defaults/99-packet-steering"


class PacketSteeringTests(unittest.TestCase):
    def run_case(self, cpus, existing=None, globals_present=True, service_present=True, commit_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "service"
            service.write_text('#!/bin/sh\necho "service $*" >> "$TEST_LOG"\n', newline="\n")
            service.chmod(0o755)
            if not service_present:
                service.unlink()
            cpu_stat = root / "stat"
            cpu_stat.write_text("cpu 0 0 0 0\n" + "".join(f"cpu{number} 0 0 0 0\n" for number in range(cpus)), newline="\n")
            uci = root / "uci"
            uci.write_text('''#!/bin/sh
if [ "$1" = -q ]; then shift; fi
if [ "$1" = get ]; then
    case "$2" in
        'network.@globals[0].packet_steering')
            [ -n "$TEST_EXISTING" ] || exit 1
            echo "$TEST_EXISTING" ;;
        'network.@globals[0]')
            [ "$TEST_GLOBALS" = 1 ] || exit 1
            echo globals ;;
        *) exit 2 ;;
    esac
else
    echo "uci $*" >> "$TEST_LOG"
    if [ "$1" = commit ] && [ "$TEST_COMMIT_FAILS" = 1 ]; then exit 1; fi
fi
''', newline="\n")
            uci.chmod(0o755)
            script = root / "defaults"
            script.write_text(SCRIPT.read_text().replace("/etc/init.d/packet_steering", service.as_posix())
                              .replace("/proc/stat", cpu_stat.as_posix()), newline="\n")
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                               TEST_LOG=(root / "log").as_posix(), TEST_EXISTING=existing or "",
                               TEST_GLOBALS=str(int(globals_present)), TEST_COMMIT_FAILS=str(int(commit_fails)))
            result = subprocess.run(["sh", str(script)], env=environment, capture_output=True, text=True)
            log = (root / "log").read_text() if (root / "log").exists() else ""
            return result.returncode, log

    def test_multicore_enables_standard_service(self):
        for cpus in (2, 4, 16):
            with self.subTest(cpus=cpus):
                code, log = self.run_case(cpus)
                self.assertEqual(code, 0)
                self.assertEqual(log, "uci set network.@globals[0].packet_steering=2\nuci commit network\nservice enable\nservice reload\n")

    def test_single_core_leaves_configuration_untouched(self):
        self.assertEqual(self.run_case(1), (0, ""))

    def test_explicit_user_choices_are_preserved(self):
        for existing in ("0", "1", "2"):
            with self.subTest(existing=existing):
                self.assertEqual(self.run_case(2, existing=existing), (0, ""))

    def test_missing_globals_are_created(self):
        code, log = self.run_case(2, globals_present=False)
        self.assertEqual(code, 0)
        self.assertTrue(log.startswith("uci set network.globals=globals\n"))

    def test_missing_service_is_skipped(self):
        self.assertEqual(self.run_case(2, service_present=False), (0, ""))

    def test_unreadable_cpu_count_requests_retry(self):
        code, log = self.run_case(0)
        self.assertNotEqual(code, 0)
        self.assertEqual(log, "")

    def test_commit_failure_does_not_start_service(self):
        code, log = self.run_case(2, commit_fails=True)
        self.assertNotEqual(code, 0)
        self.assertNotIn("service", log)


if __name__ == "__main__":
    unittest.main()
