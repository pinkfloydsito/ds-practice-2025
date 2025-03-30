from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FraudInitRequest(_message.Message):
    __slots__ = ("amount", "ip_address", "email", "billing_country", "billing_city", "payment_method", "order_id")
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    IP_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    BILLING_COUNTRY_FIELD_NUMBER: _ClassVar[int]
    BILLING_CITY_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    amount: float
    ip_address: str
    email: str
    billing_country: str
    billing_city: str
    payment_method: str
    order_id: str
    def __init__(self, amount: _Optional[float] = ..., ip_address: _Optional[str] = ..., email: _Optional[str] = ..., billing_country: _Optional[str] = ..., billing_city: _Optional[str] = ..., payment_method: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class FraudInitResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: bool = ...) -> None: ...

class FraudRequest(_message.Message):
    __slots__ = ("amount", "ip_address", "email", "billing_country", "billing_city", "payment_method", "order_id")
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    IP_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    BILLING_COUNTRY_FIELD_NUMBER: _ClassVar[int]
    BILLING_CITY_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    amount: float
    ip_address: str
    email: str
    billing_country: str
    billing_city: str
    payment_method: str
    order_id: str
    def __init__(self, amount: _Optional[float] = ..., ip_address: _Optional[str] = ..., email: _Optional[str] = ..., billing_country: _Optional[str] = ..., billing_city: _Optional[str] = ..., payment_method: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class FraudResponse(_message.Message):
    __slots__ = ("fraud_probability", "action", "details", "reasons")
    FRAUD_PROBABILITY_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    REASONS_FIELD_NUMBER: _ClassVar[int]
    fraud_probability: float
    action: str
    details: _struct_pb2.Struct
    reasons: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, fraud_probability: _Optional[float] = ..., action: _Optional[str] = ..., details: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., reasons: _Optional[_Iterable[str]] = ...) -> None: ...
