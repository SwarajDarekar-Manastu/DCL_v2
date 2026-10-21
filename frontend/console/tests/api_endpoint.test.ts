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
