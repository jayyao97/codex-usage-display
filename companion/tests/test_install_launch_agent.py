import unittest
from pathlib import Path

from companion.install_launch_agent import build_plist


class InstallLaunchAgentTests(unittest.TestCase):
    def test_plist_runs_prepared_venv_and_restarts_only_after_failure(self):
        repository = Path("/tmp/codex-usage-display")
        home = Path("/Users/example")

        config = build_plist(repository, home)

        self.assertEqual(
            config["ProgramArguments"],
            [
                str(repository / "companion/.venv/bin/python"),
                "-m",
                "companion.codex_display",
            ],
        )
        self.assertEqual(config["WorkingDirectory"], str(repository))
        self.assertEqual(
            config["EnvironmentVariables"]["PYTHONPATH"],
            str(repository),
        )
        self.assertEqual(
            config["EnvironmentVariables"]["CODEX_DISPLAY_LOG"],
            str(home / "Library/Logs/CodexUsageDisplay/companion.log"),
        )
        self.assertTrue(config["RunAtLoad"])
        self.assertEqual(config["KeepAlive"], {"SuccessfulExit": False})
        self.assertGreaterEqual(config["ThrottleInterval"], 10)
        self.assertEqual(config["StandardOutPath"], "/dev/null")
        self.assertEqual(config["StandardErrorPath"], "/dev/null")


if __name__ == "__main__":
    unittest.main()
