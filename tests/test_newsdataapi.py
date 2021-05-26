import os
from newsdataapi import NewsDataApiClient 
import unittest

class test_newsdataapi(unittest.TestCase):
    def setUp(self):
        # your private API key.
        #key = os.environ.get("PYTEST_TOKEN")
        key = "pub_1893fc8648dd1d490ec89f920eec2d573"
        self.api = NewsDataApiClient(apikey=key)

    def test_news_api(self):
        response = self.api.news_api()

        self.assertEqual(response['status'], "success")

    def test_archive_api(self):
        response = self.api.archive_api()

        self.assertEqual(response['status'], "success")

    def test_sources_api(self):
        response = self.api.sources_api()

        self.assertEqual(response['status'], "success")