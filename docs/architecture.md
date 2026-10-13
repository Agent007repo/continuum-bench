# Architecture

The current package separates inference runners, energy integration, placement constraints, sovereignty evidence and item-cluster statistics. A runner returns text and explicitly nullable token and time-to-first-token metrics. The non-streaming HTTP adapter reports client-observed latency; it cannot establish time to first token.

The local HTTP adapter accepts loopback endpoints and does not follow redirects. Remote providers, paid calls, streaming, resume state and experiment orchestration are not implemented. The mock has a synthetic provenance label and no energy estimate.

An unverified sovereignty dimension blocks scoring instead of becoming a convenient zero. This strict rule is a design choice, not a validated standard. Residency verification is only a placeholder assertion in the prototype routing candidate. Final boundary decisions must incorporate retention, jurisdiction and data processing evidence separately.
