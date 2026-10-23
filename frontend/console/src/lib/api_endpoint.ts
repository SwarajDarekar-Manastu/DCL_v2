// Every call from the Console to the backend lives in this file (file 08 §7, file 10 §2.1).
// Shaped by src/lib/config.ts; tokens come from the auth client set in configureApi().

import type { components, operations } from './api_schema';

// ---------------------------------------------------------------- types
// Generated from the backend's OpenAPI schema (`npm run gen:api`); never copy a backend model by hand.

type Schemas = components['schemas'];

/** backend/api/auth.py */
export type ConsoleUser = Schemas['ConsoleUser'];
export type LoginResponse = Schemas['LoginResponse'];
export type ConfigEntry = Schemas['ConfigEntry'];
export type ConfigChange = Schemas['Change'];
export type ConfigBatch = Schemas['ChangeBatch'];
export type ConfigImpact = Schemas['ImpactView'];
export type ConfigPreview = Schemas['PreviewResponse'];
export type ConfigApplied = Schemas['ApplyResponse'];
export type ConfigRollback = Schemas['RollbackRequest'];
export type LocalAccount = Schemas['UserView'];
export type LocalAccountCreate = Schemas['UserCreate'];
export type LocalAccountUpdate = Schemas['UserUpdate'];

/** backend/api/viewer.py */
export type ViewerPayload = Schemas['ViewerPayload'];
export type ViewerView = ViewerPayload['view'];
export type ViewerRegion = Schemas['Region'];
export type ResolutionStatus = Schemas['ViewerStatus'];

/** backend/api/audit.py */
export type AuditItem = Schemas['AuditItem'];
export type AuditPage = Schemas['AuditPage'];
export type AuditEntityType = Schemas['AuditEntityType'];
export type AuditFilters = NonNullable<operations['list_audit_audit_get']['parameters']['query']>;

/** backend/api/benchmark.py, backend/benchmark/catalog.py */
export type BenchmarkCategory = Schemas['BenchmarkCategory'];
export type FailureClass = Schemas['FailureClass'];
export type ExpectedBehavior = Schemas['ExpectedBehavior'];
export type CaseSpec = Schemas['CaseSpec'];
export type BenchmarkCase = Schemas['CaseView'];
export type BenchmarkCaseList = Schemas['BenchmarkCaseList'];
export type BenchmarkCaseContent = Schemas['CaseContent'];
export type BenchmarkCaseCreate = Schemas['CaseCreate'];
export type SuiteSummary = Schemas['SuiteSummary'];
export type SuiteExport = Schemas['SuiteExport'];
export type ImportCounts = Schemas['ImportCounts'];
export type RunRequest = Schemas['RunRequest'];
export type BenchmarkRun = Schemas['RunView'];
export type BenchmarkResult = Schemas['ResultView'];
export type RunResults = Schemas['RunResults'];
export type RunComparison = Schemas['RunComparison'];
export type BenchmarkCaseFilters = NonNullable<operations['get_cases_benchmark_cases_get']['parameters']['query']>;

/** backend/api/engine.py retrieval lab (S2) */
export type RetrievalLabRequest = Schemas['RetrievalLabRequest'];
export type SearchResult = Schemas['SearchResult'];
export type SearchHit = Schemas['Hit'];

/** backend/api/assets.py */
export type AssetUrl = Schemas['AssetUrl'];

// ops (backend/api/ops.py)
export type FailedTask = Schemas['FailedTask'];
export type FailedTasks = Schemas['FailedTasks'];
export type OpsSummary = Schemas['OpsSummary'];

/** backend/review/api_models.py and backend/dispatcher/contract.py (S1) */
export type FlagType = Schemas['FlagType'];
export type FlagSeverity = Schemas['FlagSeverity'];
export type CaseStatus = Schemas['CaseStatus'];
export type ReviewRoute = Schemas['Route'];
export type CaseFilters = NonNullable<operations['list_cases_review_cases_get']['parameters']['query']>;
export type CaseSummary = Schemas['CaseSummary'];
export type CaseList = Schemas['CaseList'];
export type CaseDetail = Schemas['CaseDetail'];
export type FlagView = Schemas['FlagView'];
export type Evidence = NonNullable<FlagView['evidence']>;
export type Suggestion = Schemas['Suggestion'];
export type CaseLocation = Schemas['CaseLocation'];
export type FlagResolution = Schemas['FlagResolution'];
export type Resolution = FlagResolution['resolution'];
export type ResolutionAction = Resolution['action'];
export type RuleType = Schemas['RuleType'];
export type RuleScope = Schemas['RuleScope'];
export type RuleDraft = Schemas['RuleDraft'];
export type RuleView = Schemas['RuleView'];
export type RuleList = Schemas['RuleList'];
export type RuleSimulation = Schemas['RuleSimulation'];
export type ResolveRequest = Schemas['ResolveRequest'];
export type ResolveResponse = Schemas['ResolveResponse'];
export type RejectRequest = Schemas['RejectRequest'];
export type UndoResponse = Schemas['UndoResponse'];
export type DryRunRequest = Schemas['DryRunRequest'];
export type DryRunResponse = Schemas['DryRunResponse'];
export type ChannelPreview = Schemas['ChannelPreview'];

