from newsdataapi import NewsDataApiClient


# API key authorization, Initialize the client with your API key
api = NewsDataApiClient(apikey='API Key')


# News API
response = api.news_api()
print(response)


# Archive API
response = api.archive_api(q='test')
print(response)


# Sources API
response = api.sources_api()
print(response)

# Crypto API
response = api.crypto_api()
print(response)
