
class NewsdataException(Exception):
    """Base class for all other exceptions"""

    def __init__(self, Error):
        self.Error = Error
