"""Shared test helpers."""


class FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")
