"""数据源管理功能：连接达梦数据库并提供 FastAPI 接口。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from metadata_manage import MetadataCatalogManager


@dataclass(slots=True)
class DMDataSourceConfig:
    """达梦数据源配置。"""

    host: str = "localhost"
    port: int = 5236
    schema: str = "CH_AI"
    username: str = "SYSDBA"
    password: str = "SYSDBA001"

    @classmethod
    def from_env(cls) -> "DMDataSourceConfig":
        """从环境变量读取数据库连接配置。"""

        return cls(
            host=os.getenv("DM_HOST", "localhost"),
            port=int(os.getenv("DM_PORT", "5236")),
            schema=os.getenv("DM_SCHEMA", "CH_AI"),
            username=os.getenv("DM_USERNAME", "SYSDBA"),
            password=os.getenv("DM_PASSWORD", "SYSDBA001"),
        )


class TableInfo(BaseModel):
    """前端表格使用的单条表信息。"""

    index: int = Field(..., description="序号")
    table_comment: str = Field(..., description="表中文名/注释")
    table_name: str = Field(..., description="表名(物理名)")
    business_domain: str = Field(..., description="所属业务域")
    metadata_status: str = Field(..., description="元数据状态")


class TableListResponse(BaseModel):
    """查询全部表的接口响应。"""

    code: int = Field(..., description="响应码，200 表示成功")
    message: str = Field(..., description="响应说明")
    data: list[TableInfo] = Field(default_factory=list, description="表列表数据")


class DataManageRegistry:
    """负责连接达梦数据库，并提供“查询所有表”的服务接口。"""

    def __init__(self, config: DMDataSourceConfig | None = None) -> None:
        self.config = config or DMDataSourceConfig.from_env()

    def _load_driver(self):
        """延迟导入达梦驱动，避免模块导入时就报错。"""

        try:
            import dmPython  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未安装达梦驱动 dmPython，请先安装后再调用当前接口。") from exc
        return dmPython

    def _validate_schema_name(self) -> str:
        """仅允许安全的 schema 名，避免 SQL 拼接风险。"""

        schema_name = self.config.schema.upper().strip()
        if not re.fullmatch(r"[A-Z0-9_]+", schema_name):
            raise ValueError(f"非法的 schema 名称: {self.config.schema}")
        return schema_name

    def _build_connect_kwargs(self) -> dict[str, Any]:
        """组装达梦连接参数。"""

        if not self.config.username or not self.config.password:
            raise ValueError("缺少达梦数据库账号或密码，请设置环境变量 DM_USERNAME 和 DM_PASSWORD。")

        return {
            "user": self.config.username,
            "password": self.config.password,
            "server": self.config.host,
            "port": self.config.port,
        }

    def get_connection(self):
        """创建达梦数据库连接。"""

        dm_python = self._load_driver()
        connect_kwargs = self._build_connect_kwargs()
        return dm_python.connect(**connect_kwargs)

    def query_all_tables(
        self,
        domain_mapping: dict[str, str] | None = None,
        added_table_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """查询当前 schema 下的所有表，并整理为前端可直接使用的数据。"""

        schema_name = self._validate_schema_name()
        table_domain_mapping = {key.upper(): value for key, value in (domain_mapping or {}).items()}
        metadata_table_names = {name.upper() for name in (added_table_names or set())}

        sql = f"""
            SELECT
                t.TABLE_NAME,
                COALESCE(c.COMMENTS, '') AS TABLE_COMMENT
            FROM ALL_TABLES t
            LEFT JOIN ALL_TAB_COMMENTS c
                ON c.OWNER = t.OWNER
               AND c.TABLE_NAME = t.TABLE_NAME
            WHERE t.OWNER = '{schema_name}'
            ORDER BY t.TABLE_NAME
        """

        with self.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()

        table_list: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            table_name = str(row[0]).upper()
            table_comment = str(row[1] or "")
            metadata_status = "已添加" if table_name in metadata_table_names else "未添加"

            table_list.append(
                {
                    "index": index,
                    "table_comment": table_comment,
                    "table_name": table_name,
                    "business_domain": table_domain_mapping.get(table_name, "未归类"),
                    "metadata_status": metadata_status,
                }
            )

        return table_list

    def get_all_tables_api_response(
        self,
        domain_mapping: dict[str, str] | None = None,
        added_table_names: set[str] | None = None,
    ) -> TableListResponse:
        """服务接口：返回给前端的统一响应结构。"""

        data = self.query_all_tables(domain_mapping=domain_mapping, added_table_names=added_table_names)
        return TableListResponse(code=200, message="查询成功", data=data)


router = APIRouter(prefix="/dataManage", tags=["数据源管理"])


@router.get("/tables", response_model=TableListResponse, summary="查询当前数据源下的所有表")
def get_all_tables() -> TableListResponse:
    """FastAPI 接口函数：返回当前达梦数据源下的所有表。"""

    service = DataManageRegistry()
    metadata_manager = MetadataCatalogManager()
    try:
        added_table_names = metadata_manager.get_metadata_table_names()
        return service.get_all_tables_api_response(added_table_names=added_table_names)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询达梦表信息失败: {exc}") from exc


if __name__ == "__main__":
    service = DataManageRegistry()
    response = service.get_all_tables_api_response()
    print(response.model_dump())
