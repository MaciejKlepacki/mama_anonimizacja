"""Ustawienia aplikacji: domyślne z config/default_settings.json, nadpisania w config/settings.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "default_settings.json"
USER_SETTINGS_PATH = CONFIG_DIR / "settings.json"


class EntitySettings(BaseModel):
    enabled: bool = True
    label: str = Field(..., description="Etykieta placeholdera, np. OSOBA → [OSOBA_1]")
    threshold: float = Field(0.4, ge=0.0, le=1.0)

    @field_validator("label")
    @classmethod
    def _label_ok(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not v:
            raise ValueError("Etykieta nie może być pusta")
        if "[" in v or "]" in v:
            raise ValueError("Etykieta nie może zawierać nawiasów kwadratowych")
        return v


class CustomRecognizer(BaseModel):
    """Własny rozpoznawacz oparty o wyrażenia regularne (Presidio PatternRecognizer)."""

    name: str
    entity: str = Field(..., description="Typ encji Presidio, np. NR_SPRAWY")
    label: Optional[str] = Field(None, description="Etykieta placeholdera; domyślnie = entity")
    patterns: List[str] = Field(default_factory=list)
    deny_list: List[str] = Field(default_factory=list)
    context: List[str] = Field(default_factory=list)
    score: float = Field(0.6, ge=0.0, le=1.0)
    threshold: float = Field(0.4, ge=0.0, le=1.0)
    enabled: bool = True

    @field_validator("entity")
    @classmethod
    def _entity_ok(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.fullmatch(r"[A-Z0-9_ĄĆĘŁŃÓŚŹŻ]+", v):
            raise ValueError("Typ encji: tylko wielkie litery, cyfry i podkreślenia")
        return v

    @field_validator("patterns")
    @classmethod
    def _patterns_ok(cls, v: List[str]) -> List[str]:
        for p in v:
            try:
                re.compile(p)
            except re.error as e:  # pragma: no cover - komunikat
                raise ValueError(f"Błędne wyrażenie regularne {p!r}: {e}")
        return v

    @property
    def placeholder_label(self) -> str:
        return (self.label or self.entity).strip().upper().replace(" ", "_")


class DocxSettings(BaseModel):
    detect_bold_headings: bool = True
    include_footnotes: bool = True
    include_headers_footers: bool = False
    merge_wrapped_lines: bool = True  # dokument z PDF: każda linia to osobny akapit → sklejamy w zdania
    drop_page_numbers: bool = True  # samotne numery stron ("2", "3", …) z konwersji PDF


class OutputSettings(BaseModel):
    include_intro: bool = True
    include_legend: bool = True
    title: str = "Dokument (zanonimizowany)"


class Settings(BaseModel):
    language: str = "pl"
    spacy_model: str = "pl_core_news_lg"
    entities: Dict[str, EntitySettings] = Field(default_factory=dict)
    custom_recognizers: List[CustomRecognizer] = Field(default_factory=list)
    allow_list: List[str] = Field(default_factory=list)
    deny_list: Dict[str, List[str]] = Field(default_factory=dict)
    docx: DocxSettings = Field(default_factory=DocxSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)

    # --- pomocnicze -------------------------------------------------------
    def enabled_entities(self) -> List[str]:
        """Encje w pełni włączone (model NER + rozpoznawacze)."""
        ents = [k for k, v in self.entities.items() if v.enabled]
        ents += [c.entity for c in self.custom_recognizers if c.enabled]
        return list(dict.fromkeys(ents))

    def deny_only_entities(self) -> List[str]:
        """Encje wyłączone, ale z deny-listą: anonimizujemy wyłącznie frazy z listy."""
        enabled = set(self.enabled_entities())
        return [e for e, v in self.deny_list.items() if v and e not in enabled]

    def threshold_for(self, entity: str) -> float:
        if entity in self.entities:
            return self.entities[entity].threshold
        for c in self.custom_recognizers:
            if c.entity == entity:
                return c.threshold
        return 0.4

    def label_for(self, entity: str) -> str:
        if entity in self.entities:
            return self.entities[entity].label
        for c in self.custom_recognizers:
            if c.entity == entity:
                return c.placeholder_label
        return entity

    def engine_signature(self) -> str:
        """Fragment ustawień wpływający na budowę silnika (cache)."""
        data = self.model_dump(mode="json")
        data.pop("output", None)
        data.pop("docx", None)
        data.pop("allow_list", None)  # allow-lista podmieniana jest bez przebudowy silnika
        return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_settings(user_path: Path = USER_SETTINGS_PATH) -> Settings:
    """Ładuje ustawienia: domyślne + (jeśli istnieje) plik użytkownika."""
    data = _read_json(DEFAULT_SETTINGS_PATH)
    if user_path.exists():
        user = _read_json(user_path)
        data = _merge(data, user)
    return Settings.model_validate(data)


def save_settings(settings: Settings, user_path: Path = USER_SETTINGS_PATH) -> None:
    user_path.parent.mkdir(parents=True, exist_ok=True)
    with user_path.open("w", encoding="utf-8") as f:
        json.dump(settings.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        f.write("\n")


def reset_settings(user_path: Path = USER_SETTINGS_PATH) -> Settings:
    if user_path.exists():
        user_path.unlink()
    return load_settings(user_path)


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k == "entities":
            merged = dict(out[k])
            for ent, cfg in v.items():
                merged[ent] = {**merged.get(ent, {}), **cfg} if isinstance(cfg, dict) else cfg
            out[k] = merged
        elif isinstance(v, dict) and isinstance(out.get(k), dict) and k in ("docx", "output"):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out
