"""
分块策略接口：定义 ChunkingStrategy ABC 和注册表。

通过注册表可以一键切换分块策略，支持：
  - 配置文件：config.CHUNKING_STRATEGY
  - CLI 参数：--chunking-strategy
  - 代码调用：get_strategy(name)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChunkContext:
    """传递给分块策略的上下文元数据。"""
    doc_title: str = ""
    pdf_stem: str = ""
    total_pages: int = 0
    image_dir: Optional[str] = None


class ChunkingStrategy(ABC):
    """分块策略抽象基类。

    接收干净段落（有 style/level，无标记），
    返回带 *** / <-split-> 标记的段落。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称，用于注册和选择。"""
        ...

    @abstractmethod
    def chunk(
        self,
        paragraphs: list[dict],
        context: Optional[ChunkContext] = None,
    ) -> list[dict]:
        """对干净段落插入分块标记。

        Parameters
        ----------
        paragraphs : list[dict]
            干净段落列表，每项格式:
              {"text": str, "style": str, "level": int, "image": optional dict}
            text 不含 *** 或 <-split-> 标记。
        context : ChunkContext, optional
            文档元数据（标题、文件名、页数等）。

        Returns
        -------
        list[dict]
            插入分块标记后的段落列表。
        """
        ...


# ======================================================================
# 策略注册表
# ======================================================================

_registry: dict[str, type[ChunkingStrategy]] = {}


def register_strategy(name: str, cls: type[ChunkingStrategy]) -> None:
    """注册一个分块策略类。"""
    if not issubclass(cls, ChunkingStrategy):
        raise TypeError(f"{cls.__name__} 必须继承 ChunkingStrategy")
    _registry[name] = cls


def get_strategy(name: str) -> ChunkingStrategy:
    """根据名称获取策略实例。

    如果指定名称的策略未注册，回退到 "default"。
    """
    cls = _registry.get(name)
    if cls is None:
        # 回退到 default
        cls = _registry.get("default")
    if cls is None:
        raise ValueError(
            f"未找到分块策略 '{name}'，且默认策略也未注册。"
            f"可用策略: {list(_registry.keys())}"
        )
    return cls()


def list_strategies() -> list[str]:
    """列出所有已注册的策略名称。"""
    return list(_registry.keys())
