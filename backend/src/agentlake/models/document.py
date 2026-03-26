"""Processed document, chunk, and citation models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentlake.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProcessedDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A fully processed document produced from a raw source file.

    Each document has YAML frontmatter conforming to the Common Data
    Ontology, a markdown body with citation links, and vector
    embeddings for semantic search.
    """

    __tablename__ = "processed_documents"

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(VARCHAR(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        VARCHAR(50),
        nullable=False,
        comment="One of: technical, business, operational, research, communication, reference.",
    )
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    frontmatter: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    entities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    processing_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    # ── Relationships ────────────────────────────────────────────────────
    source_file = relationship("File", lazy="selectin")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DocumentChunk.chunk_index",
    )
    citations: Mapped[list["Citation"]] = relationship(
        "Citation",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Citation.citation_index",
    )

    __table_args__ = (
        Index("ix_processed_documents_category", "category"),
        Index("ix_processed_documents_source_current", "source_file_id", "is_current"),
        Index(
            "ix_processed_documents_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_processed_documents_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessedDocument id={self.id} title={self.title!r} "
            f"v{self.version} current={self.is_current}>"
        )


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    """A content chunk within a processed document.

    Chunks are produced by the semantic chunker and individually
    summarised and embedded for granular search.
    """

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True
    )
    source_locator: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────────────────
    document: Mapped["ProcessedDocument"] = relationship(
        "ProcessedDocument", back_populates="chunks"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} doc={self.document_id} "
            f"idx={self.chunk_index} tokens={self.token_count}>"
        )


class Citation(UUIDPrimaryKeyMixin, Base):
    """A citation linking a processed document back to its raw source.

    Every citation uses the format
    ``[N](/api/v1/vault/files/{file_id}/download#chunk={chunk_index})``.
    """

    __tablename__ = "citations"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processed_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_locator: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    quote_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────────────────
    document: Mapped["ProcessedDocument"] = relationship(
        "ProcessedDocument", back_populates="citations"
    )
    source_file = relationship("File", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "citation_index", name="uq_citation_doc_index"
        ),
        Index("ix_citations_source_file_id", "source_file_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Citation id={self.id} [{self.citation_index}] "
            f"file={self.source_file_id} chunk={self.chunk_index}>"
        )
