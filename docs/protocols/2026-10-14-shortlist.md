# Model and dataset shortlist v0.1, 14 October 2026

Identity: ContinuumBench/shortlist/2026-10-14/v0.1. This is a primary-card verification record, not a frozen run inventory. It neither selects a cloud provider nor claims Mac compatibility. No model or dataset download and no inference occurred.

| Candidate upstream model | Card declaration | Exact revision | Outstanding gate |
|---|---|---|---|
| Qwen2.5-0.5B-Instruct | Apache-2.0 | Pending | Licence terms, derived artifact, runtime |
| Qwen2.5-1.5B-Instruct | Apache-2.0; pinned licence opened | 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 | Derived artifact, runtime |
| Qwen2.5-7B-Instruct | Apache-2.0 | Pending | Licence terms, derived artifact, runtime |
| Qwen2.5-14B-Instruct | Apache-2.0 | Pending | Licence terms, derived artifact, runtime |
| Qwen2.5-32B-Instruct | Apache-2.0 | Pending | Licence terms, derived artifact, runtime |
| Mistral-7B-Instruct-v0.3 | Apache-2.0 on pinned card | c170c708c41dac9275d15a8fff4eca08d52bab71 | Complete licence terms, derived artifact, runtime |

The six owner-hosted cards were opened on 14 October. URLs and exact verification states are in `configs/2026-10-14-shortlist.json`. Model names denote candidate size variants, not measured memory requirements. Four Qwen revisions remain unfrozen. Qwen 3B is excluded from this draft because its owner metadata declares a custom licence. Do not infer a size variant's rights from another variant. Revisions identify upstream repositories; conversions need independent weight/tokenizer hashes, quantization settings and backend versions before collection. Do not redistribute any weights before checking licence duties.

| Dataset candidate | Primary source opened | Permitted scope today | Decision |
|---|---|---|---|
| rajpurkar/squad | Owner Hub card and original SQuAD website | Links and metadata only; card declares CC BY-SA 4.0 | General QA control candidate; revision, full rights check, sampling and split freeze pending |
| EdinburghNLP/xsum | Owner Hub card | Links and metadata only; licence marked unknown | Exclude from current run plan until rights are verified |

Neither set supplies the digital-industries, automotive and healthcare domain evaluation required by the vacancy. Those corpora, annotation rules and task scorers remain pending. General QA accuracy cannot establish safety or utility in those sectors. The [TU Delft vacancy](https://www.academictransfer.com/en/jobs/364287/phd-position-sustainable-generative-ai-for-digital-sovereignty/) was opened again on 14 October and lists the three domains and 1 November 2026 application deadline. A thesis substitute remains unconfirmed.

No external dataset examples or model weights are redistributed here. For any later sample, pin the source revision, verify document-specific rights, record attribution and local checksum, and separate pilot from confirmatory items before collection. Public availability alone is not a reuse grant.
