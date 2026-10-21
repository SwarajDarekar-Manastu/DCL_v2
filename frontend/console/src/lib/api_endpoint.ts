// Every call from the Console to the backend lives in this file (file 08 §7, file 10 §2.1).
// Shaped by src/lib/config.ts; tokens come from the auth client set in configureApi().

import type { ConsoleRole } from '$lib/auth/roles';

// ---------------------------------------------------------------- types (mirror backend/api/*)

/** backend/api/auth.py ConsoleUser */
export interface ConsoleUser {
	oid: string;
	name: string;
	email: string;
	roles: ConsoleRole[];
}

/** backend/api/ws.py Topic */
export type LiveTopic = 'case' | 'run' | 'ops';

/** backend/api/ws.py Event, as delivered in an "event" frame */
export interface LiveEvent {
	topic: LiveTopic;
	key: string;
	event: string;
	data: Record<string, unknown>;
	at: string;
}

/** backend/api/viewer.py ViewerPayload and parts */
export type ResolutionStatus = 'exact' | 'page_fallback' | 'document_only';

export interface ViewerRegion {
	bbox: [number, number, number, number]; // x0, y0, x1, y1 in 0..1 of the rendered image
	kind: 'cited' | 'handwriting' | 'flag';
	label: string;
	confidence: number | null;
}

export type ViewerView =
	| {
			kind: 'page';
			page_no: number;
			page_count: number;
			image_url: string;
			width: number;
			height: number;
			regions: ViewerRegion[];
			text: string;
	  }
	| {
			kind: 'image';
			image_kind: 'photo' | 'plot' | 'diagram' | 'figure';
			image_url: string;
			width: number;
			height: number;
			regions: ViewerRegion[];
			caption: string;
	  }
	| {
			kind: 'table';
			sheet_name: string | null;
			header_rows: number;
			rows: string[][];
			highlight: [number, number, number, number] | null;
	  }
	| { kind: 'code'; language: string; first_line: number; lines: string[]; highlight: [number, number] | null }
	| { kind: 'text'; text: string; breadcrumb: string }
	| { kind: 'video'; video_url: string; t_ms: number; poster_url: string | null };

export interface ViewerPayload {
	anchor: string;
	document: {
		doc_id: string;
		title: string;
		doc_kind: string;
		source_origin: 'internal' | 'external_kept';
		trust_tier: number;
		language: string | null;
		test_ids: string[];
		doc_date: string | null;
		status: string;
		open_flags: number;
	};
	resolution: { status: ResolutionStatus; message: string };
	view: ViewerView;
	links: {
		onedrive: { path: string; web_url: string }[];
		download_url: string | null;
		review_case_key: string | null;
	};
	translation: {
		source_language: string | null;
		available: boolean;
		translated_text: string | null;
		pending: boolean;
	};
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
