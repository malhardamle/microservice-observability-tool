from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import (
	parse_cpu_metrics_output,
	parse_disk_metrics_output,
	parse_memory_metrics_output,
	parse_network_metrics_output,
)


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


if __name__ == "__main__":
	unittest.main()
