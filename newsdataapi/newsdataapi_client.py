import requests
from newsdataapi import constants
from newsdataapi.utils import is_valid_string, is_valid_integer
from newsdataapi.newsdataapi_exception import NewsdataException
from newsdataapi.helpers import get, MaxRetries
from urllib.parse import urlencode, quote

class NewsDataApiClient(object):

    def __init__(self, apikey=None, session=None):

        """ Initializes newsdata client object for access Newsdata APIs """

        """
        :param apikey: your API key.
        :type apikey:  string
        :param session: Default value for this argument is None but if you’re making several requests to the same host,
                        the underlying TCP connection will be reused, which can result in a significant performance increase.
                        Please make sure call session.close() after execute all calls to free up resource.
        :type session: requests.Session
        """

        self.apikey = apikey
        # Check if session argument is None
        if session is None:
            self.request_method = requests
        else:
            self.request_method = session

        # Default value for maximum retries and retry delay is zero
        self.max_retries = 0
        self.retry_delay = 0

        # Default proxies value is none
        self.proxies = None

        # set request timeout
        self.request_timeout = constants.DEFAULT_REQUEST_TIMEOUT

    def set_retries( self, max_retries=0, retry_delay = 0):
        """ API maximum retry and delay when getting 500 error """

        """
        :param max_retries: Your maximum retries when server responding with 500 internal error, Default value for this augument is zero.
        :type max_retries:  integer
        :param retry_delay: Delay(in seconds) between retries when server responding with 500 error, Default value for this augument
                            is zero seconds.
        :type retry_delay:  integer
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def set_request_timeout( self, request_timeout = constants.DEFAULT_REQUEST_TIMEOUT):
        """ API maximum timeout for the request """

        """
        :param request_timeout: How many seconds to wait for the client to make a connection and/or send a response.
        :type request_timeout:  integer
        """
        self.request_timeout = request_timeout

    def api_proxies( self, proxies):
        """ Configure Proxie dictionary """

        """
        :param proxies: A dictionary of the protocol to the proxy url ( ex.{ "https" : "https://1.1.1.1:80"}).
        :type proxies:  dictionary
        """
        self.proxies = proxies


    def news_api( self, country=None, category=None, language=None, domain=None, q=None, qInTitle=None, page=None):
        """ Sending GET request to the news api"""

        """
        :param country: A comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: us, gb, in, jp, ae, sa, au, ca, sg
        :type data: string
        :param category: A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: top, business, science, technology, sports, health, entertainment
        :type category: string
        :param language: A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: en, ar, jp, in, es, fr
        :type language: string
        :param domain: A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.
        :type domain: string
        :param q: Keywords or phrases to search for in the news title and content. The value must be URL-encoded
                Advance search options:
                Search Social.
                    q=social
                Search "Social Pizza".
                    q=social pizza
                Search Social but not with pizza. social -pizza
                    q=social -pizza
                Search Social but not with pizza and wildfire. social -pizza -wildfire
                    q=social -pizza -wildfire
                Search multiple keyword with AND operator. social AND pizza
                    q=social AND pizza
        :type q: string
        :param qInTitle: Keywords or phrases to search for in the news title only.
        :type qInTitle: string
        :param page: Use this to page through the results if the total results found is greater than the page size.
        :type page: integer
        :return: server response in JSON object
        """

        if self.apikey is None:
            raise ValueError("Please provide your private API Key")
        apikey = self.apikey

        URL_parameters = {}
        news_data_input = [apikey, country, category, language, domain, q, qInTitle, page]
        params_key = ["apikey", "country", "category", "language", "domain", "q", "qInTitle", "page"]
        params_type = ["string", "string", "string", "string", "string", "string", "string", "integer"]

        for index, i in enumerate(news_data_input):
            if i is not None:
                if ((is_valid_string(i))&(params_key[index]!="page")):
                    URL_parameters[params_key[index]] = i
                elif ((is_valid_integer(i))&(params_key[index]=="page")):
                    URL_parameters[params_key[index]] = i
                else:
                    raise TypeError(str(params_key[index]) + " should be of type " + params_type[index])

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)

        # Make a GET request to constants.NEWS_URL
        response = get(self.request_method, constants.NEWS_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        if response.status_code == 500:
            response = MaxRetries(response, self.max_retries, self.retry_delay, self.request_method, constants.NEWS_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        # Check the status code of the response if not equal to 200, then raise exception
        if response.status_code != 200:
            raise NewsdataException(response.json())

        # Return the response json
        return response.json()


    def archive_api( self, country=None, category=None, language=None, domain=None, from_date=None, to_date=None, q=None, qInTitle=None, page=None):
        """ Sending GET request to the archive api"""

        """
        :param country: A comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: us, gb, in, jp, ae, sa, au, ca, sg
        :type data: string
        :param category: A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: top, business, science, technology, sports, health, entertainment
        :type category: string
        :param language: A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: en, ar, jp, in, es, fr
        :type language: string
        :param domain: A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.
        :type domain: string
        :param from_date: A date and optional time for the oldest article allowed. This should be in ISO 8601 format (e.g. 2021-04-18 or 2021-04-18T04:04:34).
        :type from_date: string
        :param to_date: A date and optional time for the newest article allowed. This should be in ISO 8601 format (e.g. 2021-04-18 or 2021-04-18T04:04:34)
        :type to_date: string
        :param q: Keywords or phrases to search for in the news title and content. The value must be URL-encoded
                Advance search options:
                Search Social.
                    q=social
                Search "Social Pizza".
                    q=social pizza
                Search Social but not with pizza. social -pizza
                    q=social -pizza
                Search Social but not with pizza and wildfire. social -pizza -wildfire
                    q=social -pizza -wildfire
                Search multiple keyword with AND operator. social AND pizza
                    q=social AND pizza
        :type q: string
        :param qInTitle: Keywords or phrases to search for in the news title only.
        :type qInTitle: string
        :param page: Use this to page through the results if the total results found is greater than the page size.
        :type page: integer
        :return: server response in JSON object
        """

        if self.apikey is None:
            raise ValueError("Please provide your private API Key")
        apikey = self.apikey

        URL_parameters = {}
        news_data_input = [apikey, country, category, language, domain, from_date, to_date, q, qInTitle, page]
        params_key = ["apikey", "country", "category", "language", "domain", "from_date", "to_date", "q", "qInTitle", "page"]
        params_type = ["string", "string", "string", "string", "string", "string", "string", "string", "string", "integer"]

        for index, i in enumerate(news_data_input):
            if i is not None:
                if ((is_valid_string(i))&(params_key[index]!="page")):
                    URL_parameters[params_key[index]] = i
                elif ((is_valid_integer(i))&(params_key[index]=="page")):
                    URL_parameters[params_key[index]] = i
                else:
                    raise TypeError(str(params_key[index]) + " should be of type " + params_type[index])

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)

        # Make a GET request to constants.ARCHIVE_URL
        response = get(self.request_method, constants.ARCHIVE_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        if response.status_code == 500:
            response = MaxRetries(response, self.max_retries, self.retry_delay, self.request_method, constants.ARCHIVE_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        # Check the status code of the response if not equal to 200, then raise exception
        if response.status_code != 200:
            raise NewsdataException(response.json())

        # Return the response json
        return response.json()



    def sources_api( self, country=None, category=None, language=None):
        """ Sending GET request to the sources api"""

        """
        :param country: Find sources that display news in a specific country. Possible Options: us, gb, in, jp, ae, sa, au, ca, sg
        :type data: string
        :param category: Find sources that display news of this category. Possible Options: top, business, science, technology, sports, health, entertainment
        :type category: string
        :param language: Find sources that display news in a specific language. Possible Options: en, ar, jp, in, es, fr
        :type language: string
        :return: server response in JSON object
        """

        if self.apikey is None:
            raise ValueError("Please provide your private API Key")
        apikey = self.apikey

        URL_parameters = {}
        news_data_input = [apikey, country, category, language]
        params_key = ["apikey", "country", "category", "language"]

        for index, i in enumerate(news_data_input):
            if i is not None:
                if is_valid_string(i):
                    URL_parameters[params_key[index]] = i
                else:
                    raise TypeError(str(params_key[index]) + " should be of type string")

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)

        # Make a GET request to constants.SOURCES_URL
        response = get(self.request_method, constants.SOURCES_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        if response.status_code == 500:
            response = MaxRetries(response, self.max_retries, self.retry_delay, self.request_method, constants.SOURCES_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        # Check the status code of the response if not equal to 200, then raise exception
        if response.status_code != 200:
            raise NewsdataException(response.json())

        # Return the response json
        return response.json()

    def crypto_api( self, country=None, category=None, language=None, domain=None, q=None, qInTitle=None, page=None):
        """ Sending GET request to the crypto api"""

        """
        :param country: A comma seperated string of 2-letter ISO 3166-1 countries (maximum 5) to restrict the search to. Possible Options: us, gb, in, jp, ae, sa, au, ca, sg
        :type data: string
        :param category: A comma seperated string of categories (maximum 5) to restrict the search to. Possible Options: top, business, science, technology, sports, health, entertainment
        :type category: string
        :param language: A comma seperated string of languages (maximum 5) to restrict the search to. Possible Options: en, ar, jp, in, es, fr
        :type language: string
        :param domain: A comma seperated string of domains (maximum 5) to restrict the search to. Use the /domains endpoint to find top sources id.
        :type domain: string
        :param q: Keywords or phrases to search for in the news title and content. The value must be URL-encoded
                Advance search options:
                Search Bitcoin.
                    q=bitcoin
                Search "Bitcoin Ethereum".
                    q=bitcoin ethereum
                Search Bitcoin but not with Ethereum.
                    q=bitcoin -ethereum
                Search Bitcoin but not with Ethereum and Dogecoin. bitcoin -ethereum -dogecoin
                    q=bitcoin -ethereum -dogecoin
                Search multiple keyword with AND operator. bitcoin AND ethereum
                    q=bitcoin AND ethereum
        :type q: string
        :param qInTitle: Keywords or phrases to search for in the news title only.
        :type qInTitle: string
        :param page: Use this to page through the results if the total results found is greater than the page size.
        :type page: integer
        :return: server response in JSON object
        """

        if self.apikey is None:
            raise ValueError("Please provide your private API Key")
        apikey = self.apikey

        URL_parameters = {}
        news_data_input = [apikey, country, category, language, domain, q, qInTitle, page]
        params_key = ["apikey", "country", "category", "language", "domain", "q", "qInTitle", "page"]
        params_type = ["string", "string", "string", "string", "string", "string", "string", "integer"]

        for index, i in enumerate(news_data_input):
            if i is not None:
                if ((is_valid_string(i))&(params_key[index]!="page")):
                    URL_parameters[params_key[index]] = i
                elif ((is_valid_integer(i))&(params_key[index]=="page")):
                    URL_parameters[params_key[index]] = i
                else:
                    raise TypeError(str(params_key[index]) + " should be of type " + params_type[index])

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)

        # Make a GET request to constants.CRYPTO_URL
        response = get(self.request_method, constants.CRYPTO_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        if response.status_code == 500:
            response = MaxRetries(response, self.max_retries, self.retry_delay, self.request_method, constants.CRYPTO_URL, URL_parameters_encoded, self.proxies, self.request_timeout)

        # Check the status code of the response if not equal to 200, then raise exception
        if response.status_code != 200:
            raise NewsdataException(response.json())

        # Return the response json
        return response.json()
