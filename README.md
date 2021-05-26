![Alt text](https://raw.githubusercontent.com/newsdataapi/python-client/main/newsdata-logo.png)

# <p align="center">Newsdataapi Python Client
newsdataapi allows you to create a library for accessing http services easily, in a centralized way. An API defined by newsdataapi will return a JSON object when called.

<br />

# Installation

## Supported Python Versions
Python >= 3.5 fully supported and tested.

## Install Package
```
pip install newsdataapi
```

## Quick Start

Newsdataapi docs can be seen [here](https://newsdata.io/docs).

<br />

### Latest News API

`GET /1/news`

```
from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key
api = NewsDataApiClient(apikey="API key")

# You can pass Empty or Request Parameters. ex(country = "us")
response = api.news_api()

```
`API key` : Your private Newsdata API key. 

`country` : You can pass a comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: `us` `gb` `in` `jp` `ae` `sa` `au` `ca` `sg` 

`category` : A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: `top`, `business`, `science`, `technology`, `sports`, `health`, `entertainment`

`language` : A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: `en`, `ar`, `jp`, `in`, `es`, `fr`

`domain` : A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.
 
`q` : Keywords or phrases to search for in the news title and content. The value must be URL-encoded. Advance search options: Search Social q=social, Search "Social Pizza" q=social pizza, Search Social but not with pizza. social -pizza q=social -pizza, Search Social but not with pizza and wildfire. social -pizza -wildfire q=social -pizza -wildfire, Search multiple keyword with AND operator. social AND pizza q=social AND pizza 

`qInTitle` : Keywords or phrases to search for in the news title only.

`page` : Use this to page through the results if the total results found is greater than the page size.



<br />

### News Archive API

`GET /1/archive`

```
from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key
api = NewsDataApiClient(apikey="API key")

# You can pass Empty or Request Parameters. ex(country = "us")
response = api.archive_api()

```
`API key` : Your private Newsdata API key. 

`country` : You can pass a comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: `us` `gb` `in` `jp` `ae` `sa` `au` `ca` `sg` 

`category` : A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: `top`, `business`, `science`, `technology`, `sports`, `health`, `entertainment`

`language` : A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: `en`, `ar`, `jp`, `in`, `es`, `fr`

`domain` : A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.

`from_data` : A date and optional time for the oldest article allowed. This should be in ISO 8601 format (e.g. `2021-04-18` or `2021-04-18T04:04:34`)

`to_date` : A date and optional time for the newest article allowed. This should be in ISO 8601 format (e.g. `2021-04-18` or `2021-04-18T04:04:34`)
 
`q` : Keywords or phrases to search for in the news title and content. The value must be URL-encoded. Advance search options: Search Social q=social, Search "Social Pizza" q=social pizza, Search Social but not with pizza. social -pizza q=social -pizza, Search Social but not with pizza and wildfire. social -pizza -wildfire q=social -pizza -wildfire, Search multiple keyword with AND operator. social AND pizza q=social AND pizza 

`qInTitle` : Keywords or phrases to search for in the news title only.

`page` : Use this to page through the results if the total results found is greater than the page size.



<br />


### News Sources API

`GET /1/sources`

```
from newsdataapi import NewsDataApiClient

# API key authorization, Initialize the client with your API key
api = NewsDataApiClient(apikey="API key")

# You can pass Empty or Request Parameters. ex(country = "us")
response = api.sources_api()

```
`API key` : Your private Newsdata API key. 

`country` : You can pass a comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: `us` `gb` `in` `jp` `ae` `sa` `au` `ca` `sg` 

`category` : A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: `top`, `business`, `science`, `technology`, `sports`, `health`, `entertainment`

`language` : A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: `en`, `ar`, `jp`, `in`, `es`, `fr`

`domain` : A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.

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