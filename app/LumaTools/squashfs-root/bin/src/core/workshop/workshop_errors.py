from __future__ import annotations

from enum import StrEnum


class WorkshopErrorCode(StrEnum):
    NEEDS_LOGIN = "needs_login"
    NO_LICENSE = "no_license"
    PRIVATE_ITEM = "private_item"
    ITEM_NOT_FOUND = "item_not_found"
    AGREEMENT_REQUIRED = "agreement_required"
    NETWORK_ERROR = "network_error"
    DISK_ERROR = "disk_error"
    UNSUPPORTED_GAME = "unsupported_game"
    FAILED = "failed"


class WorkshopError(RuntimeError):
    def __init__(self, code: WorkshopErrorCode, message: str, details: str = ""):
        super().__init__(message)
        self.code = code
        self.details = details


def classify_steamcmd_error(output: str) -> WorkshopErrorCode:
    text = (output or "").lower()
    rules = (
        (
            WorkshopErrorCode.AGREEMENT_REQUIRED,
            ("workshop agreement", "subscriber agreement", "must accept"),
        ),
        (
            WorkshopErrorCode.PRIVATE_ITEM,
            ("private item", "access denied", "insufficient privilege"),
        ),
        (
            WorkshopErrorCode.NO_LICENSE,
            ("no subscription", "no license", "license required"),
        ),
        (
            WorkshopErrorCode.NEEDS_LOGIN,
            ("login failure", "account logon denied", "invalid password", "two-factor"),
        ),
        (
            WorkshopErrorCode.ITEM_NOT_FOUND,
            ("item not found", "file not found", "does not exist"),
        ),
        (
            WorkshopErrorCode.DISK_ERROR,
            ("disk write failure", "no space left", "permission denied", "read-only file system"),
        ),
        (
            WorkshopErrorCode.NETWORK_ERROR,
            ("connection failed", "timeout", "network is unreachable", "failed to connect"),
        ),
        (
            WorkshopErrorCode.UNSUPPORTED_GAME,
            ("workshop is not supported", "invalid app id"),
        ),
    )
    for code, needles in rules:
        if any(needle in text for needle in needles):
            return code
    return WorkshopErrorCode.FAILED