/** backend/api/ws.py Topic (websocket frames are not in the OpenAPI schema) */
export type LiveTopic = 'case' | 'run' | 'ops';

/** backend/api/ws.py Event, as delivered in an "event" frame */
export interface LiveEvent {
	topic: LiveTopic;
	key: string;
	event: string;
	data: Record<string, unknown>;
	at: string;
}

export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly detail: string,
		/** Per-field reasons from a 422 body `{"detail": {"errors": {key: reason}}}` (settings API) */
		readonly errors: Record<string, string> = {}
	) {
		super(`${status}: ${detail}`);
	}
}

// ---------------------------------------------------------------- wiring

interface ApiWiring {
	baseUrl: string;
	wsUrl: string;
	getToken: () => Promise<string>;
	/** Called once per 401 answer, before the ApiError is thrown (local sign-in ends the session). */
	onUnauthorized?: () => void;
	fetch: typeof globalThis.fetch;
	WebSocket: typeof globalThis.WebSocket;
}

let wiring: ApiWiring | undefined;

export function configureApi(options: Pick<ApiWiring, 'baseUrl' | 'wsUrl' | 'getToken'> & Partial<ApiWiring>): void {
	wiring = {
		fetch: globalThis.fetch.bind(globalThis),
		WebSocket: globalThis.WebSocket,
		...options
	};
}

function wired(): ApiWiring {
	if (!wiring) throw new Error('configureApi() has not been called');
	return wiring;
}

async function request<T>(method: string, path: string, body?: unknown, signedIn = true): Promise<T> {
	const w = wired();
	const headers: Record<string, string> = signedIn ? { Authorization: `Bearer ${await w.getToken()}` } : {};
	if (body !== undefined) headers['Content-Type'] = 'application/json';
	const response = await w.fetch(w.baseUrl + path, {
		method,
		headers,
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		let detail = response.statusText;
		let errors: Record<string, string> = {};
		try {
			const payload = await response.json();
			if (typeof payload?.detail === 'string') detail = payload.detail;
			else if (payload?.detail?.errors && typeof payload.detail.errors === 'object') {
				errors = payload.detail.errors as Record<string, string>;
				detail = Object.entries(errors)
					.map(([key, reason]) => `${key}: ${reason}`)
					.join('; ');
			}
		} catch {
			// non-JSON error body: keep the status text
		}
		if (response.status === 401 && signedIn) w.onUnauthorized?.();
		throw new ApiError(response.status, detail, errors);
	}
	return (await response.json()) as T;
}

// ---------------------------------------------------------------- routes

/** POST /auth/login (backend/api/auth.py): local accounts; sent without a bearer token */
export function login(email: string, password: string): Promise<LoginResponse> {
	return request<LoginResponse>('POST', '/auth/login', { email, password }, false);
}

/** GET/POST/PATCH /auth/users (admin): local accounts */
export const listAccounts = () => request<LocalAccount[]>('GET', '/auth/users');
export const createAccount = (body: LocalAccountCreate) => request<LocalAccount>('POST', '/auth/users', body);
export const updateAccount = (userId: string, body: LocalAccountUpdate) =>
	request<LocalAccount>('PATCH', `/auth/users/${encodeURIComponent(userId)}`, body);

/** GET /auth/me (backend/api/auth.py) */
export function getMe(): Promise<ConsoleUser> {
	return request<ConsoleUser>('GET', '/auth/me');
}

/** GET /docs/{doc_id}/viewer?anchor=…&translate=… (backend/api/viewer.py) */
export function getViewer(docId: string, anchor: string, translate = false): Promise<ViewerPayload> {
	const query = new URLSearchParams({ anchor });
	if (translate) query.set('translate', 'true');
	return request<ViewerPayload>('GET', `/docs/${encodeURIComponent(docId)}/viewer?${query}`);
}

/** Query string of defined, non-empty values. */
function query(params: Record<string, string | number | boolean | null | undefined>): string {
	const q = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== null && value !== '') q.set(key, String(value));
	}
	const text = q.toString();
	return text ? `?${text}` : '';
}

