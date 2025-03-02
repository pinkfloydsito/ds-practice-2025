from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class TransactionRequest(_message.Message):
    __slots__ = ("creditCardNumber", "expiryDate")
    CREDITCARDNUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRYDATE_FIELD_NUMBER: _ClassVar[int]
    creditCardNumber: str
    expiryDate: str
    def __init__(self, creditCardNumber: _Optional[str] = ..., expiryDate: _Optional[str] = ...) -> None: ...

class TransactionResponse(_message.Message):
    __slots__ = ("isValid", "reason")
    ISVALID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    isValid: bool
    reason: str
    def __init__(self, isValid: bool = ..., reason: _Optional[str] = ...) -> None: ...
