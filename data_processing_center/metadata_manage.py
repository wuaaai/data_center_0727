"""元数据管理功能：提供元数据列表、添加元数据、取消元数据接口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


METADATA_STORE_FILE = Path(__file__).with_name("metadata_store.json")


class MetadataTableInfo(BaseModel):
    """元数据表信息。"""

    index: int = Field(..., description="序号")
    table_comment: str = Field(..., description="表中文名/注释")
    table_name: str = Field(..., description="表名(物理名)")
    business_domain: str = Field(..., description="所属业务域")


class MetadataListResponse(BaseModel):
    """元数据列表响应。"""

    code: int = Field(..., description="响应码")
    message: str = Field(..., description="响应说明")
    data: list[MetadataTableInfo] = Field(default_factory=list, description="元数据列表")


class MetadataActionResponse(BaseModel):
    """元数据新增/取消操作响应。"""

    code: int = Field(..., description="响应码")
    message: str = Field(..., description="响应说明")


class MetadataUpsertRequest(BaseModel):
    """新增元数据请求。"""

    table_comment: str = Field(default="", description="表中文名/注释")
    table_name: str = Field(..., description="表名(物理名)")
    business_domain: str = Field(default="未归类", description="所属业务域")


class MetadataCancelRequest(BaseModel):
    """取消元数据请求。"""

    table_name: str = Field(..., description="表名(物理名)")


class MetadataCatalogManager:
    """负责维护已添加为元数据的表列表。"""

    def __init__(self, store_file: Path | None = None) -> None:
        self.store_file = store_file or METADATA_STORE_FILE

    def _load_metadata_rows(self) -> list[dict[str, Any]]:
        """读取本地元数据存储。文件不存在时返回空列表。"""

        if not self.store_file.exists():
            return []

        with self.store_file.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            return []
        return data

    def _save_metadata_rows(self, rows: list[dict[str, Any]]) -> None:
        """保存元数据列表到本地 JSON 文件。"""

        with self.store_file.open("w", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)

    def list_metadata_tables(self) -> list[dict[str, Any]]:
        """查询元数据列表。"""

        rows = self._load_metadata_rows()
        result: list[dict[str, Any]] = []

        for index, row in enumerate(rows, start=1):
            result.append(
                {
                    "index": index,
                    "table_comment": row.get("table_comment", ""),
                    "table_name": row.get("table_name", ""),
                    "business_domain": row.get("business_domain", "未归类"),
                }
            )

        return result

    def get_metadata_table_names(self) -> set[str]:
        """返回已添加为元数据的表名集合。"""

        rows = self._load_metadata_rows()
        return {str(row.get("table_name", "")).upper() for row in rows if row.get("table_name")}

    def add_metadata_table(self, payload: MetadataUpsertRequest) -> None:
        """添加一张表到元数据列表中。"""

        rows = self._load_metadata_rows()
        table_name = payload.table_name.upper().strip()

        for row in rows:
            if str(row.get("table_name", "")).upper() == table_name:
                raise ValueError(f"表 {table_name} 已经添加为元数据。")

        rows.append(
            {
                "table_comment": payload.table_comment,
                "table_name": table_name,
                "business_domain": payload.business_domain or "未归类",
            }
        )
        self._save_metadata_rows(rows)

    def cancel_metadata_table(self, table_name: str) -> None:
        """从元数据列表中取消一张表。"""

        normalized_name = table_name.upper().strip()
        rows = self._load_metadata_rows()
        new_rows = [row for row in rows if str(row.get("table_name", "")).upper() != normalized_name]

        if len(new_rows) == len(rows):
            raise ValueError(f"表 {normalized_name} 不在元数据列表中。")

        self._save_metadata_rows(new_rows)

    def build_list_response(self) -> MetadataListResponse:
        """构造元数据列表接口响应。"""

        return MetadataListResponse(code=200, message="查询成功", data=self.list_metadata_tables())


router = APIRouter(prefix="/metadataManage", tags=["元数据管理"])


@router.get("/tables", response_model=MetadataListResponse, summary="查询元数据列表")
def get_metadata_tables() -> MetadataListResponse:
    """FastAPI 接口：查询元数据列表。"""

    manager = MetadataCatalogManager()
    try:
        return manager.build_list_response()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询元数据列表失败: {exc}") from exc


@router.post("/tables", response_model=MetadataActionResponse, summary="添加为元数据")
def add_metadata_table(payload: MetadataUpsertRequest) -> MetadataActionResponse:
    """FastAPI 接口：添加一张表为元数据。"""

    manager = MetadataCatalogManager()
    try:
        manager.add_metadata_table(payload)
        return MetadataActionResponse(code=200, message="添加元数据成功")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"添加元数据失败: {exc}") from exc


@router.post("/tables/cancel", response_model=MetadataActionResponse, summary="取消元数据")
def cancel_metadata_table(payload: MetadataCancelRequest) -> MetadataActionResponse:
    """FastAPI 接口：取消一张表的元数据状态。"""

    manager = MetadataCatalogManager()
    try:
        manager.cancel_metadata_table(payload.table_name)
        return MetadataActionResponse(code=200, message="取消元数据成功")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"取消元数据失败: {exc}") from exc
