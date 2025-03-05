from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class FraudRequest(_message.Message):
    __slots__ = ("user_name", "user_email")
    USER_NAME_FIELD_NUMBER: _ClassVar[int]
    USER_EMAIL_FIELD_NUMBER: _ClassVar[int]
    user_name: str
    user_email: str
    def __init__(self, user_name: _Optional[str] = ..., user_email: _Optional[str] = ...) -> None: ...

class FraudResponse(_message.Message):
    __slots__ = ("is_fraudulent", "reason")
    IS_FRAUDULENT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    is_fraudulent: bool
    reason: str
    def __init__(self, is_fraudulent: bool = ..., reason: _Optional[str] = ...) -> None: ...
