from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class TransactionRequest(_message.Message):
    __slots__ = ("creditCardNumber", "expiryDate", "vectorClock", "orderId")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    CREDITCARDNUMBER_FIELD_NUMBER: _ClassVar[int]
    EXPIRYDATE_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    ORDERID_FIELD_NUMBER: _ClassVar[int]
    creditCardNumber: str
    expiryDate: str
    vectorClock: _containers.ScalarMap[str, int]
    orderId: str
    def __init__(self, creditCardNumber: _Optional[str] = ..., expiryDate: _Optional[str] = ..., vectorClock: _Optional[_Mapping[str, int]] = ..., orderId: _Optional[str] = ...) -> None: ...

class BooksRequest(_message.Message):
    __slots__ = ("books", "vectorClock", "orderId")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    BOOKS_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    ORDERID_FIELD_NUMBER: _ClassVar[int]
    books: _containers.RepeatedScalarFieldContainer[str]
    vectorClock: _containers.ScalarMap[str, int]
    orderId: str
    def __init__(self, books: _Optional[_Iterable[str]] = ..., vectorClock: _Optional[_Mapping[str, int]] = ..., orderId: _Optional[str] = ...) -> None: ...

class BooksResponse(_message.Message):
    __slots__ = ("isValid", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ISVALID_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    isValid: bool
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, isValid: bool = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class TransactionResponse(_message.Message):
    __slots__ = ("isValid", "reason", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ISVALID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    isValid: bool
    reason: str
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, isValid: bool = ..., reason: _Optional[str] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...
