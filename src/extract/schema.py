"""LLM 抽取結果的格式（pydantic）。同一份模型也當 Structured Outputs 的 JSON Schema，限制 LLM 的輸出。

只放「要讀懂文章才能填」的欄位；trip_id、url、source_type、edge_id、seq 由程式填，
座標、營業時間等由 Google Places 填，duration、source_count 等統計在匯出時計算。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VisitType = Literal["入內參觀", "下車拍照", "行車經過"]
Mode = Literal["大眾運輸", "自駕", "走路"]
ModeBasis = Literal["原文明寫", "旅行社跟團預設遊覽車", "同園區步行範圍", "途經車站", "遊記起訖點記成車站", "原文未寫"]


class Observation(BaseModel):
    name_raw: str
    visit_type: VisitType | None
    stay_min: int | None
    as_area: bool


class Node(BaseModel):
    poi_id: str
    poi_name: str
    observations: list[Observation]


class Edge(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from")  # from 是 Python 保留字
    to: str
    mode: Mode | None
    mode_inferred: bool
    mode_basis: ModeBasis
    vehicle: str | None
    duration_min: int | None
    via: list[str]
    day: int


class Extraction(BaseModel):
    months: list[int]
    nodes: list[Node]
    edges: list[Edge]
