from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class TransactionInitRequest(_message.Message):
    __slots__ = ("order_id", "creditCardNumber", "expiryDate")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    CREDITCARDNUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRYDATE_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    creditCardNumber: str
    expiryDate: str
    def __init__(self, order_id: _Optional[str] = ..., creditCardNumber: _Optional[str] = ..., expiryDate: _Optional[str] = ...) -> None: ...

class TransactionInitResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: bool = ...) -> None: ...

class TransactionRequest(_message.Message):
    __slots__ = ("creditCardNumber", "expiryDate", "order_id")
    CREDITCARDNUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRYDATE_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    creditCardNumber: str
    expiryDate: str
    order_id: str
    def __init__(self, creditCardNumber: _Optional[str] = ..., expiryDate: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class TransactionResponse(_message.Message):
    __slots__ = ("isValid", "reason")
    ISVALID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    isValid: bool
    reason: str
    def __init__(self, isValid: bool = ..., reason: _Optional[str] = ...) -> None: ...
