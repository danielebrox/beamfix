import contextlib
import io
import json
import re
import unittest
from unittest.mock import patch

from beamfix.cli import main
from beamfix.diagnose import diagnose
from beamfix.models import Connector, Snapshot
from beamfix.terminal import Terminal, cells, render_doctor
from beamfix.troubleshoot import run


ANSI = re.compile(r"\x1b\[[0-9;]*m")


class TTYBuffer(io.StringIO):
    def isatty(self):
        return True


def sample():
    return Snapshot("Linux", "test", "wayland", "KDE", connectors=[
        Connector("card0-HDMI-A-1", "external", "connected", "disabled", ("1920x1080",)),
    ])


class TerminalTests(unittest.TestCase):
    def capture(self, **kwargs):
        lines = []
        ui = Terminal(write=lines.append, environ={"TERM": "xterm-256color"},
                      encoding="utf-8", **kwargs)
        return ui, lines

    def test_tty_uses_color_but_piped_output_is_plain(self):
        for tty in (True, False):
            with self.subTest(tty=tty):
                ui, lines = self.capture(is_tty=tty)
                ui.banner("Display health check", "test")
                ui.status("CHECK", "Output disabled", "warning")
                output = "\n".join(lines)
                self.assertEqual("\x1b[" in output, tty)
                self.assertIn("[CHECK]", output)
                if not tty:
                    self.assertTrue(output.isascii())

    def test_no_color_dumb_terminal_and_explicit_plain(self):
        for env, plain in (({"NO_COLOR": ""}, False), ({"NO_COLOR": "1"}, False),
                           ({"TERM": "dumb"}, False), ({"TERM": "xterm"}, True)):
            with self.subTest(env=env, plain=plain):
                lines = []
                ui = Terminal(write=lines.append, is_tty=True, environ=env, plain=plain)
                ui.banner("Display health check", "test")
                ui.step(1, "Reconnect", "Check detection", "Disconnect and reconnect the cable.")
                self.assertNotIn("\x1b", "\n".join(lines))

    def test_ascii_encoding_has_no_box_drawing(self):
        lines = []
        ui = Terminal(write=lines.append, is_tty=True, encoding="ascii", environ={})
        ui.banner("Guide", "test")
        ui.step(1, "Check input", "Verify the input", "Select HDMI 1.")
        self.assertTrue(ANSI.sub("", "\n".join(lines)).isascii())

    def test_narrow_layout_preserves_long_tokens_and_wide_characters(self):
        ui, lines = self.capture(is_tty=True, width=36)
        token = "card1-DisplayPort-" + "x" * 70
        ui.option(12, token)
        ui.step(1, "Check input", "Verify the selected input", "外部画面 " * 15)
        visible = [ANSI.sub("", line) for line in lines]
        self.assertTrue(all(cells(line) <= 36 for line in visible))
        self.assertIn(token, "".join(line.strip() for line in visible))

    def test_device_data_cannot_inject_ansi_or_newlines(self):
        ui, lines = self.capture(is_tty=True)
        payload = "screen\x1b[2J\nFAKE\r\x07"
        ui.option(1, payload)
        ui.field("Output", payload)
        output = "\n".join(lines)
        self.assertNotIn("\x1b[2J", output)
        self.assertNotIn("\r", output)
        self.assertNotIn("\x07", output)
        self.assertIn("screen?[2J?FAKE??", ANSI.sub("", output))

    def test_json_stays_clean_even_on_a_color_terminal(self):
        for args in (["doctor", "--json"], ["--plain", "doctor", "--json"]):
            output = TTYBuffer()
            with patch("beamfix.cli.collect", return_value=sample()), contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 1)
            data = json.loads(output.getvalue())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["visual_confirmation"], "not_performed")
            self.assertNotIn("\x1b", output.getvalue())

    def test_plain_flag_works_before_or_after_subcommand(self):
        for args in (["--plain", "doctor"], ["doctor", "--plain"]):
            output = TTYBuffer()
            with patch("beamfix.cli.collect", return_value=sample()), contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 1)
            self.assertNotIn("\x1b", output.getvalue())
            self.assertIn("NEXT STEPS", output.getvalue())
        with patch("beamfix.troubleshoot.run", return_value=2) as guided:
            main(["troubleshoot", "--plain"])
            guided.assert_called_once_with(plain=True, try_fix=False)

    def test_doctor_unknown_state_is_not_presented_as_success(self):
        data = sample()
        data.errors.append("DRM unavailable")
        ui, lines = self.capture(is_tty=True, width=50)
        render_doctor(data, diagnose(data), 2, terminal=ui)
        output = ANSI.sub("", "\n".join(lines))
        self.assertIn("[UNKNOWN]", output)
        self.assertNotIn("No issues detected", output)
        self.assertNotIn("[CONFIRMED]", output)
        self.assertLess(output.index("NEXT STEPS"), output.index("DISPLAYS"))
        self.assertTrue(all(cells(line) <= 50 for line in output.splitlines()))

    def test_colored_guided_session_retains_confirmation_and_summary(self):
        ui, lines = self.capture(is_tty=True, width=60)
        answers = iter(["1", "1", "1", "1"])
        code = run(snapshot_reader=sample, read=lambda _: next(answers), terminal=ui)
        output = ANSI.sub("", "\n".join(lines))
        self.assertEqual(code, 0)
        for label in ("TRY 01", "WHAT TO DO", "VERIFY THE RESULT", "SUMMARY", "[CONFIRMED]"):
            self.assertIn(label, output)
        self.assertTrue(all(cells(line) <= 60 for line in output.splitlines()))

    def test_interrupted_guide_is_never_green_confirmed(self):
        ui, lines = self.capture(is_tty=True)
        code = run(read=lambda _: "0", terminal=ui)
        output = "\n".join(lines)
        self.assertEqual(code, 2)
        self.assertIn("[NOT CONFIRMED]", output)
        self.assertNotIn("\x1b[32m", output)


if __name__ == "__main__":
    unittest.main()
