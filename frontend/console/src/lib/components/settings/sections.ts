// Settings sections of file 08 §3.2, in the manual's order, with the pipeline_config keys (file 05 §4.6)
// each one edits. Secrets and endpoints never appear here: they live in .env (file 01 §7.1).

export interface SettingsSection {
	id: string;
	title: string;
	summary: string;
	keys: string[];
	apply: string;
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
	{
		id: 'sources',
		title: 'Sources',
		summary:
			'Roots, sign-in status, cloud-allowed roots, default origin and trust tier, download and processing scopes with live counts and a cost estimate.',
		keys: [
			'sync.download_scope',
			'processing.scope',
			'sync.download_concurrency',
			'sync.daily_delta_cron',
			'sources.origin_defaults',
			'cloud_allowed_roots'
		],
		apply: 'Hot. Widening a scope enqueues the held items in batches.'
	},
	{
		id: 'gate',
		title: 'Gate',
		summary: 'Tier-1 paths, Tier-2 extensions, quarantine patterns, large-file cap, secret patterns.',
		keys: ['gate.*'],
		apply: 'Hot. Shows how many indexed files would now be rejected before saving.'
	},
	{
		id: 'routes',
		title: 'Routes',
		summary:
			'Per route: enabled (parked counts), parser version, page-triage model, thresholds, critical field patterns, report schemas, sanity ranges, time budgets.',
		keys: [
			'routes.<X>.enabled',
			'routes.<X>.parser_version',
			'thresholds.*',
			'critical_field_patterns',
			'report_json_schemas',
			'sanity_ranges',
			'telemetry.*'
		],
		apply: 'Hot for new files. "Re-process affected documents" shows the count first.'
	},
	{
		id: 'models',
		title: 'Models',
		summary: 'Model id per task, thinking levels, daily token budget, batch windows, embedding model and reranker.',
		keys: ['models.*', 'cloud.vertex_project', 'cloud.region', 'cloud.daily_token_budget'],
		apply: 'Embedding model changes show the number of nodes to re-embed and schedule it.'
	},
	{
		id: 'translation',
		title: 'Translation & language',
		summary: 'Translation mode, kinds and languages eligible for full translation, OCR language packs and the per-script engine table.',
		keys: ['translation.mode', 'translation.full_for', 'routes.A1.ocr_engine_by_script'],
		apply: 'Switching to full shows the count and cost first, then schedules translation jobs.'
	},
	{
		id: 'chunking',
		title: 'Chunking & index',
		summary: 'Parent and child token sizes, question proxies per document kind, HNSW ef_search, RRF k, rerank top-n.',
		keys: ['chunking.*'],
		apply: 'Chunking changes re-index from the CIR as a scheduled job.'
	},
	{
		id: 'flags',
		title: 'Flags & review',
		summary: 'Severity overrides per flag and route, strict mode, auto-resolve threshold, aging SLA.',
		keys: ['flags.severity_overrides', 'flags.strict_mode'],
		apply: 'Hot.'
	},
	{
		id: 'answer',
		title: 'Answer engine',
		summary: 'External search per group, proprietary-terms list for the sanitizer, token budget per answer, latency targets, extractive fallback.',
		keys: ['answer.external_search_enabled', 'answer.external_allowed_groups', 'answer.proprietary_terms'],
		apply: 'Hot.'
	},
	{
		id: 'prompts',
		title: 'Prompts',
		summary: 'Versioned prompt texts for enrichment, vision, synthesis and the verifier; diff viewer; run on a sample.',
		keys: [],
		apply: 'Prompts are files in the repository: a new version file applies to new calls once the code pins it; llm_calls records the prompt version.'
	}
];

export function findSection(id: string): SettingsSection | undefined {
	return SETTINGS_SECTIONS.find((section) => section.id === id);
}
