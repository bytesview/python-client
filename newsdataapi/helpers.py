import time,os,csv

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
                    data = ','.join(f'{i}:{j}' for i, j in v.items())
                    result[k] = f'"{data}"'
                elif isinstance(v, list):
                    data = ','.join(map(str, v))
                    result[k] = f'"{data}"'
                else:
                    if v is not None:
                        result[k] = f'"{v}"'

        self.generate_csv_file(results, full_path)
        
        return full_path
   