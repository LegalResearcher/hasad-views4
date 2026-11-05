import os
import tempfile
import unittest
from unittest.mock import patch

import main


class FakeSender:
    def __init__(self, status="ok"):
        self.status = status
        self.calls = []

    def __call__(self, link):
        self.calls.append(link)
        return self.status


class BatchProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = self.temp.name
        self.old_paths = (main.LINKS_PATH, main.PROCESSED_PATH)
        main.LINKS_PATH = os.path.join(self.state, "telegram_links.txt")
        main.PROCESSED_PATH = os.path.join(self.state, "processed_links.txt")
        for path in (main.LINKS_PATH, main.PROCESSED_PATH):
            open(path, "w", encoding="utf-8").close()

    def tearDown(self):
        main.LINKS_PATH, main.PROCESSED_PATH = self.old_paths
        self.temp.cleanup()

    def test_fetch_links_filters_boundary_and_sorts_newest_first(self):
        class Response:
            status_code = 200
            text = " ".join(
                f"/hasadalyoum/{number}"
                for number in (26732, 26734, 26733, 26720, 26735)
            )

        with patch.object(main.requests, "get", return_value=Response()):
            self.assertEqual(
                main.fetch_links(),
                [
                    "https://t.me/hasadalyoum/26735",
                    "https://t.me/hasadalyoum/26734",
                    "https://t.me/hasadalyoum/26733",
                ],
            )

    def test_first_run_processes_all_new_links_newest_first(self):
        batch = [
            "https://t.me/hasadalyoum/26734",
            "https://t.me/hasadalyoum/26736",
            "https://t.me/hasadalyoum/26733",
            "https://t.me/hasadalyoum/26732",
        ]
        with patch.object(main, "fetch_links", return_value=batch):
            selected = main.pull_once()
        expected = [
            "https://t.me/hasadalyoum/26736",
            "https://t.me/hasadalyoum/26734",
            "https://t.me/hasadalyoum/26733",
        ]
        sender = FakeSender()
        self.assertEqual(selected, expected)
        self.assertEqual(main.run_browser_send(sender, selected), 0)
        self.assertEqual(sender.calls, expected)
        self.assertEqual(main.read_lines(main.LINKS_PATH), [])

    def test_next_run_processes_only_new_links_after_previous_batch(self):
        first = [
            "https://t.me/hasadalyoum/26734",
            "https://t.me/hasadalyoum/26733",
        ]
        second = [
            "https://t.me/hasadalyoum/26737",
            "https://t.me/hasadalyoum/26736",
        ]
        with patch.object(main, "fetch_links", return_value=first):
            selected_first = main.pull_once()
        first_sender = FakeSender()
        main.run_browser_send(first_sender, selected_first)
        with patch.object(main, "fetch_links", return_value=first + second):
            selected_second = main.pull_once()
        expected = [
            "https://t.me/hasadalyoum/26737",
            "https://t.me/hasadalyoum/26736",
        ]
        self.assertEqual(selected_second, expected)
        sender = FakeSender()
        self.assertEqual(main.run_browser_send(sender, selected_second), 0)
        self.assertEqual(sender.calls, expected)

    def test_no_new_posts_does_not_replay_old_or_pending_links(self):
        stale = "https://t.me/hasadalyoum/26740"
        with open(main.LINKS_PATH, "w", encoding="utf-8") as file:
            file.write(stale + "\n")
        with open(main.PROCESSED_PATH, "w", encoding="utf-8") as file:
            file.write(stale + "\n")
        with patch.object(main, "fetch_links", return_value=[stale]):
            selected = main.pull_once()
        self.assertEqual(selected, [])
        self.assertEqual(main.read_lines(main.LINKS_PATH), [])

    def test_unprocessed_old_links_at_or_before_boundary_are_ignored(self):
        older = [
            "https://t.me/hasadalyoum/26732",
            "https://t.me/hasadalyoum/26731",
            "https://t.me/hasadalyoum/26600",
        ]
        with patch.object(main, "fetch_links", return_value=older):
            self.assertEqual(main.pull_once(), [])
        self.assertEqual(main.read_lines(main.LINKS_PATH), [])
        self.assertEqual(main.read_lines(main.PROCESSED_PATH), [])

    def test_fatal_stop_does_not_make_unattempted_links_replayable(self):
        batch = [
            "https://t.me/hasadalyoum/26743",
            "https://t.me/hasadalyoum/26742",
            "https://t.me/hasadalyoum/26741",
        ]
        with patch.object(main, "fetch_links", return_value=batch):
            selected = main.pull_once()
        stopped = FakeSender("fatal")
        self.assertEqual(main.run_browser_send(stopped, selected), 1)
        self.assertEqual(stopped.calls, [batch[0]])
        with patch.object(main, "fetch_links", return_value=batch):
            next_run = main.pull_once()
        self.assertEqual(next_run, [])
        self.assertEqual(main.read_lines(main.LINKS_PATH), [])


if __name__ == "__main__":
    unittest.main()
