import unittest
from pathlib import Path

from companion.install_hook import belongs_to_display, updated_config


class InstallHookTests(unittest.TestCase):
    def test_install_preserves_foreign_hooks_and_is_idempotent(self):
        foreign = {
            "hooks": [
                {
                    "type": "command",
                    "command": "/usr/bin/python3 /tmp/foreign.py",
                }
            ]
        }
        initial = {
            "description": "Existing hooks",
            "hooks": {"Stop": [foreign], "SessionStart": [foreign]},
        }
        script = Path("/tmp/repository/.codex/hooks/codex_display_event.py")

        once = updated_config(initial, script, uninstall=False)
        twice = updated_config(once, script, uninstall=False)

        self.assertEqual(once, twice)
        self.assertEqual(once["description"], "Existing hooks")
        self.assertEqual(once["hooks"]["SessionStart"], [foreign])
        self.assertEqual(len(once["hooks"]["Stop"]), 2)
        self.assertTrue(belongs_to_display(once["hooks"]["Stop"][1]))

    def test_uninstall_only_removes_display_hooks(self):
        script = Path("/tmp/repository/.codex/hooks/codex_display_event.py")
        installed = updated_config({}, script, uninstall=False)
        installed["hooks"]["Stop"].append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/bin/python3 /tmp/foreign.py",
                    }
                ]
            }
        )

        removed = updated_config(installed, script, uninstall=True)

        self.assertNotIn("UserPromptSubmit", removed["hooks"])
        self.assertEqual(len(removed["hooks"]["Stop"]), 1)
        self.assertFalse(belongs_to_display(removed["hooks"]["Stop"][0]))


if __name__ == "__main__":
    unittest.main()
