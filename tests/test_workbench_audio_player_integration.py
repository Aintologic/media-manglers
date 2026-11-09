"""The platform media backend reports a file it cannot play (220: the Review Media Inbox's own
audio player was folded into the shared built-in player, whose own tests cover playback)."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtMultimedia import (  # noqa: E402
    QAudioOutput,
    QMediaPlayer,
)
from PySide6.QtWidgets import QApplication  # noqa: E402



class WorkbenchAudioPlayerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def _wait(self, predicate, timeout: float = 10.0) -> None:
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(max(1, int(timeout * 1000)))
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate())

    def test_real_player_reports_invalid_media_error(self) -> None:
        invalid = self.root / "invalid.wav"
        invalid.write_bytes(b"not a wave file")
        audio_output = QAudioOutput()
        player = QMediaPlayer()
        player.setAudioOutput(audio_output)
        errors: list[tuple[QMediaPlayer.Error, str]] = []
        player.errorOccurred.connect(
            lambda error, message: errors.append((error, str(message)))
        )
        try:
            player.setSource(QUrl.fromLocalFile(str(invalid.resolve())))
            self._wait(
                lambda: player.mediaStatus()
                == QMediaPlayer.MediaStatus.InvalidMedia
                or player.error() != QMediaPlayer.Error.NoError
            )
            self.assertNotEqual(
                player.error(),
                QMediaPlayer.Error.NoError,
            )
            self.assertTrue(player.errorString())
            self.assertTrue(errors)
        finally:
            player.stop()
            player.setSource(QUrl())
            player.deleteLater()
            audio_output.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
