import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, configureApi, getMe, openLiveChannel, type LiveEvent } from '../src/lib/api_endpoint';

class FakeSocket {
	static instances: FakeSocket[] = [];
	sent: unknown[] = [];
	onopen: (() => void) | null = null;
	onmessage: ((m: { data: string }) => void) | null = null;
	onclose: ((c: { code: number; reason: string }) => void) | null = null;
	closed = false;
	constructor(readonly url: string) {
		FakeSocket.instances.push(this);
	}
	send(data: string) {
		this.sent.push(JSON.parse(data));
	}
	close() {
		this.closed = true;
	}
	receive(frame: object) {
		this.onmessage?.({ data: JSON.stringify(frame) });
	}
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function wire(fetchImpl: typeof fetch, token = 'tok-1') {
	configureApi({
		baseUrl: 'http://api',
		wsUrl: 'ws://api/ws',
		getToken: async () => token,
		fetch: fetchImpl,
		WebSocket: FakeSocket as unknown as typeof WebSocket
	});
}

describe('request', () => {
	it('sends the bearer token and parses JSON', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ oid: 'o', name: 'N', email: 'e', roles: ['viewer'] })));
		wire(fetchMock as unknown as typeof fetch);
		const user = await getMe();
		expect(user.roles).toEqual(['viewer']);
		expect(fetchMock).toHaveBeenCalledWith('http://api/auth/me', {
			method: 'GET',
			headers: { Authorization: 'Bearer tok-1' },
			body: undefined
		});
	});

	it('turns an error response into ApiError with the server detail', async () => {
		wire((async () => new Response(JSON.stringify({ detail: 'token expired' }), { status: 401 })) as typeof fetch);
		await expect(getMe()).rejects.toEqual(new ApiError(401, 'token expired'));
	});
});

describe('openLiveChannel', () => {
	beforeEach(() => {
		FakeSocket.instances = [];
		wire(vi.fn() as unknown as typeof fetch, 'tok-ws');
	});
	afterEach(() => vi.useRealTimers());

	it('authenticates first, subscribes after ready, and forwards events', async () => {
		const events: LiveEvent[] = [];
		const statuses: string[] = [];
		openLiveChannel({ topics: ['ops', 'case'], onEvent: (e) => events.push(e), onStatus: (s) => statuses.push(s) });
		const socket = FakeSocket.instances[0];
		expect(socket.url).toBe('ws://api/ws');
		socket.onopen?.();
		await flush();
		expect(socket.sent).toEqual([{ type: 'auth', token: 'tok-ws' }]);
		socket.receive({ type: 'ready', user: {} });
		expect(socket.sent[1]).toEqual({ type: 'subscribe', topics: ['ops', 'case'] });
		socket.receive({ type: 'event', topic: 'case', key: 'doc:4', event: 'resolved', data: { n: 3 }, at: 't' });
		expect(events).toEqual([{ topic: 'case', key: 'doc:4', event: 'resolved', data: { n: 3 }, at: 't' }]);
		expect(statuses).toEqual(['connecting', 'open']);
	});

	it('reconnects immediately after 4401 and backs off after other drops', () => {
		vi.useFakeTimers();
		openLiveChannel({ topics: ['ops'], onEvent: () => {}, backoffMs: [1000, 5000] });
		FakeSocket.instances[0].onclose?.({ code: 4401, reason: 'token expired' });
		vi.advanceTimersByTime(0);
		expect(FakeSocket.instances).toHaveLength(2);
		FakeSocket.instances[1].onclose?.({ code: 1006, reason: '' });
		vi.advanceTimersByTime(4999);
		expect(FakeSocket.instances).toHaveLength(2);
		vi.advanceTimersByTime(1);
		expect(FakeSocket.instances).toHaveLength(3);
	});

	it('does not reconnect after a bad-frame close or after close()', () => {
		vi.useFakeTimers();
		const errors: string[] = [];
		openLiveChannel({ topics: ['ops'], onEvent: () => {}, onError: (d) => errors.push(d) });
		FakeSocket.instances[0].onclose?.({ code: 4400, reason: 'unknown frame type' });
		vi.advanceTimersByTime(60000);
		expect(FakeSocket.instances).toHaveLength(1);
		expect(errors).toEqual(['live channel refused a frame: unknown frame type']);

		const channel = openLiveChannel({ topics: ['ops'], onEvent: () => {} });
		channel.close();
		expect(FakeSocket.instances[1].closed).toBe(true);
		FakeSocket.instances[1].onclose?.({ code: 1000, reason: '' });
		vi.advanceTimersByTime(60000);
		expect(FakeSocket.instances).toHaveLength(2);
	});
});

