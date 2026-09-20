import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from learn_export import Client, APIError, normalize, export, upcoming_items


class FakeClient(Client):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        return next(self.responses)


class ExportTests(unittest.TestCase):
    def test_bookmarks_and_next_links(self):
        c = FakeClient([{'Items': [1], 'PagingInfo': {'HasMoreItems': True, 'Bookmark': 'a&b'}}, {'Items': [2]}])
        self.assertEqual(c.listing('/test?x=1'), [1, 2])
        self.assertEqual(c.paths[1], '/test?x=1&bookmark=a%26b')
        c = FakeClient([{'Objects': [1], 'Next': '/next'}, {'Objects': [2], 'Next': None}])
        self.assertEqual(c.listing('/first'), [1, 2])

    def test_failed_response_is_not_an_empty_list(self):
        with self.assertRaises(APIError):
            FakeClient([{'error': 403}]).listing('/test')

    def test_undated_and_all_day_and_safe_export(self):
        course = {'Id': 1, 'Name': 'Test course'}
        assignment = normalize('Assignment', course, {'Id': 2, 'Name': '=formula final', 'CustomInstructions': {'Html': '<b>Instructions</b>'}})
        self.assertIsNone(assignment['due'])
        self.assertEqual(assignment['description'], 'Instructions')
        assignment['due'] = '2026-09-18T12:00:00Z'
        event = normalize('Event', course, {'CalendarEventId': 3, 'Title': '<script>alert(1)</script> due', 'StartDay': '2026-09-18T00:00:00', 'IsAllDayEvent': True, 'CalendarEventViewUrl': 'javascript:alert(1)'})
        self.assertTrue(event['url'].startswith('https://'))
        report = {'generated_at': '2026-09-17T12:00:00Z', 'items': [assignment, event], 'courses': [course], 'warnings': ['Failed source'], 'coverage': []}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            export(report, Path(tmp), 'America/Toronto', datetime(2026, 9, 17, 12, tzinfo=timezone.utc))
            page = (Path(tmp) / 'learn.html').read_text(encoding='utf-8')
            self.assertIn('2026-09-18 (all day)', page)
            self.assertNotIn('<script>alert(1)</script>', page)
            self.assertIn('Failed source', page)
            self.assertIn("'=formula", (Path(tmp) / 'learn.csv').read_text(encoding='utf-8-sig'))

    def test_deadline_window_and_major_assessments(self):
        def item(title, **fields):
            return dict(title=title, kind='Assignment', course='Test', **fields)
        rows = [item('Today', due='2026-09-17T23:00:00Z'),
                item('Earlier today', due='2026-09-17T11:59:00Z'),
                item('Final already finished', due='2026-09-17T11:00:00Z'),
                item('Exactly now', due='2026-09-17T12:00:00Z'),
                item('Local time passed', due='2026-09-17T07:59:00'),
                item('Boundary', due='2026-10-17T23:00:00Z'),
                item('Later', due='2026-10-18T23:00:00Z'),
                item('Old final', due='2026-09-16T12:00:00Z'),
                item('Final exam', due='2026-12-01T12:00:00Z'),
                item('Final report'), item('Ordinary undated'),
                item('Practice exam'),
                dict(title='Assignment opens', kind='Event', course='Test', event_type=2, start='2026-09-18T12:00:00Z'),
                dict(title='Assignment due', kind='Event', course='Test', event_type=6, start='2026-09-18T12:00:00Z')]
        result = upcoming_items(rows, 'America/Toronto', datetime(2026, 9, 17, 12, tzinfo=timezone.utc))
        self.assertEqual({r['title'] for r in result}, {'Today', 'Boundary', 'Assignment due'})
        week = upcoming_items(rows, 'America/Toronto', datetime(2026, 9, 17, 12, tzinfo=timezone.utc), days=7)
        self.assertEqual({r['title'] for r in week}, {'Today', 'Assignment due'})


if __name__ == '__main__':
    unittest.main()
