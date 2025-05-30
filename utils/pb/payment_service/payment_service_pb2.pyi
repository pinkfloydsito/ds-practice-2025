from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PrepareRequest(_message.Message):
    __slots__ = ("transaction_id", "amount", "payment_method", "customer_id", "metadata", "order_id")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    CUSTOMER_ID_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    amount: float
    payment_method: str
    customer_id: str
    metadata: _containers.ScalarMap[str, str]
    order_id: str
    def __init__(self, transaction_id: _Optional[str] = ..., amount: _Optional[float] = ..., payment_method: _Optional[str] = ..., customer_id: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ..., order_id: _Optional[str] = ...) -> None: ...

class PrepareResponse(_message.Message):
    __slots__ = ("can_commit", "error_message", "payment_id")
    CAN_COMMIT_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_ID_FIELD_NUMBER: _ClassVar[int]
    can_commit: bool
    error_message: str
    payment_id: str
    def __init__(self, can_commit: bool = ..., error_message: _Optional[str] = ..., payment_id: _Optional[str] = ...) -> None: ...

class CommitRequest(_message.Message):
    __slots__ = ("transaction_id", "payment_id", "order_id")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    payment_id: str
    order_id: str
    def __init__(self, transaction_id: _Optional[str] = ..., payment_id: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class CommitResponse(_message.Message):
    __slots__ = ("success", "error_message", "payment_result")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_RESULT_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error_message: str
    payment_result: PaymentResult
    def __init__(self, success: bool = ..., error_message: _Optional[str] = ..., payment_result: _Optional[_Union[PaymentResult, _Mapping]] = ...) -> None: ...

class PaymentResult(_message.Message):
    __slots__ = ("payment_id", "amount", "payment_method", "status", "confirmation_code", "timestamp")
    PAYMENT_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CONFIRMATION_CODE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    payment_id: str
    amount: float
    payment_method: str
    status: str
    confirmation_code: str
    timestamp: int
    def __init__(self, payment_id: _Optional[str] = ..., amount: _Optional[float] = ..., payment_method: _Optional[str] = ..., status: _Optional[str] = ..., confirmation_code: _Optional[str] = ..., timestamp: _Optional[int] = ...) -> None: ...

class AbortRequest(_message.Message):
    __slots__ = ("transaction_id", "payment_id", "reason")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    payment_id: str
    reason: str
    def __init__(self, transaction_id: _Optional[str] = ..., payment_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class AbortResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("transaction_id",)
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    def __init__(self, transaction_id: _Optional[str] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("transaction_id", "status", "payment_id", "amount", "payment_method", "last_updated", "error_message")
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    LAST_UPDATED_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    status: str
    payment_id: str
    amount: float
    payment_method: str
    last_updated: int
    error_message: str
    def __init__(self, transaction_id: _Optional[str] = ..., status: _Optional[str] = ..., payment_id: _Optional[str] = ..., amount: _Optional[float] = ..., payment_method: _Optional[str] = ..., last_updated: _Optional[int] = ..., error_message: _Optional[str] = ...) -> None: ...
