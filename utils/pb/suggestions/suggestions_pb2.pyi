from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SuggestionInitRequest(_message.Message):
    __slots__ = ("order_id", "book_tokens", "limit", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    BOOK_TOKENS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    book_tokens: _containers.RepeatedScalarFieldContainer[str]
    limit: int
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, order_id: _Optional[str] = ..., book_tokens: _Optional[_Iterable[str]] = ..., limit: _Optional[int] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class SuggestionInitResponse(_message.Message):
    __slots__ = ("success", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    success: bool
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, success: bool = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class RecommendationRequest(_message.Message):
    __slots__ = ("order_id", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, order_id: _Optional[str] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class RecommendationResponse(_message.Message):
    __slots__ = ("recommendations", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    RECOMMENDATIONS_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    recommendations: _containers.RepeatedCompositeFieldContainer[Recommendation]
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, recommendations: _Optional[_Iterable[_Union[Recommendation, _Mapping]]] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class Recommendation(_message.Message):
    __slots__ = ("book", "confidence_score", "reason")
    BOOK_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_SCORE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    book: Book
    confidence_score: float
    reason: str
    def __init__(self, book: _Optional[_Union[Book, _Mapping]] = ..., confidence_score: _Optional[float] = ..., reason: _Optional[str] = ...) -> None: ...

class Book(_message.Message):
    __slots__ = ("id", "title", "author", "description", "genres", "publish_date")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    GENRES_FIELD_NUMBER: _ClassVar[int]
    PUBLISH_DATE_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    author: str
    description: str
    genres: _containers.RepeatedScalarFieldContainer[str]
    publish_date: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., author: _Optional[str] = ..., description: _Optional[str] = ..., genres: _Optional[_Iterable[str]] = ..., publish_date: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ClearOrderRequest(_message.Message):
    __slots__ = ("order_id", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, order_id: _Optional[str] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class ClearOrderResponse(_message.Message):
    __slots__ = ("success", "error", "vectorClock")
    class VectorClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    VECTORCLOCK_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    vectorClock: _containers.ScalarMap[str, int]
    def __init__(self, success: bool = ..., error: _Optional[str] = ..., vectorClock: _Optional[_Mapping[str, int]] = ...) -> None: ...
