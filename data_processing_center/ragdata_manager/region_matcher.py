"""
地区自动匹配引擎 — 根据文件名/目录名自动识别河北12地市+省本级。

匹配优先级（从高到低）:
  1. 区划编码  — "1301000_预算报告.pdf"
  2. 中文全称  — "石家庄市预算执行报告.docx"
  3. 中文简称  — "石市财政2026.pdf"
  4. 拼音     — "shijiazhuang_report.pdf"
  5. 目录名   — "D:\\邯郸市\\预算.pdf"
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import os
from pathlib import Path

# ── 内置规则库: 河北 12 地市 + 省本级 ──
# "1301000": {"full": ["石家庄"], "short": ["石市"], "pinyin": ["shijiazhuang", "sjz"]}
DEFAULT_RULES: dict[str, dict[str, list[str]]] = {
    "1301000":  {"full": ["石家庄"],   "short": ["石市"], "pinyin": ["shijiazhuang", "sjz"]},
    "1302000":  {"full": ["唐山"],     "short": [],       "pinyin": ["tangshan", "ts"]},
    "1303000":  {"full": ["秦皇岛"],   "short": ["秦市"], "pinyin": ["qinhuangdao", "qhd"]},
    "1304000":  {"full": ["邯郸"],     "short": ["邯市"], "pinyin": ["handan", "hd"]},
    "1305000":  {"full": ["邢台"],     "short": [],       "pinyin": ["xingtai", "xt"]},
    "1306000":  {"full": ["保定"],     "short": [],       "pinyin": ["baoding", "bd"]},
    "1307000":  {"full": ["张家口"],   "short": ["张市"], "pinyin": ["zhangjiakou", "zjk"]},
    "1308000":  {"full": ["承德"],     "short": [],       "pinyin": ["chengde", "cd"]},
    "1309000":  {"full": ["沧州"],     "short": [],       "pinyin": ["cangzhou", "cz"]},
    "1310000":  {"full": ["廊坊"],     "short": [],       "pinyin": ["langfang", "lf"]},
    "1311000":  {"full": ["衡水"],     "short": [],       "pinyin": ["hengshui", "hs"]},
    "1331000":  {"full": ["雄安"],     "short": [],       "pinyin": ["xiongan", "xa"]},
    "130000000": {"full": ["省本级", "省本", "省级"], "short": [], "pinyin": ["shengbenji"]},
}

# 区划编码→中文名映射（从达梦数据库同步）
CODE_TO_NAME: dict[str, str] = {
    "1301000": "石家庄市", "1302000": "唐山市", "1303000": "秦皇岛市",
    "1304000": "邯郸市", "1305000": "邢台市", "1306000": "保定市",
    "1307000": "张家口市", "1308000": "承德市", "1309000": "沧州市",
    "1310000": "廊坊市", "1311000": "衡水市", "1331000": "雄安新区",
    "130000000": "河北省本级",
}


class RegionMatcher:
    """地区自动匹配引擎。"""

    def __init__(self, custom_rules: dict[str, dict[str, list[str]]] | None = None):
        """初始化匹配器。

        Args:
            custom_rules: 自定义规则，格式同 DEFAULT_RULES。会与内置规则合并（自定义优先）。
        """
        self.rules: dict[str, dict[str, list[str]]] = dict(DEFAULT_RULES)
        if custom_rules:
            for code, patterns in custom_rules.items():
                if code in self.rules:
                    for key in ("full", "short", "pinyin"):
                        existing = set(self.rules[code][key])
                        for p in patterns.get(key, []):
                            existing.add(p)
                        self.rules[code][key] = list(existing)
                else:
                    self.rules[code] = {
                        "full": patterns.get("full", []),
                        "short": patterns.get("short", []),
                        "pinyin": patterns.get("pinyin", []),
                    }

    # ── 单文件匹配 ──
    def match(self, filename: str, dirname: str = "") -> dict:
        """单文件匹配。

        Args:
            filename: 文件名 (如 "石家庄市预算报告.pdf")
            dirname:   所在目录名 (如 "邯郸市")

        Returns:
            {region_code, region_name, confidence, match_type}
            未匹配则返回 {region_code: "", region_name: "", confidence: 0, match_type: ""}
        """
        # 去掉扩展名
        stem = Path(filename).stem
        name_lower = stem.lower()

        # 1) 区划编码匹配 (最高优先级)
        code_match = re.search(r'(13\d{5,7})', stem)
        if code_match:
            code = code_match.group(1)
            # 9位→7位标准化: 末尾全0则截断
            if len(code) == 9 and code[3:] == "000000":
                code = code[:7] + "000"
            if code in self.rules:
                return {
                    "region_code": code,
                    "region_name": CODE_TO_NAME.get(code, ""),
                    "confidence": 1.0,
                    "match_type": "code",
                }

        # 2-4) 关键词匹配: full > short > pinyin
        for match_type in ("full", "short", "pinyin"):
            for code, patterns in self.rules.items():
                for pattern in patterns.get(match_type, []):
                    if pattern.lower() in name_lower:
                        confidence = {"full": 0.9, "short": 0.7, "pinyin": 0.5}[match_type]
                        return {
                            "region_code": code,
                            "region_name": CODE_TO_NAME.get(code, ""),
                            "confidence": confidence,
                            "match_type": match_type,
                        }

        # 5) 目录名匹配 (fallback)
        if dirname:
            for code, patterns in self.rules.items():
                for pattern in patterns.get("full", []) + patterns.get("short", []):
                    if pattern in dirname:
                        return {
                            "region_code": code,
                            "region_name": CODE_TO_NAME.get(code, ""),
                            "confidence": 0.5,
                            "match_type": "dirname",
                        }
            # 拼音 fallback
            dir_lower = dirname.lower()
            for code, patterns in self.rules.items():
                for pattern in patterns.get("pinyin", []):
                    if pattern in dir_lower:
                        return {
                            "region_code": code,
                            "region_name": CODE_TO_NAME.get(code, ""),
                            "confidence": 0.3,
                            "match_type": "dirname_pinyin",
                        }

        return {"region_code": "", "region_name": "", "confidence": 0.0, "match_type": ""}

    # ── 批量匹配 ──
    def batch_match(self, files: list[dict]) -> dict:
        """批量匹配，返回分组结果。

        Args:
            files: [{filename: "...", dirname: "..."}, ...]

        Returns:
            {
                matched: [{filename, region_code, region_name, confidence, match_type}, ...],
                unmatched: [{filename, dirname}, ...],
                by_region: {region_code: {region_name, files: [...]}, ...}
            }
        """
        matched: list[dict] = []
        unmatched: list[dict] = []
        by_region: dict[str, dict] = {}

        for f in files:
            r = self.match(f.get("filename", ""), f.get("dirname", ""))
            if r["region_code"]:
                r["filename"] = f.get("filename", "")
                r["dirname"] = f.get("dirname", "")
                matched.append(r)
                code = r["region_code"]
                if code not in by_region:
                    by_region[code] = {"region_code": code, "region_name": r["region_name"], "files": []}
                by_region[code]["files"].append(r)
            else:
                unmatched.append({
                    "filename": f.get("filename", ""),
                    "dirname": f.get("dirname", ""),
                })

        return {
            "matched": matched,
            "unmatched": unmatched,
            "by_region": by_region,
            "total": len(files),
            "match_rate": len(matched) / len(files) if files else 0,
        }

    # ── 分配预览 (带 KB 建议) ──
    def preview_allocation(self, files: list[dict], kb_id: str = "default") -> list[dict]:
        """预览分配结果，适合前端展示。

        Returns:
            [{filename, region_code, region_name, kb_id, confidence, match_type, dirname}, ...]
        """
        results = []
        for f in files:
            r = self.match(f.get("filename", ""), f.get("dirname", ""))
            results.append({
                "filename": f.get("filename", ""),
                "dirname": f.get("dirname", ""),
                "region_code": r["region_code"],
                "region_name": r["region_name"],
                "kb_id": kb_id,
                "confidence": r["confidence"],
                "match_type": r["match_type"],
            })
        return results


# ── 全局单例 ──
_matcher: RegionMatcher | None = None


def get_matcher() -> RegionMatcher:
    """获取全局匹配器单例。"""
    global _matcher
    if _matcher is None:
        _matcher = RegionMatcher()
    return _matcher


# ── 快捷函数 ──
def match_region(filename: str, dirname: str = "") -> dict:
    return get_matcher().match(filename, dirname)


def batch_match_regions(files: list[dict]) -> dict:
    return get_matcher().batch_match(files)
