
![Alt text](https://raw.githubusercontent.com/newsdataapi/python-client/main/newsdata-logo.png)

# <p align="center">NewsData.io Python Client
newsdataapi allows you to create a library for accessing http services easily, in a centralized way. An API defined by newsdataapi will return a JSON object when called.

[![Build Status](https://img.shields.io/github/workflow/status/newsdataapi/python-client/Upload%20Python%20Package)](https://github.com/newsdataapi/python-client/actions/workflows/python-publish.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/newsdataapi/python-client/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/newsdataapi?color=084298)](https://pypi.org/project/newsdataapi)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/newsdataapi)](https://pypi.org/project/newsdataapi)
[![Python](https://img.shields.io/badge/python-3-blue)](https://pypi.org/project/newsdataapi)


<br />

# Installation

## Supported Python Versions
Python >= 3.5 fully supported and tested.

## Install Package
```
pip install newsdataapi
```

## Documentation

Newsdataapi docs can be seen [here](https://newsdata.io/documentation).

<br />

### Latest News API

`GET /1/news`

```
# To get latest news use our news_api method.

from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey='YOUR_API_KEY')
response = api.news_api(q='entertainment')
print(response)

# Latest news with page parameter

response = api.news_api(q='entertainment',page='nextPage_value')
print(response)

# To scroll through all latest news

response = api.news_api(q='entertainment',page='nextPage_value',scroll=True)
print(response)

```
<br />

### News Archive API

`GET /1/archive`

```
# To get archive news use our archive_api method.

from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey='YOUR_API_KEY')
response = api.archive_api(q='olympic',from_date='2021-01-01',to_date='2021-06-06')
print(response)

# Archive news with page parameter

response = api.archive_api(q='olympic',from_date='2021-01-01',to_date='2021-06-06',page='nextPage_value')
print(response)

# To scroll through all archive news

response = api.archive_api(q='olympic',from_date='2021-01-01',to_date='2021-06-06',page='nextPage_value',scroll=True)
print(response)

```
<br />


### News Sources API

`GET /1/sources`

```
# To get sources use our sources_api method.

from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey="YOUR_API_KEY")
response = api.sources_api()
print(response)

```
<br />

### Crypto News API

`GET /1/crypto`

```
# To get crypto news use our crypto_api method.

from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey='YOUR_API_KEY')
response = api.crypto_api(q='bitcoin')
print(response)

# Crypto with page parameter

response = api.crypto_api(q='bitcoin',page='nextPage_value')
print(response)

# To scroll through all crypto news

response = api.crypto_api(q='bitcoin',page='nextPage_value',scroll=True)
print(response)

```
<br />

### News API with Pagination

`GET /1/news`

```
from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey="YOUR_API_KEY")
response = api.news_api()

# You can go to next page by providing Page parameter

response = api.news_api(page = "nextPage value")

# You can paginate till last page by providing Page parameter in Loop

page=None
while True:
    response = api.news_api(page = page)
    page = response.get('nextPage',None)
    if not page:
        break

```

<br />

### News API with Scrolling

```
# Note: Scrolling through all result will counsume api as per your defined size. you can also define max_result to stop scrolling at desired result size.scroll is avaliable in news_archive,news_api and news_crypto, it will return all result when scrolling is compleated.

from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key

api = NewsDataApiClient(apikey="YOUR_API_KEY")

response = api.news_api(q='entertainment',page='nextPage_value',scroll=True,max_result=1000)
print(response)

```

<br />

## License

Provided under [MIT License](https://github.com/newsdataapi/python-client/blob/main/LICENSE) by Matt Lisivick.

```
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```