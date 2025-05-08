from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class KeyValuePair(_message.Message):
    __slots__ = ("key", "value", "version", "type")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: str
    version: int
    type: WriteRequest.ValueType
    def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ..., version: _Optional[int] = ..., type: _Optional[_Union[WriteRequest.ValueType, str]] = ...) -> None: ...

class ReadRequest(_message.Message):
    __slots__ = ("key",)
    KEY_FIELD_NUMBER: _ClassVar[int]
    key: str
    def __init__(self, key: _Optional[str] = ...) -> None: ...

class ReadAllRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadAllResponse(_message.Message):
    __slots__ = ("success", "message", "items", "total_returned")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_RETURNED_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    items: _containers.RepeatedCompositeFieldContainer[KeyValuePair]
    total_returned: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., items: _Optional[_Iterable[_Union[KeyValuePair, _Mapping]]] = ..., total_returned: _Optional[int] = ...) -> None: ...

class ReadResponse(_message.Message):
    __slots__ = ("success", "value", "version", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    value: str
    version: int
    message: str
    def __init__(self, success: bool = ..., value: _Optional[str] = ..., version: _Optional[int] = ..., message: _Optional[str] = ...) -> None: ...

class WriteRequest(_message.Message):
    __slots__ = ("key", "value", "type")
    class ValueType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STRING: _ClassVar[WriteRequest.ValueType]
        INT: _ClassVar[WriteRequest.ValueType]
        FLOAT: _ClassVar[WriteRequest.ValueType]
        JSON: _ClassVar[WriteRequest.ValueType]
    STRING: WriteRequest.ValueType
    INT: WriteRequest.ValueType
    FLOAT: WriteRequest.ValueType
    JSON: WriteRequest.ValueType
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: str
    type: WriteRequest.ValueType
    def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ..., type: _Optional[_Union[WriteRequest.ValueType, str]] = ...) -> None: ...

class WriteResponse(_message.Message):
    __slots__ = ("success", "message", "version", "primary_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    version: int
    primary_id: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., version: _Optional[int] = ..., primary_id: _Optional[str] = ...) -> None: ...

class DecrementRequest(_message.Message):
    __slots__ = ("key", "amount")
    KEY_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    key: str
    amount: float
    def __init__(self, key: _Optional[str] = ..., amount: _Optional[float] = ...) -> None: ...

class IncrementRequest(_message.Message):
    __slots__ = ("key", "amount")
    KEY_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    key: str
    amount: float
    def __init__(self, key: _Optional[str] = ..., amount: _Optional[float] = ...) -> None: ...

class DecrementResponse(_message.Message):
    __slots__ = ("success", "new_value", "message", "current_value", "version", "primary_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    NEW_VALUE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VALUE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    new_value: float
    message: str
    current_value: float
    version: int
    primary_id: str
    def __init__(self, success: bool = ..., new_value: _Optional[float] = ..., message: _Optional[str] = ..., current_value: _Optional[float] = ..., version: _Optional[int] = ..., primary_id: _Optional[str] = ...) -> None: ...

class IncrementResponse(_message.Message):
    __slots__ = ("success", "new_value", "message", "current_value", "version", "primary_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    NEW_VALUE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VALUE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    new_value: float
    message: str
    current_value: float
    version: int
    primary_id: str
    def __init__(self, success: bool = ..., new_value: _Optional[float] = ..., message: _Optional[str] = ..., current_value: _Optional[float] = ..., version: _Optional[int] = ..., primary_id: _Optional[str] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("primary_id", "term", "updates", "last_index")
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    UPDATES_FIELD_NUMBER: _ClassVar[int]
    LAST_INDEX_FIELD_NUMBER: _ClassVar[int]
    primary_id: str
    term: int
    updates: _containers.RepeatedScalarFieldContainer[str]
    last_index: int
    def __init__(self, primary_id: _Optional[str] = ..., term: _Optional[int] = ..., updates: _Optional[_Iterable[str]] = ..., last_index: _Optional[int] = ...) -> None: ...

class HeartbeatResponse(_message.Message):
    __slots__ = ("success", "message", "term")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    term: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., term: _Optional[int] = ...) -> None: ...

class VoteRequest(_message.Message):
    __slots__ = ("term", "candidate_id", "last_log_index")
    TERM_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_ID_FIELD_NUMBER: _ClassVar[int]
    LAST_LOG_INDEX_FIELD_NUMBER: _ClassVar[int]
    term: int
    candidate_id: str
    last_log_index: int
    def __init__(self, term: _Optional[int] = ..., candidate_id: _Optional[str] = ..., last_log_index: _Optional[int] = ...) -> None: ...

class VoteResponse(_message.Message):
    __slots__ = ("vote_granted", "term")
    VOTE_GRANTED_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    vote_granted: bool
    term: int
    def __init__(self, vote_granted: bool = ..., term: _Optional[int] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("node_id", "role", "primary_id", "record_count", "term")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    RECORD_COUNT_FIELD_NUMBER: _ClassVar[int]
    TERM_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    role: str
    primary_id: str
    record_count: int
    term: int
    def __init__(self, node_id: _Optional[str] = ..., role: _Optional[str] = ..., primary_id: _Optional[str] = ..., record_count: _Optional[int] = ..., term: _Optional[int] = ...) -> None: ...