/** GET /assets/url?uri=s3://dcl-assets/... (backend/api/assets.py): a 15-minute URL for an asset */
export function presignAsset(uri: string): Promise<AssetUrl> {
	return request<AssetUrl>('GET', `/assets/url${query({ uri })}`);
}

/** GET /audit (reviewer): audit_events newest first; entity_id may repeat */
export function listAudit(filters: AuditFilters = {}): Promise<AuditPage> {
	const { entity_id = [], ...rest } = filters;
	const q = new URLSearchParams(query(rest).slice(1));
	for (const id of entity_id) q.append('entity_id', id);
	const text = q.toString();
	return request<AuditPage>('GET', `/audit${text ? `?${text}` : ''}`);
}

// ---------------------------------------------------------------- prompt registry (backend/api/engine.py, S2)
// The routes answer untyped JSON; these mirror backend/llm_engine/prompts/registry.py.

export interface PromptVersion {
	area: string;
	name: string;
	version: string;
	number: number;
	latest: boolean;
	in_use: boolean;
	variables: string[];
	chars: number;
}
export interface PromptText extends PromptVersion {
	system: string;
	user_template: string;
}
export interface PromptDiff {
	area: string;
	a: string;
	b: string;
	unified: string;
}
export interface PromptRunRequest {
	variables: Record<string, string>;
	image_base64?: string | null;
	tier?: 'flash' | 'lite';
}
export interface PromptRunResult {
	version: string;
	model: string;
	text: string;
	latency_ms: number;
	input_tokens: number | null;
	output_tokens: number | null;
}

const promptPath = (area: string, version: string) => `/v1/prompts/${encodeURIComponent(area)}/${encodeURIComponent(version)}`;
export const listPrompts = () => request<PromptVersion[]>('GET', '/v1/prompts');
export const getPrompt = (area: string, version: string) => request<PromptText>('GET', promptPath(area, version));
export const diffPrompts = (area: string, a: string, b: string) =>
	request<PromptDiff>('GET', `/v1/prompts/${encodeURIComponent(area)}/diff/${encodeURIComponent(a)}/${encodeURIComponent(b)}`);
/** Run on sample: one real model call (reviewer or admin; it costs tokens). */
export const runPrompt = (area: string, version: string, body: PromptRunRequest) =>
	request<PromptRunResult>('POST', `${promptPath(area, version)}/run`, body);

// ---------------------------------------------------------------- sync (backend/api/sync.py, S1)

export type RootStatus = Schemas['RootView'];
export type SignInState = Schemas['SignInState'];
export type RedispatchPreview = Schemas['RedispatchPreview'];
export type RedispatchResult = Schemas['RedispatchResult'];

/** GET /sync/roots (reviewer): auth, delta times, webhook or poll, counts, waiting files, recent errors per root */
export const listRoots = () => request<RootStatus[]>('GET', '/sync/roots');
/** POST /sync/sign-in (admin): starts the device-code sign-in; GET polls its state */
export const startSignIn = () => request<SignInState>('POST', '/sync/sign-in');
export const signInState = () => request<SignInState>('GET', '/sync/sign-in');
/** POST /sync/process-everything (admin): processing.scope = [] through the versioned settings path */
export const processEverything = () => request<ConfigApplied>('POST', '/sync/process-everything');
export const redispatchPreview = (route: string) => request<RedispatchPreview>('GET', `/sync/redispatch${query({ route })}`);
export const redispatchRoute = (route: string) => request<RedispatchResult>('POST', `/sync/redispatch${query({ route })}`);

// ---------------------------------------------------------------- entities (backend/api/entities.py, S1)

export type Entity = Schemas['EntityView'];
export type EntityPage = Schemas['EntityPage'];
export type EntityType = Entity['type'];
export const searchEntities = (q: { query?: string; type?: EntityType | ''; limit?: number; offset?: number }) =>
	request<EntityPage>('GET', `/entities${query({ query: q.query, type: q.type || undefined, limit: q.limit, offset: q.offset })}`);
