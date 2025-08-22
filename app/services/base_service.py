class BaseService:
    """
    Base class for all services in the Prometheus application.
    """

    def start(self):
        """
        Start the services.
        This method should be overridden by subclasses to implement specific startup logic.
        """
        pass

    def close(self):
        """
        Close the services and release any resources.
        This method should be overridden by subclasses to implement specific cleanup logic.
        """
        pass
