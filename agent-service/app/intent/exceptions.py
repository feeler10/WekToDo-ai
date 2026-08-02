class IntentRecognitionError(Exception):
    pass


class IntentProviderUnavailableError(IntentRecognitionError):
    pass


class InvalidIntentOutputError(IntentRecognitionError):
    pass


class UnsupportedIntentProviderError(IntentRecognitionError):
    pass
