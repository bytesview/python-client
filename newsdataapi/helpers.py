import time,os,csv

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


class FileHandler:

    def __init__(self,folder_path:str=None) -> None:
        self.folder_path = folder_path

    def generate_csv_file(self,collected_data:list,full_filepath:str):
        with open(full_filepath,'w',newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file,fieldnames=list(collected_data[0].keys()))
            writer.writeheader()
            writer.writerows(collected_data)


    def save_to_csv(self, response: dict, folder_path: str=None, filename: str=None)->str:
        folder_path = folder_path or self.folder_path
        filename = filename or str(time.time_ns())

        if not folder_path or not os.path.exists(folder_path):
            raise FileNotFoundError(f'Provided folder path not found: {folder_path}')

        filename = f'{filename}.csv' if not filename.endswith('.csv') else filename
        full_path = os.path.join(folder_path, filename)

        if os.path.exists(full_path):
            raise FileExistsError(f'Provided file already exists: {filename} in folder: {folder_path}')

        results = response.get('results', [])

        for result in results:
            for k, v in result.items():
                if isinstance(v, dict):
                    result[k] = ','.join(f'{i}:{j}' for i, j in v.items())
                elif isinstance(v, list):
                    result[k] = ','.join(map(str, v))

        self.generate_csv_file(results, full_path)
        
        return full_path
   