export const mergeEntities = (target_entity_id: string, source_entity_ids: string[]) =>
	request<Entity>('POST', '/entities/merge', { target_entity_id, source_entity_ids });
export const splitEntity = (entity_id: string, alias_keys: string[], canonical_name: string) =>
	request<Entity>('POST', '/entities/split', { entity_id, alias_keys, canonical_name });

// ---------------------------------------------------------------- settings (backend/api/settings.py, S1)

/** GET /settings?prefix (admin): current value and version of every key */
export const listSettings = (prefix = '') => request<{ items: ConfigEntry[] }>('GET', `/settings${query({ prefix: prefix || undefined })}`);
export const settingHistory = (key: string) => request<{ items: ConfigEntry[] }>('GET', `/settings/${encodeURIComponent(key)}/history`);
export const previewSettings = (body: ConfigBatch) => request<ConfigPreview>('POST', '/settings/preview', body);
export const applySettings = (body: ConfigBatch) => request<ConfigApplied>('PUT', '/settings', body);
export const rollbackSettings = (body: ConfigRollback) => request<ConfigApplied>('POST', '/settings/rollback', body);

// ---------------------------------------------------------------- ops (backend/api/ops.py)

/** GET /ops/failed-tasks (admin): the Celery dead-letter list, newest first */
/** GET /ops/summary (viewer): queue depths, documents by status, open flags, last runs, model calls today */
export const getOpsSummary = () => request<OpsSummary>('GET', '/ops/summary');
export const listFailedTasks = (limit = 100) => request<FailedTasks>('GET', `/ops/failed-tasks${query({ limit })}`);

// ---------------------------------------------------------------- benchmark (backend/api/benchmark.py)

const benchCase = (caseId: string) => `/benchmark/cases/${encodeURIComponent(caseId)}`;

export const listSuites = () => request<SuiteSummary[]>('GET', '/benchmark/suites');
export const exportSuite = (suite: string) =>
	request<SuiteExport>('GET', `/benchmark/suites/${encodeURIComponent(suite)}/export`);
export const importSuite = (suite: string, cases: BenchmarkCaseCreate[]) =>
	request<ImportCounts>('POST', `/benchmark/suites/${encodeURIComponent(suite)}/import`, { cases });
export const listBenchmarkCases = (filters: BenchmarkCaseFilters = {}) =>
	request<BenchmarkCaseList>('GET', `/benchmark/cases${query(filters)}`);
export const caseHistory = (caseId: string) => request<BenchmarkCase[]>('GET', benchCase(caseId));
export const createBenchmarkCase = (body: BenchmarkCaseCreate) => request<BenchmarkCase>('POST', '/benchmark/cases', body);
export const addCaseVersion = (caseId: string, body: BenchmarkCaseContent) =>
	request<BenchmarkCase>('POST', `${benchCase(caseId)}/versions`, body);
export const approveCase = (caseId: string) => request<BenchmarkCase>('POST', `${benchCase(caseId)}/approve`);
export const retireCase = (caseId: string) => request<BenchmarkCase>('POST', `${benchCase(caseId)}/retire`);
export const listRuns = (suite?: string, limit = 50) =>
	request<BenchmarkRun[]>('GET', `/benchmark/runs${query({ suite, limit })}`);
export const startRun = (body: RunRequest) => request<BenchmarkRun>('POST', '/benchmark/runs', body);
export const getRun = (runId: string) => request<RunResults>('GET', `/benchmark/runs/${encodeURIComponent(runId)}`);
export const cancelRun = (runId: string) =>
	request<BenchmarkRun>('POST', `/benchmark/runs/${encodeURIComponent(runId)}/cancel`);
export const compareRuns = (base: string, head: string) =>
	request<RunComparison>('GET', `/benchmark/compare${query({ base, head })}`);

/** POST /v1/retrieval/search (backend/api/engine.py, S2): the Retrieval lab */
export const retrievalSearch = (body: RetrievalLabRequest) => request<SearchResult>('POST', '/v1/retrieval/search', body);

const casePath = (caseKey: string) => `/review/cases/${encodeURIComponent(caseKey)}`;

/** GET /review/cases (backend/api/review.py, S1) */
export function listCases(filters: CaseFilters = {}): Promise<CaseList> {
	return request<CaseList>('GET', `/review/cases${query(filters)}`);
}

/** GET /review/cases/{case_key} */
export function getCase(caseKey: string): Promise<CaseDetail> {
	return request<CaseDetail>('GET', casePath(caseKey));
}

