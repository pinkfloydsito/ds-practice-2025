from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class FraudRequest(_message.Message):
    __slots__ = ("order_id", "user_id", "amount", "payment_method", "location")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    LOCATION_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    user_id: str
    amount: float
    payment_method: str
    location: str
    def __init__(self, order_id: _Optional[str] = ..., user_id: _Optional[str] = ..., amount: _Optional[float] = ..., payment_method: _Optional[str] = ..., location: _Optional[str] = ...) -> None: ...

class FraudResponse(_message.Message):
    __slots__ = ("is_fraudulent", "reason")
    IS_FRAUDULENT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    is_fraudulent: bool
    reason: str
    def __init__(self, is_fraudulent: bool = ..., reason: _Optional[str] = ...) -> None: ...
