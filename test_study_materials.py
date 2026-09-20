import unittest
from study_materials import collect_materials


class MaterialsTests(unittest.TestCase):
    def test_nested_modules_and_safe_links(self):
        class Client:
            def get(self, path):
                return {'Modules': [{'Title': 'Week 1', 'Topics': [
                    {'TopicId': 10, 'Title': 'Slides', 'Url': '/content/slides.pdf'}],
                    'Modules': [{'Title': 'Practice', 'Topics': [
                        {'TopicId': 11, 'Title': 'Worksheet', 'Url': 'javascript:alert(1)'}]}]}]}
        report = collect_materials(Client(), [{'Id': 1, 'Name': 'Math'}], '1.97')
        self.assertEqual(len(report['items']), 2)
        self.assertEqual(report['items'][1]['module'], 'Week 1 / Practice')
        self.assertTrue(report['items'][1]['url'].startswith('https://'))
        self.assertEqual(report['warnings'], [])

    def test_failed_course_is_reported(self):
        class Client:
            def get(self, path):
                raise RuntimeError('HTTP 403')
        report = collect_materials(Client(), [{'Id': 1, 'Name': 'Math'}], '1.97')
        self.assertEqual(report['items'], [])
        self.assertIn('HTTP 403', report['warnings'][0])