/** POST /review/cases/{case_key}/assign (null unassigns) */
export function assignCase(caseKey: string, assignee: string | null): Promise<CaseDetail> {
	return request<CaseDetail>('POST', `${casePath(caseKey)}/assign`, { assignee });
}

/** POST /review/cases/{case_key}/resolve */
export function resolveCase(caseKey: string, body: ResolveRequest): Promise<ResolveResponse> {
	return request<ResolveResponse>('POST', `${casePath(caseKey)}/resolve`, body);
}

/** POST /review/cases/{case_key}/reject */
export function rejectCase(caseKey: string, body: RejectRequest): Promise<CaseDetail> {
	return request<CaseDetail>('POST', `${casePath(caseKey)}/reject`, body);
}

/** POST /review/cases/{case_key}/undo */
export function undoCase(caseKey: string): Promise<UndoResponse> {
	return request<UndoResponse>('POST', `${casePath(caseKey)}/undo`);
}

/** POST /review/dry-run */
export function dryRun(body: DryRunRequest): Promise<DryRunResponse> {
	return request<DryRunResponse>('POST', '/review/dry-run', body);
}

/** GET /review/rules */
export function listRules(): Promise<RuleList> {
	return request<RuleList>('GET', '/review/rules');
}

/** POST /review/rules */
export function createRule(draft: RuleDraft): Promise<RuleView> {
	return request<RuleView>('POST', '/review/rules', draft);
}

/** POST /review/rules/{rule_id}/simulate */
export function simulateRule(ruleId: string): Promise<RuleSimulation> {
	return request<RuleSimulation>('POST', `/review/rules/${encodeURIComponent(ruleId)}/simulate`);
}

/** POST /review/rules/{rule_id}/deactivate (admin) */
export function deactivateRule(ruleId: string): Promise<RuleView> {
	return request<RuleView>('POST', `/review/rules/${encodeURIComponent(ruleId)}/deactivate`);
}

// ---------------------------------------------------------------- live channel (backend/api/ws.py)

export type LiveStatus = 'connecting' | 'open' | 'closed';

export interface LiveChannel {
	close(): void;
}

export interface LiveOptions {
	topics: LiveTopic[];
	onEvent: (event: LiveEvent) => void;
	onStatus?: (status: LiveStatus) => void;
	onError?: (detail: string) => void;
	/** Reconnect delays in ms; the last one repeats. */
	backoffMs?: number[];
}

const CLOSE_UNAUTHENTICATED = 4401;
const CLOSE_BAD_FRAME = 4400;

export function openLiveChannel(options: LiveOptions): LiveChannel {
	const w = wired();
	const backoff = options.backoffMs ?? [1000, 2000, 5000, 10000, 30000];
	let attempt = 0;
	let stopped = false;
	let socket: WebSocket | undefined;
	let timer: ReturnType<typeof setTimeout> | undefined;

	const connect = () => {
		options.onStatus?.('connecting');
		socket = new w.WebSocket(w.wsUrl);
		socket.onopen = async () => {
			try {
				socket?.send(JSON.stringify({ type: 'auth', token: await w.getToken() }));
			} catch (error) {
				options.onError?.(String(error));
				socket?.close();
			}
		};
		socket.onmessage = (message) => {
			const frame = JSON.parse(String(message.data));
			if (frame.type === 'ready') {
				attempt = 0;
				options.onStatus?.('open');
				socket?.send(JSON.stringify({ type: 'subscribe', topics: options.topics }));
			} else if (frame.type === 'event') {
				const { type: _type, ...event } = frame;
				options.onEvent(event as LiveEvent);
			} else if (frame.type === 'error') {
				options.onError?.(frame.detail);
			}
		};
		socket.onclose = (closed) => {
			options.onStatus?.('closed');
			if (stopped) return;
			if (closed.code === CLOSE_BAD_FRAME) {
				options.onError?.(`live channel refused a frame: ${closed.reason}`);
				return;
			}
			// 4401 (token expired or refused) reconnects too: getToken() renews the token.
			const delay = closed.code === CLOSE_UNAUTHENTICATED && attempt === 0 ? 0 : backoff[Math.min(attempt, backoff.length - 1)];
			attempt += 1;
			timer = setTimeout(connect, delay);
		};
	};

	connect();
	return {
		close() {
			stopped = true;
			if (timer) clearTimeout(timer);
			socket?.close();
		}
	};
}
