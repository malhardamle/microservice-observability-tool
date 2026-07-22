from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import (
	ProcessIOSnapshot,
	discover_pid_for_port,
	format_pid_io_metrics,
	parse_cpu_metrics_output,
	parse_disk_metrics_output,
	parse_listening_pids_output,
	parse_memory_metrics_output,
	parse_network_metrics_output,
	parse_pid_cpu_metrics_output,
	parse_pid_io_output,
	parse_pid_memory_metrics_output,
)
from unittest.mock import patch


MPSTAT_OUTPUT = """
Linux 6.8.0-1057-raspi (hayes-valley)   07/02/2026  _aarch64_  (4 CPU)

10:02:01 PM  CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal   %guest   %gnice   %idle
10:02:02 PM  all    4.00    0.00    1.00    0.50    0.00    0.50    0.00     0.00     0.00   94.00
10:02:02 PM    0    8.00    0.00    1.00    0.00    0.00    1.00    0.00     0.00     0.00   90.00
10:02:02 PM    1    4.00    0.00    2.00    0.00    0.00    1.00    0.00     0.00     0.00   93.00
10:02:02 PM    2    3.00    0.00    1.00    1.00    0.00    0.00    0.00     0.00     0.00   95.00
10:02:02 PM    3    1.00    0.00    0.00    1.00    0.00    0.00    0.00     0.00     0.00   98.00

Average:     CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal   %guest   %gnice   %idle
Average:     all    4.00    0.00    1.00    0.50    0.00    0.50    0.00     0.00     0.00   94.00
Average:       0    8.00    0.00    1.00    0.00    0.00    1.00    0.00     0.00     0.00   90.00
Average:       1    4.00    0.00    2.00    0.00    0.00    1.00    0.00     0.00     0.00   93.00
Average:       2    3.00    0.00    1.00    1.00    0.00    0.00    0.00     0.00     0.00   95.00
Average:       3    1.00    0.00    0.00    1.00    0.00    0.00    0.00     0.00     0.00   98.00
"""

VMSTAT_OUTPUT = """
     8192000 K total memory
     6029312 K used memory
      934112 K active memory
     1228800 K inactive memory
     2162688 K free memory
      262144 K buffer memory
      786432 K swap cache
     1048572 K total swap
           0 K used swap
     1048572 K free swap
"""

SAR_OUTPUT = """
Linux 6.8.0-1057-raspi (hayes-valley)   07/02/2026  _aarch64_  (4 CPU)

10:03:01 PM     IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
10:03:02 PM        lo      3.00      3.00      0.30      0.30      0.00      0.00      0.00      0.00
10:03:02 PM     wlan0     52.00     41.00     12.50      8.25      0.00      0.00      0.00      0.00

Average:        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
Average:           lo      3.00      3.00      0.30      0.30      0.00      0.00      0.00      0.00
Average:        wlan0     52.00     41.00     12.50      8.25      0.00      0.00      0.00      0.00
"""

IOSTAT_OUTPUT = """
Linux 6.8.0-1057-raspi (hayes-valley)   07/02/2026      _aarch64_        (4 CPU)

Device             tps    kB_read/s    kB_wrtn/s    kB_dscd/s    kB_read    kB_wrtn    kB_dscd
mmcblk0          10.00        12.00        40.00         0.00         12         40          0

Device             tps    kB_read/s    kB_wrtn/s    kB_dscd/s    kB_read    kB_wrtn    kB_dscd
mmcblk0           8.00        20.00        64.00         0.00         20         64          0
"""

PIDSTAT_CPU_OUTPUT = """
Linux 6.8.0-1057-raspi (hayes-valley)   07/02/2026  _aarch64_  (4 CPU)

10:10:01 PM   UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
10:10:02 PM  1000      4242    5.00    1.00    0.00    0.00    6.00     2  service

Average:      UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
Average:     1000      4242    5.00    1.00    0.00    0.00    6.00     -  service
"""

PIDSTAT_MEMORY_OUTPUT = """
Linux 6.8.0-1057-raspi (hayes-valley)   07/02/2026  _aarch64_  (4 CPU)

10:10:01 PM   UID       PID  minflt/s  majflt/s     VSZ      RSS   %MEM  Command
10:10:02 PM  1000      4242      2.00      0.00  1048576    65536   1.50  service

Average:      UID       PID  minflt/s  majflt/s     VSZ      RSS   %MEM  Command
Average:     1000      4242      2.00      0.00  1048576    65536   1.50  service
"""

PROC_PID_IO_OUTPUT = """
rchar: 166946
wchar: 59853
syscr: 463
syscw: 28
read_bytes: 0
write_bytes: 4096
cancelled_write_bytes: 0
"""

SS_OUTPUT_SINGLE_PID = """
LISTEN 0      4096              *:8080             *:*    users:(("service",pid=4242,fd=3))
"""

SS_OUTPUT_MULTI_PID = """
LISTEN 0      4096              *:8080             *:*    users:(("service",pid=4242,fd=3),("service",pid=5252,fd=4))
"""


