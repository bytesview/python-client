import requests,time
from warnings import warn
from newsdataapi import constants
from typing import Optional,Union
from datetime import datetime,timezone
from newsdataapi.helpers import FileHandler
from requests.exceptions import RequestException
from newsdataapi.newsdataapi_exception import NewsdataException
from urllib.parse import urlencode, quote,urlparse,parse_qs,urljoin

class NewsDataApiClient(FileHandler):

    def __init__(
            self, apikey:str, session:bool= False, max_retries:int= constants.DEFAULT_MAX_RETRIES, retry_delay:int= constants.DEFAULT_RETRY_DELAY,
            proxies:Optional[dict]=None, request_timeout:int= constants.DEFAULT_REQUEST_TIMEOUT,max_result:int=10**10, debug:Optional[bool]=False,
            folder_path:str=None,include_headers:bool=False
        ):
        """Initializes newsdata client object for access Newsdata APIs."""
        self.apikey = apikey
        self.request_method:requests = requests if session == False else requests.Session()
        self.max_result = max_result
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.proxies = proxies
        self.request_timeout = request_timeout
        self.is_debug = debug
        self.include_headers = include_headers
        self.set_base_url()
        super().__init__(folder_path=folder_path)
    
    def set_base_url(self,new_base_url:str=constants.BASE_URL)->None:
        self.latest_url = urljoin(new_base_url,constants.LATEST_ENDPOINT)
        self.archive_url = urljoin(new_base_url,constants.ARCHIVE_ENDPOINT)
        self.crypto_url = urljoin(new_base_url,constants.CRYPTO_ENDPOINT)
        self.sources_url = urljoin(new_base_url,constants.SOURCES_ENDPOINT)
        self.count_url = urljoin(new_base_url,constants.COUNT_ENDPOINT)

    def set_retries( self, max_retries:int, retry_delay:int)->None:
        """ API maximum retry and delay"""
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def set_request_timeout( self, request_timeout:int)->None:
        """ API maximum timeout for the request """
        self.request_timeout = request_timeout

    def get_current_dt(self)->str:
        return datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    def api_proxies( self, proxies:dict)->None:
        """ Configure Proxie dictionary """
        self.proxies = proxies
    
    def __validate_parms(self,user_param:dict)->dict:
        bool_params = {'full_content','image','video','removeduplicate'}
        int_params = {'size'}
        string_params = {
            'q','qInTitle','country','category','language','domain','domainurl','excludedomain','timezone','page',
            'from_date','to_date','apikey','qInMeta','prioritydomain','timeframe','tag','sentiment','region','coin',
            'excludefield'
        }
        
        def validate_url(url:str)-> str:
            valid_fn_parms = {k.lower() for k in user_param.keys()}
            parsed_url = urlparse(url)
            if parsed_url.netloc:
                q_string = parse_qs(parsed_url.query)
            else:
                q_string = parse_qs(url)
            
            valid_q_string = {}
            for k,v in q_string.items():
                k = k.strip().strip('%').strip('?').lower()
                if k in valid_fn_parms:
                    valid_q_string[k] = v[0]
                else:
                    raise TypeError(f'Provided parameter is invalid: {k}')
            
            if not valid_q_string.get('apikey'):
                valid_q_string['apikey'] = self.apikey

            return valid_q_string
        
        if user_param.get('raw_query'):
            value = user_param['raw_query']
            if not isinstance(value,str):
                raise TypeError('raw_query should be of type string.')
            return validate_url(url=value)

        valid_parms = {}
        for param,value in user_param.items():
            if not value:continue
            if param in string_params:
                if isinstance(value,list):
                    value = ','.join(value)
                if not isinstance(value,str):
                    raise TypeError(f'{param} should be of type string.')
            elif param in bool_params:
                if not isinstance(value,bool):
                    raise TypeError(f'{param} should be of type bool.')
                value = 1 if value == True else 0
            elif param in int_params:
                if not isinstance(value,int):
                    raise TypeError(f'{param} should be of type int.')
            
            valid_parms[param] = value

        return valid_parms
    
    def __get_feeds(self,url:str,retry_count:int=None)-> dict:
        try:
            if retry_count is None:
                retry_count = self.max_retries

            if retry_count <= 0:
                raise  NewsdataException('Maximum retry limit reached. For more information use debug parameter while initializing NewsDataApiClient.')
            
            response = self.request_method.get(url=url,proxies=self.proxies,timeout=self.request_timeout)
            headers = dict(response.headers)
            
            if self.is_debug == True:
                print(f'Debug | {self.get_current_dt()} | x_rate_limit_remaining: {headers.get("x_rate_limit_remaining")} | x_api_limit_remaining: {headers.get("x_api_limit_remaining")}')
            
            feeds_data:dict = response.json()
            if self.include_headers == True:
                feeds_data.update({'response_headers':headers})

            if response.status_code != 200:
                
                if response.status_code == 500:
                    if self.is_debug == True:
                        print(f"Debug | {self.get_current_dt()} | Encountered 'ServerError' going to sleep for: {self.retry_delay} seconds.")
                    time.sleep(self.retry_delay)
                    return self.__get_feeds(url=url,retry_count=retry_count-1)
                
                elif feeds_data.get('results',{}).get('code') == 'TooManyRequests':
                    if self.is_debug == True:
                        print(f"Debug | {self.get_current_dt()} | Encountered 'TooManyRequests' going to sleep for: {constants.DEFAULT_RETRY_DELAY_TooManyRequests} seconds.")
                    time.sleep(constants.DEFAULT_RETRY_DELAY_TooManyRequests)
                    return self.__get_feeds(url=url,retry_count=retry_count-1)
                
                elif feeds_data.get('results',{}).get('code') == 'RateLimitExceeded':
                    if self.is_debug == True:
                        print(f"Debug | {self.get_current_dt()} | Encountered 'RateLimitExceeded' going to sleep for: {constants.DEFAULT_RETRY_DELAY_RateLimitExceeded} seconds.")
                    time.sleep(constants.DEFAULT_RETRY_DELAY_RateLimitExceeded)
                    return self.__get_feeds(url=url,retry_count=retry_count-1)
                
                else:
                    raise NewsdataException(response.json())
            
            else:
                return feeds_data

        except RequestException:
            
            if self.is_debug == True:
                print(f"Debug | {self.get_current_dt()} | Encountered 'ConnectionError' going to sleep for: {self.retry_delay} seconds.")
            time.sleep(self.retry_delay)
            
            if isinstance(self.request_method,requests.Session):
                self.request_method = requests.Session()
            
            return self.__get_feeds(url=url,retry_count=retry_count-1)

    def __get_feeds_all(self,url:str,max_result:int)-> dict:
        
        if max_result is None:
            max_result = self.max_result

        if not isinstance(max_result,int):
            raise TypeError('max_result should be of type int.')
                
        if not isinstance(self.request_method,requests.Session):
            self.request_method = requests.Session()

        feeds_count = 0
        data = {'totalResults':None,'results':[],'nextPage':True}
        while data.get("nextPage"):
            try:
                response = self.__get_feeds(url=f'{url}&page={data.get("nextPage")}' if data.get('results') else url)
            except NewsdataException as e:
                if data['totalResults'] is None:
                    raise e
                return data
            data['totalResults'] = response.get('totalResults')
            results = response.get('results')
            data['results'].extend(results)
            data['nextPage'] = response.get('nextPage')
            if self.include_headers:
                data['response_headers'] = response.get('response_headers')
            feeds_count+=len(results)
            if self.is_debug == True:
                print(f"Debug | {self.get_current_dt()} | total results: {data['totalResults']} | extracted: {feeds_count}")
            if feeds_count >= max_result:
                return data
            time.sleep(0.5)
        return data

    def news_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None, country:Optional[Union[str, list]]=None, category:Optional[Union[str, list]]=None,
            language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None, timeframe:Optional[Union[int,str]]=None, size:Optional[int]=None,
            domainurl:Optional[Union[str, list]]=None, excludedomain:Optional[Union[str, list]]=None, timezone:Optional[str]=None, full_content:Optional[bool]=None,
            image:Optional[bool]=None, video:Optional[bool]=None, prioritydomain:Optional[str]=None, page:Optional[str]=None, scroll:Optional[bool]=False,
            max_result:Optional[int]=None, qInMeta:Optional[str]=None, tag:Optional[Union[str,list]]=None, sentiment:Optional[str]=None,
            region:Optional[Union[str,list]]=None,excludefield:Optional[Union[str,list]]=None,removeduplicate:Optional[bool]=None,raw_query:Optional[str]=None
        )->dict:
        """ 
        Sending GET request to the news api.
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        warn('This method is deprecated and will be removed in upcoming updates, Instead use latest_api()', DeprecationWarning, stacklevel=2)
        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'timeframe':str(timeframe) if timeframe else timeframe,
            'size':size,'domainurl':domainurl,'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,
            'page':page,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment, 'region':region,'excludefield':excludefield,'removeduplicate':removeduplicate,'raw_query':raw_query
        }
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{self.latest_url}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{self.latest_url}?{URL_parameters_encoded}')
    
    def latest_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None, country:Optional[Union[str, list]]=None, category:Optional[Union[str, list]]=None,
            language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None, timeframe:Optional[Union[int,str]]=None, size:Optional[int]=None,
            domainurl:Optional[Union[str, list]]=None, excludedomain:Optional[Union[str, list]]=None, timezone:Optional[str]=None, full_content:Optional[bool]=None,
            image:Optional[bool]=None, video:Optional[bool]=None, prioritydomain:Optional[str]=None, page:Optional[str]=None, scroll:Optional[bool]=False,
            max_result:Optional[int]=None, qInMeta:Optional[str]=None, tag:Optional[Union[str,list]]=None, sentiment:Optional[str]=None,
            region:Optional[Union[str,list]]=None,excludefield:Optional[Union[str,list]]=None,removeduplicate:Optional[bool]=None,raw_query:Optional[str]=None
        )->dict:
        """ 
        Sending GET request to the latest api.
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'timeframe':str(timeframe) if timeframe else timeframe,
            'size':size,'domainurl':domainurl,'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,
            'page':page,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment, 'region':region,'excludefield':excludefield,'removeduplicate':removeduplicate,'raw_query':raw_query
        }
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{self.latest_url}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{self.latest_url}?{URL_parameters_encoded}')

    def archive_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None, country:Optional[Union[str, list]]=None, category:Optional[Union[str, list]]=None,
            language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None, size:Optional[int]=None,domainurl:Optional[Union[str, list]]=None,
            excludedomain:Optional[Union[str, list]]=None, timezone:Optional[str]=None, full_content:Optional[bool]=None,image:Optional[bool]=None,
            video:Optional[bool]=None,prioritydomain:Optional[str]=None, page:Optional[str]=None, scroll:Optional[bool]=False, max_result:Optional[int]=None,
            from_date:Optional[str]=None, to_date:Optional[str]=None, qInMeta:Optional[str]=None, excludefield:Optional[Union[str,list]]=None,raw_query:Optional[str]=None
    ) -> dict:
        """
        Sending GET request to the archive api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {
            'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'size':size,'domainurl':domainurl,'excludedomain':excludedomain,
            'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,'page':page,'from_date':from_date,'to_date':to_date,
            'apikey':self.apikey,'qInMeta':qInMeta,'excludefield':excludefield,'raw_query':raw_query
        }
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{self.archive_url}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{self.archive_url}?{URL_parameters_encoded}') 
    
    def sources_api( self, country:Optional[str]= None, category:Optional[str]= None, language:Optional[str]= None, prioritydomain:Optional[str]= None,raw_query:Optional[str]=None):
        """ 
        Sending GET request to the sources api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {"apikey":self.apikey, "country":country, "category":category, "language":language, "prioritydomain":prioritydomain,'raw_query':raw_query}
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        return self.__get_feeds(url=f'{self.sources_url}?{URL_parameters_encoded}')

    def crypto_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None,language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None,
            timeframe:Optional[Union[int,str]]=None, size:Optional[int]=None,domainurl:Optional[Union[str, list]]=None, excludedomain:Optional[Union[str, list]]=None,
            timezone:Optional[str]=None, full_content:Optional[bool]=None,image:Optional[bool]=None, video:Optional[bool]=None, prioritydomain:Optional[str]=None, 
            page:Optional[str]=None, scroll:Optional[bool]=False,max_result:Optional[int]=None, qInMeta:Optional[str]=None,tag:Optional[Union[str,list]]=None, 
            sentiment:Optional[str]=None,coin:Optional[Union[str, list]]=None,excludefield:Optional[Union[str,list]]=None,from_date:Optional[str]=None, 
            to_date:Optional[str]=None,removeduplicate:Optional[bool]=None,raw_query:Optional[str]=None,
        )->dict:
        """ 
        Sending GET request to the crypto api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """

        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'language':language,'domain':domain,'size':size,'domainurl':domainurl,
            'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,'page':page,
            'timeframe':str(timeframe) if timeframe else timeframe,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment,'coin':coin,'excludefield':excludefield,
            'from_date':from_date,'to_date':to_date,'removeduplicate':removeduplicate,'raw_query':raw_query
        }
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{self.crypto_url}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{self.crypto_url}?{URL_parameters_encoded}') 

    def count_api(
        self, q:Optional[str]=None, qInTitle:Optional[str]=None, qInMeta:Optional[str]=None, country:Optional[Union[str, list]]=None,
        category:Optional[Union[str, list]]=None,language:Optional[Union[str, list]]=None, from_date:Optional[str]=None,
        to_date:Optional[str]=None,raw_query:Optional[str]=None
    ) -> dict:
        """
        Sending GET request to the count api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {
            'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'from_date':from_date,'to_date':to_date,
            'apikey':self.apikey,'qInMeta':qInMeta,'raw_query':raw_query
        }
        URL_parameters = self.__validate_parms(user_param=params)
        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        return self.__get_feeds(url=f'{self.count_url}?{URL_parameters_encoded}') 

    def __del__(self):
        if isinstance(self.request_method,requests.Session):
            self.request_method.close()
