"""Shared datatypes for CodeClaw."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileOperationResult:
    action: str
    path: str
    detail: str = ""
    diff: str = ""
