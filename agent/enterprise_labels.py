from __future__ import annotations

from typing import Any

LABEL_RANK = {
    "Public": 0,
    "Internal": 1,
    "Sensitive": 2,
    "Confidential": 3,
    "Highly Confidential": 4,
}

SECRET_FINDINGS = {
    "api_key",
    "aws_key",
    "private_key",
    "password_in_text",
    "jwt_token",
    "connection_string",
}

REGULATED_FINDINGS = {
    "ssn",
    "aadhaar",
    "pan_card",
    "credit_card",
    "iban",
    "bank_account",
}

SENSITIVE_FINDINGS = {
    "email",
    "phone",
}

INTERNAL_FINDINGS = {
    "ipv4_private",
}


def normalize_findings(findings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(findings or [])


def derive_enterprise_label(
    findings: list[dict[str, Any]] | None,
    *,
    risk: str = "none",
    risk_score: int = 0,
    inspect_status: str = "",
) -> dict[str, Any]:
    items = normalize_findings(findings)
    finding_types = [str(item.get("type", "") or "") for item in items if item.get("type")]
    categories: set[str] = set()
    reasons: list[str] = []

    for finding_type in finding_types:
        normalized = finding_type.lower()
        raw_name = normalized.split(":", 1)[-1]
        if raw_name in SECRET_FINDINGS:
            categories.add("secret")
            reasons.append(f"{finding_type} detected")
        elif raw_name in REGULATED_FINDINGS:
            categories.add("regulated")
            reasons.append(f"{finding_type} detected")
        elif normalized.startswith("keyword:") or normalized.startswith("custom:") or raw_name in SENSITIVE_FINDINGS:
            categories.add("sensitive")
            reasons.append(f"{finding_type} detected")
        elif raw_name in INTERNAL_FINDINGS:
            categories.add("internal")
            reasons.append(f"{finding_type} detected")

    enterprise_label = "Public"
    if "secret" in categories:
        enterprise_label = "Highly Confidential"
    elif "regulated" in categories:
        enterprise_label = "Confidential"
    elif "sensitive" in categories:
        enterprise_label = "Sensitive"
    elif "internal" in categories:
        enterprise_label = "Internal"
    elif items:
        enterprise_label = "Sensitive"
    elif str(inspect_status or "").lower() == "inspected":
        enterprise_label = "Public"
    elif risk in {"low", "medium", "high"}:
        enterprise_label = "Internal"

    label_source = "content_inspection" if items else "inspection_default"
    label_reason = "; ".join(reasons[:4]) if reasons else (
        "No sensitive patterns matched" if enterprise_label == "Public" else "Inspection completed without classifier details"
    )

    return {
        "enterprise_label": enterprise_label,
        "sensitivity_score": LABEL_RANK.get(enterprise_label, 0),
        "label_source": label_source,
        "label_reason": label_reason,
        "finding_types": finding_types,
        "findings_count": len(items),
        "risk": risk or "none",
        "risk_score": int(risk_score or 0),
    }


def derive_block_metadata(
    action: str,
    label_summary: dict[str, Any] | None,
    *,
    destination_type: str = "local",
) -> dict[str, Any]:
    summary = dict(label_summary or {})
    label = str(summary.get("enterprise_label", "Public") or "Public")
    score = int(summary.get("sensitivity_score", LABEL_RANK.get(label, 0)) or 0)
    destination_type = str(destination_type or "local")

    block_candidate = False
    block_reason = ""
    blocking_supported = False
    blocking_mode = "detect_only"
    if score >= LABEL_RANK["Confidential"] and action == "move" and destination_type in {"usb", "upload", "cloud_sync"}:
        block_candidate = True
        block_reason = f"{label} file moved toward {destination_type}"
        blocking_supported = True
        blocking_mode = "agent_enforced"

    return {
        "block_candidate": block_candidate,
        "block_reason": block_reason,
        "blocking_supported": blocking_supported,
        "blocking_mode": blocking_mode,
    }
