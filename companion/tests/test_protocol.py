import json
import unittest

from companion.codex_display.metrics import Snapshot
from companion.codex_display.protocol import (
    decode_command,
    encode_result,
    encode_snapshot,
)


class ProtocolTests(unittest.TestCase):
    def test_snapshot_fits_single_negotiated_ble_packet(self):
        snapshot = Snapshot(
            generated_at=1_800_000_000,
            utc_offset_minutes=480,
            remaining_percent=96,
            limit_window_minutes=10080,
            quota_reset_seconds=604800,
            tokens_today=123456789,
            tokens_7d=987654321,
            reset_credits=3,
            next_credit_expiry_seconds=2592000,
            active_threads=12,
        )
        payload = encode_snapshot(snapshot, 42)
        decoded = json.loads(payload)
        self.assertLessEqual(len(payload), 180)
        self.assertEqual(decoded["r"], 96)
        self.assertEqual(decoded["u"], 10080)
        self.assertEqual(decoded["a"], 12)

    def test_accepts_allowlisted_command(self):
        command = decode_command(b'{"v":1,"sid":9,"id":7,"a":"refresh"}')
        self.assertEqual(command["id"], 7)
        self.assertEqual(command["a"], "refresh")

    def test_rejects_unknown_action(self):
        with self.assertRaisesRegex(ValueError, "不允许"):
            decode_command(b'{"v":1,"sid":9,"id":7,"a":"shell"}')

    def test_rejects_wrong_protocol(self):
        with self.assertRaisesRegex(ValueError, "协议版本"):
            decode_command(b'{"v":2,"sid":9,"id":7,"a":"refresh"}')

    def test_result_is_bounded(self):
        payload = encode_result(8, False, "x" * 100)
        decoded = json.loads(payload)
        self.assertEqual(decoded["ok"], 0)
        self.assertEqual(len(decoded["m"]), 48)


if __name__ == "__main__":
    unittest.main()
