import os,unittest
from newsdataapi import NewsDataApiClient 

class test_newsdataapi(unittest.TestCase):
    def setUp(self):
        # your private API key.
        key = os.environ.get("PYTEST_TOKEN")
        self.api = NewsDataApiClient(apikey=key)

    def test_news_api(self):
        response = self.api.news_api()

        self.assertEqual(response['status'], "success")

    def test_archive_api(self):
        response = self.api.archive_api(q='test')

        self.assertEqual(response['status'], "success")

    def test_sources_api(self):
        response = self.api.sources_api()

        self.assertEqual(response['status'], "success")

    def test_crypto_api(self):
        response = self.api.crypto_api()

        self.assertEqual(response['status'], "success")
