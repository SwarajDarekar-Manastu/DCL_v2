// Every call from the Console to the backend lives in this file (file 08 §7, file 10 §2.1).
// Shaped by src/lib/config.ts; tokens come from the auth client set in configureApi().

import type { components, operations } from './api_schema';

// ---------------------------------------------------------------- types
// Generated from the backend's OpenAPI schema (`npm run gen:api`); never copy a backend model by hand.

type Schemas = components['schemas'];

/** backend/api/auth.py */
export type ConsoleUser = Schemas['ConsoleUser'];

/** backend/api/viewer.py */
export type ViewerPayload = Schemas['ViewerPayload'];
export type ViewerView = ViewerPayload['view'];
export type ViewerRegion = Schemas['Region'];
export type ResolutionStatus = Schemas['ResolutionStatus'];

/** backend/api/assets.py */
export type AssetUrl = Schemas['AssetUrl'];

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
		readonly detail: string
	) {
		super(`${status}: ${detail}`);
	}
}

// ---------------------------------------------------------------- wiring

interface ApiWiring {
	baseUrl: string;
	wsUrl: string;
	getToken: () => Promise<string>;
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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const w = wired();
	const headers: Record<string, string> = { Authorization: `Bearer ${await w.getToken()}` };
	if (body !== undefined) headers['Content-Type'] = 'application/json';
	const response = await w.fetch(w.baseUrl + path, {
		method,
		headers,
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		let detail = response.statusText;
		try {
			const payload = await response.json();
			if (typeof payload?.detail === 'string') detail = payload.detail;
		} catch {
			// non-JSON error body: keep the status text
		}
		throw new ApiError(response.status, detail);
	}
	return (await response.json()) as T;
}

// ---------------------------------------------------------------- routes

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
