import time

def get(request_method, URL, URL_parameters_encoded, proxies, request_timeout):
    if proxies is None:
        return request_method.get(URL + "?" + URL_parameters_encoded, timeout=request_timeout)
    else:
        return request_method.get(URL + "?" + URL_parameters_encoded, timeout=request_timeout, proxies = proxies)

def MaxRetries(response, max_retries, retry_delay, request_method, URL, URL_parameters_encoded, proxies, request_timeout):
    while (max_retries):
        time.sleep(retry_delay)
        response = get(request_method, URL, URL_parameters_encoded, proxies, request_timeout)
        if response.status_code!=500:
            break
        max_retries-=1
    return response