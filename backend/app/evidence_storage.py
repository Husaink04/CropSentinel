"""Backward-compatible evidence storage re-export."""

from app.object_storage import Base64EvidenceStorage, StoredObject, evidence_storage, object_storage

StoredEvidence = StoredObject
EvidenceStorage = Base64EvidenceStorage