describe('getViewer', () => {
	it('forwards the anchor untouched and asks for translation only when toggled', async () => {
		const { getViewer } = await import('../src/lib/api_endpoint');
		const fetchMock = vi.fn(async () => new Response('{}'));
		wire(fetchMock as unknown as typeof fetch);
		await getViewer('doc-1', 'cells:Run 1!A1:D20:ab12cd34ef56ab78');
		await getViewer('doc-1', 'page:3:', true);
		const urls = fetchMock.mock.calls.map((call) => (call as unknown[])[0]);
		expect(urls).toEqual([
			'http://api/docs/doc-1/viewer?anchor=cells%3ARun+1%21A1%3AD20%3Aab12cd34ef56ab78',
			'http://api/docs/doc-1/viewer?anchor=page%3A3%3A&translate=true'
		]);
	});
});

describe('review calls', () => {
	const CASE = '0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90:Sheet 1/A';

	it('sends only the filters that are set', async () => {
		const { listCases } = await import('../src/lib/api_endpoint');
		const fetchMock = vi.fn(async () => new Response('{"items":[],"next_cursor":null,"open_hard":0,"open_soft":0}'));
		wire(fetchMock as unknown as typeof fetch);
		await listCases({ severity: 'HARD', flag_type: null, root_name: '', sort: 'impact', has_suggestion: false });
		await listCases();
		const urls = fetchMock.mock.calls.map((call) => (call as unknown[])[0]);
		expect(urls).toEqual(['http://api/review/cases?severity=HARD&sort=impact&has_suggestion=false', 'http://api/review/cases']);
	});

	it('percent-encodes the case key in every case path', async () => {
		const api = await import('../src/lib/api_endpoint');
		const fetchMock = vi.fn(async () => new Response('{}'));
		wire(fetchMock as unknown as typeof fetch);
		await api.getCase(CASE);
		await api.undoCase(CASE);
		await api.assignCase(CASE, null);
		const calls = fetchMock.mock.calls.map((call) => call as unknown as [string, RequestInit]);
		const encoded = 'http://api/review/cases/0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90%3ASheet%201%2FA';
		expect(calls.map(([url, init]) => [url, init.method])).toEqual([
			[encoded, 'GET'],
			[`${encoded}/undo`, 'POST'],
			[`${encoded}/assign`, 'POST']
		]);
		expect(calls[2][1].body).toBe('{"assignee":null}');
	});

	it('posts one resolve with the per-flag resolutions and an optional rule', async () => {
		const { resolveCase } = await import('../src/lib/api_endpoint');
		const fetchMock = vi.fn(async () => new Response('{}'));
		wire(fetchMock as unknown as typeof fetch);
		const body = {
			resolutions: [
				{
					flag_id: 'f1',
					resolution: { action: 'set_unit' as const, channel: 'AIN0', unit: 'psi', quantity: 'pressure', gauge_or_abs: 'gauge' as const }
				}
			],
			rule: { rule_type: 'unit_mapping' as const, scope: { scope_folder_id: 'folder-1' }, body: { AIN0: 'psig' }, precedence: 0 }
		};
		await resolveCase(CASE, body);
		const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
		expect(JSON.parse(String(init.body))).toEqual(body);
	});
});
