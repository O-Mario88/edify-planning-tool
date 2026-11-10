from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PortfolioSchool(_message.Message):
    __slots__ = ("school_type", "enrollment")
    SCHOOL_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    school_type: str
    enrollment: int
    def __init__(self, school_type: _Optional[str] = ..., enrollment: _Optional[int] = ...) -> None: ...

class SummarizePortfolioRequest(_message.Message):
    __slots__ = ("schools",)
    SCHOOLS_FIELD_NUMBER: _ClassVar[int]
    schools: _containers.RepeatedCompositeFieldContainer[PortfolioSchool]
    def __init__(self, schools: _Optional[_Iterable[_Union[PortfolioSchool, _Mapping]]] = ...) -> None: ...

class SummarizePortfolioResponse(_message.Message):
    __slots__ = ("school_count", "schools_by_type", "schools_with_enrollment", "total_enrollment", "median_enrollment")
    class SchoolsByTypeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SCHOOL_COUNT_FIELD_NUMBER: _ClassVar[int]
    SCHOOLS_BY_TYPE_FIELD_NUMBER: _ClassVar[int]
    SCHOOLS_WITH_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    MEDIAN_ENROLLMENT_FIELD_NUMBER: _ClassVar[int]
    school_count: int
    schools_by_type: _containers.ScalarMap[str, int]
    schools_with_enrollment: int
    total_enrollment: int
    median_enrollment: float
    def __init__(self, school_count: _Optional[int] = ..., schools_by_type: _Optional[_Mapping[str, int]] = ..., schools_with_enrollment: _Optional[int] = ..., total_enrollment: _Optional[int] = ..., median_enrollment: _Optional[float] = ...) -> None: ...
