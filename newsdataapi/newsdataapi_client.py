import requests,time
from warnings import warn
from newsdataapi import constants
from typing import Optional,Union
from datetime import datetime,timezone
from urllib.parse import urlencode, quote
from newsdataapi.helpers import FileHandler
from requests.exceptions import RequestException
from newsdataapi.newsdataapi_exception import NewsdataException

class NewsDataApiClient(FileHandler):

    def __init__(
            self, apikey:str, session:bool= False, max_retries:int= constants.DEFAULT_MAX_RETRIES, retry_delay:int= constants.DEFAULT_RETRY_DELAY,
            proxies:Optional[dict]=None, request_timeout:int= constants.DEFAULT_REQUEST_TIMEOUT,max_result:int=10**10, debug:Optional[bool]=False,
            folder_path:str=None
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
        super().__init__(folder_path=folder_path)

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
    
    def __validate_parms(self,param:str,value:Union[list,int,str,bool])->dict:
        bool_params = {'full_content','image','video','cryptofeeds'}
        int_params = {'size'}
        string_params = {
            'q','qInTitle','country','category','language','domain','domainurl','excludedomain','timezone','page',
            'from_date','to_date','apikey','qInMeta','prioritydomain','timeframe','tag','sentiment','region','coin',
            'excludefield'
        }

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

        return {param:value}
    
    def __get_feeds(self,url:str,retry_count:int=None)-> dict:
        try:
            if retry_count is None:
                retry_count = self.max_retries

            if retry_count <= 0:
                raise  NewsdataException('Maximum retry limit reached. For more information use debug parameter while initializing NewsDataApiClient.')
            
            response = self.request_method.get(url=url,proxies=self.proxies,timeout=self.request_timeout)
            
            if self.is_debug == True:
                headers = response.headers
                print(f'Debug | {self.get_current_dt()} | x_rate_limit_remaining: {headers.get("x_rate_limit_remaining")} | x_api_limit_remaining: {headers.get("x_api_limit_remaining")}')
            
            feeds_data:dict = response.json()
            
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
            region:Optional[Union[str,list]]=None,excludefield:Optional[Union[str,list]]=None
        )->dict:
        """ 
        Sending GET request to the news api.
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        warn('This method is deprecated and will be removed in upcoming updates, Instead use latest_api()', DeprecationWarning, stacklevel=2)
        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'timeframe':str(timeframe) if timeframe else timeframe,
            'size':size,'domainurl':domainurl,'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,
            'page':page,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment, 'region':region,'excludefield':excludefield
        }
        URL_parameters = {}
        for key,value in params.items():
            if value is not None:
                URL_parameters.update(self.__validate_parms(param=key,value=value))

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{constants.LATEST_URL}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{constants.LATEST_URL}?{URL_parameters_encoded}')
    
    def latest_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None, country:Optional[Union[str, list]]=None, category:Optional[Union[str, list]]=None,
            language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None, timeframe:Optional[Union[int,str]]=None, size:Optional[int]=None,
            domainurl:Optional[Union[str, list]]=None, excludedomain:Optional[Union[str, list]]=None, timezone:Optional[str]=None, full_content:Optional[bool]=None,
            image:Optional[bool]=None, video:Optional[bool]=None, prioritydomain:Optional[str]=None, page:Optional[str]=None, scroll:Optional[bool]=False,
            max_result:Optional[int]=None, qInMeta:Optional[str]=None, tag:Optional[Union[str,list]]=None, sentiment:Optional[str]=None,
            region:Optional[Union[str,list]]=None,excludefield:Optional[Union[str,list]]=None
        )->dict:
        """ 
        Sending GET request to the latest api.
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'timeframe':str(timeframe) if timeframe else timeframe,
            'size':size,'domainurl':domainurl,'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,
            'page':page,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment, 'region':region,'excludefield':excludefield
        }
        URL_parameters = {}
        for key,value in params.items():
            if value is not None:
                URL_parameters.update(self.__validate_parms(param=key,value=value))

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{constants.LATEST_URL}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{constants.LATEST_URL}?{URL_parameters_encoded}')

    def archive_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None, country:Optional[Union[str, list]]=None, category:Optional[Union[str, list]]=None,
            language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None, size:Optional[int]=None,domainurl:Optional[Union[str, list]]=None,
            excludedomain:Optional[Union[str, list]]=None, timezone:Optional[str]=None, full_content:Optional[bool]=None,image:Optional[bool]=None,
            video:Optional[bool]=None,prioritydomain:Optional[str]=None, page:Optional[str]=None, scroll:Optional[bool]=False, max_result:Optional[int]=None,
            from_date:Optional[str]=None, to_date:Optional[str]=None, qInMeta:Optional[str]=None, cryptofeeds:Optional[bool]=None,excludefield:Optional[Union[str,list]]=None
    ) -> dict:
        """
        Sending GET request to the archive api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        params = {
            'q':q,'qInTitle':qInTitle,'country':country,'category':category,'language':language,'domain':domain,'size':size,'domainurl':domainurl,'excludedomain':excludedomain,
            'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,'page':page,'from_date':from_date,'to_date':to_date,
            'apikey':self.apikey,'qInMeta':qInMeta,'cryptofeeds':cryptofeeds,'excludefield':excludefield
        }
        URL_parameters = {}
        for key,value in params.items():
            if value is not None:
                URL_parameters.update(self.__validate_parms(param=key,value=value))

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{constants.ARCHIVE_URL}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{constants.ARCHIVE_URL}?{URL_parameters_encoded}') 
    
    def sources_api( self, country:Optional[str]= None, category:Optional[str]= None, language:Optional[str]= None, prioritydomain:Optional[str]= None):
        """ 
        Sending GET request to the sources api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """
        URL_parameters = {}
        params = {"apikey":self.apikey, "country":country, "category":category, "language":language, "prioritydomain":prioritydomain}
        URL_parameters = {}
        for key,value in params.items():
            if value is not None:
                URL_parameters.update(self.__validate_parms(param=key,value=value))

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        return self.__get_feeds(url=f'{constants.SOURCES_URL}?{URL_parameters_encoded}')

    def crypto_api(
            self, q:Optional[str]=None, qInTitle:Optional[str]=None,language:Optional[Union[str, list]]=None, domain:Optional[Union[str, list]]=None,
            timeframe:Optional[Union[int,str]]=None, size:Optional[int]=None,domainurl:Optional[Union[str, list]]=None, excludedomain:Optional[Union[str, list]]=None,
            timezone:Optional[str]=None, full_content:Optional[bool]=None,image:Optional[bool]=None, video:Optional[bool]=None, prioritydomain:Optional[str]=None, 
            page:Optional[str]=None, scroll:Optional[bool]=False,max_result:Optional[int]=None, qInMeta:Optional[str]=None,tag:Optional[Union[str,list]]=None, 
            sentiment:Optional[str]=None,coin:Optional[Union[str, list]]=None,excludefield:Optional[Union[str,list]]=None
        )->dict:
        """ 
        Sending GET request to the crypto api
        For more information about parameters and input, Please visit our documentation page: https://newsdata.io/documentation
        """

        params = {
            'apikey':self.apikey,'q':q,'qInTitle':qInTitle,'language':language,'domain':domain,'size':size,'domainurl':domainurl,
            'excludedomain':excludedomain,'timezone':timezone,'full_content':full_content,'image':image,'video':video,'prioritydomain':prioritydomain,'page':page,
            'timeframe':str(timeframe) if timeframe else timeframe,'qInMeta':qInMeta,'tag':tag, 'sentiment':sentiment,'coin':coin,'excludefield':excludefield
        }
        URL_parameters = {}
        for key,value in params.items():
            if value is not None:
                URL_parameters.update(self.__validate_parms(param=key,value=value))

        URL_parameters_encoded = urlencode(URL_parameters, quote_via=quote)
        if scroll == True:
            return self.__get_feeds_all(url=f'{constants.CRYPTO_URL}?{URL_parameters_encoded}',max_result=max_result)
        else:
            return self.__get_feeds(url=f'{constants.CRYPTO_URL}?{URL_parameters_encoded}') 

    def __del__(self):
        if isinstance(self.request_method,requests.Session):
            self.request_method.close()
