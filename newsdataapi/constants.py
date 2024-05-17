# All the Newsdata supported API URL
BASE_URL = 'https://newsdata.io/api/1/'

# Latest News URL
LATEST_URL = BASE_URL + 'latest'

# News Archive URL
ARCHIVE_URL = BASE_URL + 'archive'

# News Sources URL
SOURCES_URL = BASE_URL + 'sources'

# News Crypto URL
CRYPTO_URL = BASE_URL + 'crypto'

# Default request values
DEFAULT_REQUEST_TIMEOUT = 300
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY = 1800
DEFAULT_RETRY_DELAY_TooManyRequests = 10
DEFAULT_RETRY_DELAY_RateLimitExceeded = 900