class CollectorParserTests(unittest.TestCase):
	def test_parse_cpu_metrics_output(self) -> None:
		lines = parse_cpu_metrics_output(MPSTAT_OUTPUT)
		self.assertIn('raspberry_pi_cpu_usage_percent{cpu="cpu"} 6.00', lines)
		self.assertIn('raspberry_pi_cpu_usage_percent{cpu="cpu0"} 10.00', lines)
		self.assertIn('raspberry_pi_cpu_usage_percent{cpu="cpu3"} 2.00', lines)

	def test_parse_memory_metrics_output(self) -> None:
		lines = parse_memory_metrics_output(VMSTAT_OUTPUT)
		self.assertIn("raspberry_pi_memory_total_bytes 8388608000", lines)
		self.assertIn("raspberry_pi_memory_used_bytes 6174015488", lines)
		self.assertIn("raspberry_pi_memory_free_bytes 2214592512", lines)
		self.assertIn("raspberry_pi_memory_used_percent 73.60", lines)

	def test_parse_network_metrics_output(self) -> None:
		lines = parse_network_metrics_output(SAR_OUTPUT)
		self.assertNotIn('raspberry_pi_network_receive_bytes_per_second{iface="lo"} 307.20', lines)
		self.assertIn(
			'raspberry_pi_network_receive_bytes_per_second{iface="wlan0"} 12800.00',
			lines,
		)
		self.assertIn(
			'raspberry_pi_network_transmit_bytes_per_second{iface="wlan0"} 8448.00',
			lines,
		)

	def test_parse_disk_metrics_output(self) -> None:
		lines = parse_disk_metrics_output(IOSTAT_OUTPUT)
		self.assertIn(
			'raspberry_pi_disk_read_bytes_per_second{device="mmcblk0"} 20480.00',
			lines,
		)
		self.assertIn(
			'raspberry_pi_disk_write_bytes_per_second{device="mmcblk0"} 65536.00',
			lines,
		)

	def test_parse_pid_cpu_metrics_output(self) -> None:
		lines = parse_pid_cpu_metrics_output(PIDSTAT_CPU_OUTPUT, 4242)
		self.assertIn(
			'raspberry_pi_app_cpu_usage_percent{pid="4242",command="service"} 6.00',
			lines,
		)

	def test_parse_pid_memory_metrics_output(self) -> None:
		lines = parse_pid_memory_metrics_output(PIDSTAT_MEMORY_OUTPUT, 4242)
		self.assertIn(
			'raspberry_pi_app_memory_virtual_bytes{pid="4242",command="service"} 1073741824',
			lines,
		)
		self.assertIn(
			'raspberry_pi_app_memory_resident_bytes{pid="4242",command="service"} 67108864',
			lines,
		)
		self.assertIn(
			'raspberry_pi_app_memory_percent{pid="4242",command="service"} 1.50',
			lines,
		)

	def test_parse_pid_io_output(self) -> None:
		counters = parse_pid_io_output(PROC_PID_IO_OUTPUT)
		self.assertEqual(counters["rchar"], 166946)
		self.assertEqual(counters["wchar"], 59853)
		self.assertEqual(counters["read_bytes"], 0)
		self.assertEqual(counters["write_bytes"], 4096)

	def test_format_pid_io_metrics(self) -> None:
		previous_snapshot = ProcessIOSnapshot(
			pid=4242,
			counters={
				"rchar": 1024,
				"wchar": 2048,
				"read_bytes": 4096,
				"write_bytes": 8192,
			},
		)
		current_snapshot = ProcessIOSnapshot(
			pid=4242,
			counters={
				"rchar": 3072,
				"wchar": 6144,
				"read_bytes": 12288,
				"write_bytes": 20480,
			},
		)
		lines = format_pid_io_metrics(4242, "service", current_snapshot, previous_snapshot, 2)
		self.assertIn(
			'raspberry_pi_app_io_read_chars_bytes_per_second{pid="4242",command="service"} 1024.00',
			lines,
		)
		self.assertIn(
			'raspberry_pi_app_io_write_chars_bytes_per_second{pid="4242",command="service"} 2048.00',
			lines,
		)
		self.assertIn(
			'raspberry_pi_app_disk_read_bytes_per_second{pid="4242",command="service"} 4096.00',
			lines,
		)
		self.assertIn(
			'raspberry_pi_app_disk_write_bytes_per_second{pid="4242",command="service"} 6144.00',
			lines,
		)

	def test_parse_listening_pids_output(self) -> None:
		self.assertEqual(parse_listening_pids_output(SS_OUTPUT_SINGLE_PID), [4242])

	def test_discover_pid_for_port(self) -> None:
		with patch("main.run_command", return_value=SS_OUTPUT_SINGLE_PID) as mock_run:
			self.assertEqual(discover_pid_for_port(8080), 4242)
		mock_run.assert_called_once_with(["ss", "-ltnpH", "sport = :8080"])

	def test_discover_pid_for_port_rejects_multiple_matches(self) -> None:
		with patch("main.run_command", return_value=SS_OUTPUT_MULTI_PID):
			with self.assertRaisesRegex(RuntimeError, "multiple listening processes found"):
				discover_pid_for_port(8080)


if __name__ == "__main__":
	unittest.main()
